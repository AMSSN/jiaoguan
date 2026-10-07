# -*- coding: utf-8 -*-
"""系统界面控制: 相机参数配置 / 连接测试 / 型号管理 / 是否存图。

注意: page_system.ui 只有一个占位 QLabel, 没有任何可编辑控件;
为遵守"不修改 .ui"的约束, 这里在代码中动态创建所需控件并加入布局。
"""
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from GlobalConfig import GlobalConfig, write_ModelConfig_file
from my_camera import Camera
from tools import logger
from ui.page_system import Ui_Form_systemPage


class SystemController(QWidget):
    def __init__(self, parent=None):
        super(SystemController, self).__init__(parent)
        self.ui = Ui_Form_systemPage()
        self.ui.setupUi(self)

        self.gc = GlobalConfig()
        self.camera = Camera()

        self._build_ui()
        self._load_from_config()
        self._connect()

    # ---------------- 动态构建控件 ----------------
    def _build_ui(self):
        self.ui.label.hide()          # 隐藏占位 label
        root = QVBoxLayout(self)

        # --- 相机配置 ---
        cam_box = QGroupBox("相机配置", self)
        form = QFormLayout(cam_box)
        self.spin_exposure = QDoubleSpinBox(cam_box)
        self.spin_exposure.setRange(1.0, 1000000.0)
        self.spin_exposure.setSuffix(" ms")
        self.spin_gain = QDoubleSpinBox(cam_box)
        self.spin_gain.setRange(0.0, 100.0)
        self.chk_save_image = QCheckBox("保存检测图像", cam_box)

        self.btn_apply = QPushButton("应用参数", cam_box)
        self.btn_test = QPushButton("测试连接", cam_box)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_test)

        self.label_cam_state = QLabel("未测试", cam_box)
        form.addRow("曝光", self.spin_exposure)
        form.addRow("增益", self.spin_gain)
        form.addRow("", self.chk_save_image)
        form.addRow(btn_row)
        form.addRow("状态", self.label_cam_state)
        root.addWidget(cam_box)

        # --- 型号管理 ---
        model_box = QGroupBox("型号管理", self)
        mform = QFormLayout(model_box)
        self.combo_model = QComboBox(model_box)
        self.edit_inner_lower = QLineEdit(model_box)
        self.edit_inner_upper = QLineEdit(model_box)
        self.edit_outer_lower = QLineEdit(model_box)
        self.edit_outer_upper = QLineEdit(model_box)
        self.btn_save_model = QPushButton("保存型号", model_box)
        mform.addRow("型号", self.combo_model)
        mform.addRow("内径下限(mm)", self.edit_inner_lower)
        mform.addRow("内径上限(mm)", self.edit_inner_upper)
        mform.addRow("外径下限(mm)", self.edit_outer_lower)
        mform.addRow("外径上限(mm)", self.edit_outer_upper)
        mform.addRow("", self.btn_save_model)
        root.addWidget(model_box)
        root.addStretch(1)

    # ---------------- 回填配置 ----------------
    def _load_from_config(self):
        cam = self.gc.first_camera()
        # app.json 中 exposure 以微秒存储, 界面以毫秒展示
        self.spin_exposure.setValue(float(cam.get("exposure", 5000.0)) / 1000.0)
        self.spin_gain.setValue(float(cam.get("gain", 1.0)))
        self.chk_save_image.setChecked(self.gc.save_image)

        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        self.combo_model.addItems(list(self.gc.modelConfigs.keys()))
        if self.gc.current_model:
            self.combo_model.setCurrentText(self.gc.current_model)
        self.combo_model.blockSignals(False)
        self._load_model_fields()

    def _load_model_fields(self):
        mc = self.gc.find_model(self.combo_model.currentText())
        if mc is None:
            for edit in (self.edit_inner_lower, self.edit_inner_upper,
                         self.edit_outer_lower, self.edit_outer_upper):
                edit.setText("")
            return
        self.spin_exposure.setValue(mc.camera_exposure/1000)
        self.spin_gain.setValue(mc.camera_gain)
        self.edit_inner_lower.setText(str(mc.inner_lower))
        self.edit_inner_upper.setText(str(mc.inner_upper))
        self.edit_outer_lower.setText(str(mc.outer_lower))
        self.edit_outer_upper.setText(str(mc.outer_upper))

    # ---------------- 事件绑定 ----------------
    def _connect(self):
        self.btn_apply.clicked.connect(self.on_apply_params)  # 应用参数按钮
        self.btn_test.clicked.connect(self.on_test_connection)  # 测试连接按钮
        self.chk_save_image.toggled.connect(self.on_save_image_toggled) # 是否保存图片单选框
        self.combo_model.currentIndexChanged.connect(self._load_model_fields)  # 型号的多选框
        self.btn_save_model.clicked.connect(self.on_save_model)  # 保存型号按钮


    # ---------------- 槽函数 ----------------
    def on_apply_params(self):
        exposure_ms = self.spin_exposure.value()
        gain = self.spin_gain.value()
        try:
            self.camera.set_params(exposure_ms, gain)
            # 写入到全局配置文件
            # TODO 整个逻辑要从双相机改为单相机！！！！
            cam = self.gc.first_camera()
            cam["exposure"] = exposure_ms * 1000.0
            cam["gain"] = gain
            self.gc.save_app()
            self.label_cam_state.setText("参数已应用")
        except Exception as e:  # 相机未打开等
            logger.warning(f"应用相机参数异常: {e}")


    def on_test_connection(self):
        ok, msg = self.camera.test_connection()
        self.label_cam_state.setText(msg)
        self.label_cam_state.setStyleSheet(
            "color: #009600;" if ok else "color: #c80000;")
        (logger.info if ok else logger.warning)(f"相机连接测试: {msg}")

    def on_save_image_toggled(self, checked):
        self.gc.app["save_image"] = bool(checked)
        self.gc.save_app()

    def on_save_model(self):
        mc = self.gc.find_model(self.combo_model.currentText())
        if mc is None:
            return
        try:
            items = mc.items
            for key, lo, hi in (("inner_radius", self.edit_inner_lower, self.edit_inner_upper),
                                ("outer_radius", self.edit_outer_lower, self.edit_outer_upper)):
                node = items.setdefault(key, {})
                node["lower"] = float(lo.text())
                node["upper"] = float(hi.text())
            cam_items = mc.camera
            cam_items["exposure"] = int(self.spin_exposure.value() * 1000)  # 转为微秒，与 on_apply_params / 加载处保持一致
            cam_items["gain"] = self.spin_gain.value()  # 配置里 gain 是浮点，不要 int()
        except ValueError:
            self.label_cam_state.setText("型号参数格式错误")
            return
        write_ModelConfig_file(mc)
        self.label_cam_state.setText(f"型号 {mc.name} 已保存")
