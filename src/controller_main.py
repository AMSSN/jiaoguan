# -*- coding: utf-8 -*-
"""主窗口控制: 子界面装配、启动初始化、退出资源释放。"""
from PyQt6.QtWidgets import QMainWindow

from GlobalConfig import GlobalConfig, write_ModelConfig_file
from controller_data import DataController
from controller_detect import DetectController
from controller_info import InfoController
from controller_system import SystemController
from tools import logger
from ui.mainwindow import Ui_MainWindow


class MainController(QMainWindow):
    def __init__(self, parent=None):
        super(MainController, self).__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # --- 全局配置与数据库 ---
        self.gc = GlobalConfig()
        self.gc.load_app()
        self.gc.load_models()
        self.db = self.gc.get_db()
        self.db.start()  # 启动后台落盘线程

        # --- 子界面 ---
        self.infoPage = None
        self.detectPage = None
        self.dataPage = None
        self.systemPage = None
        self.init_stackedWidget()
        self.connects()

        # 默认展示首页
        self.ui.stackedWidget.setCurrentIndex(0)
        logger.info(f"{self.gc.app_name} 启动完成")

    def init_stackedWidget(self):
        # 初始化子界面
        self.infoPage = InfoController()
        self.ui.stackedWidget.insertWidget(0, self.infoPage)
        self.detectPage = DetectController()
        self.ui.stackedWidget.insertWidget(1, self.detectPage)
        self.dataPage = DataController()
        self.ui.stackedWidget.insertWidget(2, self.dataPage)
        self.systemPage = SystemController()
        self.ui.stackedWidget.insertWidget(3, self.systemPage)

    def connects(self):
        # 导航栏的按钮绑定
        page_map = [
            (self.ui.pushButton_info, 0),
            (self.ui.pushButton_detect, 1),
            (self.ui.pushButton_data, 2),
            (self.ui.pushButton_system, 3),
        ]
        for btn, idx in page_map:
            btn.clicked.connect(lambda _, i=idx: self.handle_stackedWidget_switch(i))

    def handle_stackedWidget_switch(self, index):
        self.ui.stackedWidget.setCurrentIndex(index)
        # logger.debug(f"stackedWidget切换至page:{index}")

    # ---------------- 退出释放 ----------------
    def closeEvent(self, event):
        """关闭时停止相机线程、数据库线程、日志线程并保存配置。"""
        try:
            if self.detectPage is not None:
                self.detectPage.stop()
        except Exception as e:
            logger.error(f"停止检测页异常: {e}")

        try:
            self.db.stop()
            self.db.disconnect()
        except Exception as e:
            logger.error(f"关闭数据库异常: {e}")

        try:
            self.gc.save_app()
            if self.gc.current_model_config is not None:
                write_ModelConfig_file(self.gc.current_model_config)
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

        logger.info("程序退出, 资源已释放")
        try:
            logger.shutdown()
        except Exception:
            pass

        event.accept()
