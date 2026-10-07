"""
通用日志模块 —— 适用于 PyQt 项目
=================================

特性
----
1. 后台线程运行：日志格式化、写文件、输出控制台均在独立后台线程完成，
   不阻塞 GUI 线程与主业务线程。
2. 任意线程可触发：对外 log() 内部使用 Qt 信号发射，QueuedConnection
   机制保证跨线程调用绝对安全（自动排队）。
3. UI 实时展示：可把任意 QPlainTextEdit 绑定为日志窗口，刷新在 GUI 线程
   中安全执行。
4. 单例模式：Logger.instance() 全局获取，配置一次处处可用。

注意
----
* 务必在已创建 QApplication 的 GUI 主线程中首次调用 Logger.instance()，
  否则信号所在的线程没有事件循环，排队信号将无法投递。
* init_file / add_stream_handler 建议在开始记录日志前调用（初始化阶段）。
"""

import logging
import os
import threading
import atexit
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit

# -------------------------- 日志级别常量 --------------------------
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL

_LEVEL_NAME = {
    DEBUG: "DEBUG",
    INFO: "INFO",
    WARNING: "WARNING",
    ERROR: "ERROR",
    CRITICAL: "CRITICAL",
}



# -------------------------- 信号发射器 --------------------------
class _LogEmitter(QObject):
    """驻留 GUI 主线程。任意线程调用 emit() 时，Qt 通过 QueuedConnection
    把信号安全地投递到后台工作线程的事件循环。"""
    logRequested = pyqtSignal(int, str)  # (level_no, message)

    def emit(self, level_no: int, message: str) -> None:
        self.logRequested.emit(level_no, str(message))


# -------------------------- 后台工作对象 --------------------------
class _LogWorker(QObject):
    """运行于独立 QThread，负责真正的写日志与 UI 推送。"""
    displayReady = pyqtSignal(int, str)  # 推送给 GUI 线程更新显示

    def __init__(self):
        super().__init__()
        self._logger = logging.getLogger("qt_logger")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

    def add_handler(self, handler: logging.Handler) -> None:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        self._logger.addHandler(handler)

    def on_log(self, level_no: int, message: str) -> None:
        self._logger.log(level_no, message)
        # 跨线程推送给 UI（自动排队到 GUI 线程）
        self.displayReady.emit(level_no, message)


# -------------------------- UI 显示桥接 --------------------------
class _DisplayBridge(QObject):
    """驻留 GUI 线程，把后台日志安全地刷新到控件。"""

    def __init__(self, widget: QPlainTextEdit):
        super().__init__()
        self._widget = widget
        self._colors = {
            DEBUG: QColor(120, 120, 120),
            INFO: QColor(0, 0, 0),
            WARNING: QColor(190, 130, 0),
            ERROR: QColor(200, 0, 0),
            CRITICAL: QColor(255, 0, 80),
        }

    def update(self, level_no: int, message: str) -> None:
        color = self._colors.get(level_no, QColor(0, 0, 0))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = f"[{ts}] [{_LEVEL_NAME.get(level_no, 'INFO')}] {message}\n"
        cursor = self._widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor.insertText(text, fmt)
        self._widget.setTextCursor(cursor)
        self._widget.ensureCursorVisible()


# -------------------------- 日志器（单例） --------------------------
class MyLogger(QObject):
    """通用日志器：后台线程运行 + 任意线程可触发 + UI 展示。"""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # 单例保护：重复构造时跳过初始化
        if MyLogger._instance is not None:
            return
        super().__init__()

        self._thread = QThread()
        self._thread.setObjectName("LoggerThread")
        self._worker = _LogWorker()
        self._worker.moveToThread(self._thread)

        self._emitter = _LogEmitter()
        self._emitter.logRequested.connect(self._worker.on_log)

        self._display_bridge = None
        self._thread.start()

        MyLogger._instance = self
        atexit.register(self.shutdown)

    # ---------------- 公共 API ----------------
    @classmethod
    def instance(cls) -> "MyLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = MyLogger()
        return cls._instance

    def init_file(self, filepath: str,
                  max_bytes: int = 5 * 1024 * 1024,
                  backup_count: int = 3) -> None:
        """启用滚动文件日志（后台线程写入）。"""
        from logging.handlers import RotatingFileHandler
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        handler = RotatingFileHandler(
            filepath, maxBytes=max_bytes,
            backupCount=backup_count, encoding="utf-8")
        self._worker.add_handler(handler)

    def add_stream_handler(self) -> None:
        """同时输出到控制台。"""
        self._worker.add_handler(logging.StreamHandler())

    def attach_widget(self, widget: QPlainTextEdit,
                      max_blocks: int = 5000) -> None:
        """绑定一个 QPlainTextEdit 作为日志显示窗口。"""
        widget.setMaximumBlockCount(max_blocks)
        self._display_bridge = _DisplayBridge(widget)
        self._worker.displayReady.connect(self._display_bridge.update)

    def log(self, level_no: int, message: str) -> None:
        """记录一条日志（可在任意线程调用）。"""
        self._emitter.emit(level_no, message)

    def debug(self, msg):
        self.log(DEBUG, msg)

    def info(self, msg):
        self.log(INFO, msg)

    def warning(self, msg):
        self.log(WARNING, msg)

    def error(self, msg):
        self.log(ERROR, msg)

    def critical(self, msg):
        self.log(CRITICAL, msg)

    def shutdown(self) -> None:
        """退出后台线程（程序退出时自动调用）。"""
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)


# -------------------------- 全局日志初始化 --------------------------
def log_init(log_name="logs/App.log"):
    log = MyLogger.instance()
    log.init_file(log_name)
    log.add_stream_handler()
    log.info("日志初始化完成")
    return log


# -------------------------- 使用示例 --------------------------
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QPlainTextEdit

    app = QApplication(sys.argv)

    win = QMainWindow()
    widget = QWidget()
    layout = QVBoxLayout(widget)
    log_view = QPlainTextEdit()
    log_view.setReadOnly(True)
    btn = QPushButton("在子线程里打日志")
    layout.addWidget(log_view)
    layout.addWidget(btn)
    win.setCentralWidget(widget)
    win.resize(600, 400)
    win.show()

    # 在 GUI 主线程初始化日志器并绑定控件
    log = MyLogger.instance()
    log.init_file("app.log")
    log.add_stream_handler()
    log.attach_widget(log_view)
    log.info("程序启动完成")


    # 子线程中触发日志 —— 验证跨线程安全
    def background_task():
        for i in range(5):
            MyLogger.instance().warning(f"后台任务进度 {i}/5")


    btn.clicked.connect(lambda: threading.Thread(target=background_task, daemon=True).start())

    sys.exit(app.exec())
