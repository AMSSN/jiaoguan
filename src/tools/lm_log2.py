"""
通用日志模块（Qt / 非 Qt 解耦版）
================================

特性
----
1. 始终可用：底层基于标准 logging + 后台 threading.Thread + queue.Queue，
   不依赖 Qt，没有 QApplication 也能正常写文件 / 控制台。
2. 可选 UI：仅当环境安装了 PyQt6，且通过 attach_widget(widget) 传入
   QPlainTextEdit 时，才把日志实时显示到控件（需 QApplication 已启动）。
3. 非 Qt 回调：set_display_callback(cb) 可在无 Qt 时把日志推给任意回调。
4. 退出安全：stop() + join() 保证队列排空，日志不丢失。
5. 单例：MyLogger.instance() 全局唯一。

注意
----
* 若使用 attach_widget(widget)，务必在已创建 QApplication 并进入事件循环后调用，
  否则 Qt 信号无法投递到 GUI 线程（只影响显示，不影响文件/控制台输出）。
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
from datetime import datetime

# -------------------------- 是否具备 Qt 能力 --------------------------
try:
    from PyQt6.QtCore import QObject, pyqtSignal, Qt
    from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
    from PyQt6.QtWidgets import QPlainTextEdit
    HAS_QT = True
except Exception:  # pragma: no cover - 无 PyQt6 环境
    HAS_QT = False
    QObject = pyqtSignal = Qt = QColor = QTextCharFormat = QTextCursor = QPlainTextEdit = None

# -------------------------- 日志级别常量 --------------------------
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL

_LEVEL_NAME = {
    DEBUG: "DEBUG", INFO: "INFO", WARNING: "WARNING",
    ERROR: "ERROR", CRITICAL: "CRITICAL",
}

_DEFAULT_FMT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")


# -------------------------- Qt 相关（仅 HAS_QT 时定义） --------------------------
if HAS_QT:
    class _LogEmitter(QObject):
        """驻留 GUI 线程。后台线程调用 emit() 时，Qt 通过 QueuedConnection
        把信号安全地投递到 GUI 线程。"""
        logRequested = pyqtSignal(int, str)

        def emit(self, level_no: int, message: str) -> None:
            self.logRequested.emit(level_no, str(message))

    class _DisplayBridge(QObject):
        """驻留 GUI 线程，把日志安全地刷新到 QPlainTextEdit。"""
        def __init__(self, widget: "QPlainTextEdit"):
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


# -------------------------- 后台工作线程（始终可用） --------------------------
class _LogWorker(threading.Thread):
    """纯 Python 后台线程：从队列取日志 → 写文件/控制台 → 可选推送给 UI。"""
    def __init__(self):
        super().__init__(daemon=True, name="LoggerThread")
        self._logger = logging.getLogger("decoupled_logger")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._queue: "queue.Queue" = queue.Queue()
        self._should_stop = threading.Event()   # ✅ 改名，避免与 Thread._stop 冲突
        self._display = None

    def add_handler(self, handler: logging.Handler) -> None:
        handler.setFormatter(_DEFAULT_FMT)
        self._logger.addHandler(handler)

    def submit(self, level: int, message: str) -> None:
        self._queue.put((level, str(message)))

    def set_display(self, cb) -> None:
        self._display = cb

    def run(self) -> None:
        while not self._should_stop.is_set() or not self._queue.empty():
            try:
                level, msg = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._process(level, msg)
            self._queue.task_done()

    def _process(self, level: int, msg: str) -> None:
        self._logger.log(level, msg)
        if self._display is not None:
            try:
                self._display(level, msg)
            except Exception:
                pass

    def stop(self) -> None:
        self._should_stop.set()     # ✅ 对应改名



# -------------------------- 日志器（单例） --------------------------
class MyLogger:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        if MyLogger._instance is not None:
            return  # 单例保护
        self._worker = _LogWorker()
        self._started = False
        MyLogger._instance = self
        atexit.register(self.shutdown)

    @classmethod
    def instance(cls) -> "MyLogger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = MyLogger()
        return cls._instance

    # ---------------- 配置 API ----------------
    def start(self) -> "MyLogger":
        if not self._started:
            self._worker.start()
            self._started = True
        return self

    def set_level(self, level) -> "MyLogger":
        self._worker._logger.setLevel(level)
        return self

    def init_file(self, filepath: str = "logs/App.log",
                  max_bytes: int = 5 * 1024 * 1024,
                  backup_count: int = 3) -> "MyLogger":
        from logging.handlers import RotatingFileHandler
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        handler = RotatingFileHandler(
            filepath, maxBytes=max_bytes,
            backupCount=backup_count, encoding="utf-8")
        self._worker.add_handler(handler)
        return self

    def add_stream_handler(self) -> "MyLogger":
        self._worker.add_handler(logging.StreamHandler())
        return self

    def attach_widget(self, widget, max_blocks: int = 5000) -> "MyLogger":
        """绑定 QPlainTextEdit 作为日志窗口（需 PyQt6 + 已启动 QApplication）。"""
        if not HAS_QT:
            raise RuntimeError(
                "attach_widget 需要 PyQt6，但当前环境 HAS_QT=False。"
                "可改用 set_display_callback 传入纯 Python 回调。")
        if not isinstance(widget, QPlainTextEdit):
            raise TypeError("widget 必须是 PyQt6.QtWidgets.QPlainTextEdit")
        widget.setMaximumBlockCount(max_blocks)
        emitter = _LogEmitter()
        bridge = _DisplayBridge(widget)
        emitter.logRequested.connect(bridge.update, Qt.QueuedConnection)
        self._worker.set_display(lambda level, msg: emitter.emit(level, msg))
        return self

    def set_display_callback(self, cb) -> "MyLogger":
        """非 Qt 环境：传入 (level, msg) -> None 的回调，在后台线程执行。"""
        if cb is not None and not callable(cb):
            raise TypeError("cb 必须可调用")
        self._worker.set_display(cb)
        return self

    # ---------------- 写日志 API ----------------
    def _log(self, level: int, message: str) -> None:
        self.start()
        self._worker.submit(level, message)

    def debug(self, msg):   self._log(DEBUG, msg)
    def info(self, msg):    self._log(INFO, msg)
    def warning(self, msg): self._log(WARNING, msg)
    def error(self, msg):   self._log(ERROR, msg)
    def critical(self, msg): self._log(CRITICAL, msg)

    def shutdown(self) -> None:
        self._worker.stop()
        self._worker.join(timeout=3)


# -------------------------- 全局日志初始化 --------------------------
def log_init(log_name: str = "logs/App.log",
             widget=None,
             level=logging.DEBUG,
             console: bool = True) -> "MyLogger":
    """
    log_name : 日志文件路径（默认 logs/App.log，按大小滚动）
    widget   : PyQt6 的 QPlainTextEdit，传了就绑定 UI 显示（可选）
    level    : 日志级别
    console  : 是否同时输出到控制台
    """
    log = MyLogger.instance()
    log.init_file(log_name)
    if console:
        log.add_stream_handler()
    if widget is not None:
        log.attach_widget(widget)
    log.set_level(level)
    log.info("日志初始化完成")
    return log


# -------------------------- 使用示例 --------------------------
if __name__ == "__main__":
    # 1) 无 Qt：直接可用
    logger = log_init()

    # 2) 有 Qt：传入 widget（需在 QApplication 启动后）
    # import sys
    # from PyQt6.QtWidgets import QApplication, QPlainTextEdit
    # app = QApplication(sys.argv)
    # log = log_init(widget=some_plaintextedit)

    logger.info("hello, decoupled logger")
    logger.warning("即便没有 QApplication 也能写入文件/控制台")
