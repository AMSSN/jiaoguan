# -*- coding: utf-8 -*-
"""检测界面控制: 相机启停、前后端交替显示、测量判定、结果落库。"""
from datetime import datetime

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from GlobalConfig import GlobalConfig
from my_camera import Camera, CameraError
from tools import cv2, imwrite_cn, logger
from tools.lm_sql import DetectionRecord
from ui.page_detect import Ui_Form_detectPage


# --------------------------------------------------------------------------- #
# 视觉测量接口(仅定义输入输出, 算法待实现)
# --------------------------------------------------------------------------- #
def survey_image(image, model_config):
    """对单帧图像做测量。

    输入:
        image: np.ndarray 单帧图像(BGR 或灰度)
        model_config: GlobalConfig.ModelConfig 当前型号配置
    输出: dict
        inner_d  (float) 实测内径(mm)
        outer_d  (float) 实测外径(mm)
        fencen_ok (bool) 分层检测是否通过
        neiling_ok(bool) 内菱检测是否通过
        passed   (bool) 综合判定(可选, 最终以公差比较为准)
        detail   (dict) 附加信息(可含 cost_ms 等)
    """
    # TODO: 实现实际测量算法
    h, w = image.shape[:2]
    return {
        "inner_d": 0.0,
        "outer_d": 0.0,
        "fencen_ok": True,
        "neiling_ok": True,
        "passed": True,
        "detail": {"size": [w, h], "cost_ms": 0.0},
    }


class _FrameBridge(QObject):
    """相机线程 -> GUI 线程 的帧投递桥。"""
    frameReady = pyqtSignal(object)


def _ok_color(ok: bool) -> str:
    return "#009600" if ok else "#c80000"


class DetectController(QWidget):
    def __init__(self, parent=None):
        super(DetectController, self).__init__(parent)
        self.ui = Ui_Form_detectPage()
        self.ui.setupUi(self)

        self.gc = GlobalConfig()
        self.db = self.gc.get_db()
        self.camera = Camera()

        self._running = False
        self._frame_count = 0

        # 图像显示区(页面为空白 QWidget, 这里代码内嵌 QLabel)
        self.label_front = self._make_view(self.ui.widget_front_view, "前端")
        self.label_back = self._make_view(self.ui.widget_back_view, "后端")

        # 帧投递桥(相机线程 -> GUI 线程)
        self._bridge = _FrameBridge()
        self._bridge.frameReady.connect(
            self._on_frame_ui, Qt.ConnectionType.QueuedConnection)

        self._load_models()
        self._connect()
        self._set_state("已停止", False)

    # ---------------- 初始化 ----------------
    @staticmethod
    def _make_view(holder: QWidget, text: str) -> QLabel:
        lab = QLabel(text, holder)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setMinimumSize(160, 120)
        lab.setStyleSheet("border:1px solid #999; color:#888; background:#f0f0f0;")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(lab)
        return lab

    def _load_models(self):
        self.ui.comboBox.blockSignals(True)
        self.ui.comboBox.clear()
        names = list(self.gc.modelConfigs.keys())
        self.ui.comboBox.addItems(names)
        default = self.gc.detection.get("default_model") or (names[0] if names else "")
        if default:
            self.ui.comboBox.setCurrentText(default)
        self.ui.comboBox.blockSignals(False)
        if default and self.gc.set_current_model(default):
            self._refresh_spec_text()

    def _connect(self):
        self.ui.comboBox.currentTextChanged.connect(self.on_model_changed)
        self.ui.pushButton.clicked.connect(self.toggle_detect)

    def _refresh_spec_text(self):
        mc = self.gc.current_model_config
        if mc is None:
            return
        self.ui.lineEdit_inner_radius.setToolTip(
            f"合格范围: {mc.inner_lower} ~ {mc.inner_upper} mm")
        self.ui.lineEdit_outer_radius.setToolTip(
            f"合格范围: {mc.outer_lower} ~ {mc.outer_upper} mm")

    # ---------------- 型号切换 ----------------
    def on_model_changed(self, name):
        if self.gc.set_current_model(name):
            self._refresh_spec_text()

    # ---------------- 启停检测 ----------------
    def toggle_detect(self):
        if self._running:
            self.stop()
        else:
            self.start()

    def start(self):
        mc = self.gc.current_model_config  # 用的是Type.json里的曝光值
        if mc is None:
            QMessageBox.warning(self, "提示", "请先选择产品型号")
            return
        try:
            self.camera.open(dev_index=0,
                             exposure_ms=mc.camera_exposure / 1000.0,
                             gain=mc.camera_gain)
            self.camera.start_monitor(self._on_frame)
        except CameraError as e:
            QMessageBox.critical(self, "相机错误", str(e))
            logger.error(f"启动检测失败: {e}")
            return
        self._running = True
        self._frame_count = 0
        self.ui.pushButton.setText("停止检测")
        self._set_state("运行中", True)

    def stop(self):
        try:
            self.camera.stop_monitor()
            self.camera.close()
        except Exception as e:
            logger.error(f"停止相机异常: {e}")
        self._running = False
        self.ui.pushButton.setText("启动检测")
        self._set_state("已停止", False)

    # ---------------- 帧回调 ----------------
    def _on_frame(self, frame):
        """相机后台线程执行: 仅投递到 GUI 线程。"""
        if not self._running:
            return
        self._bridge.frameReady.emit(frame)


    def _on_frame_ui(self, frame):
        # 真正的帧回调函数(槽函数)
        if frame is None or not self._running:
            return
        self._frame_count += 1
        # 前后端交替: 第 1 帧前端, 第 2 帧后端, 循环
        target = self.label_front if self._frame_count % 2 == 1 else self.label_back
        self._show_image(target, frame)
        #TODO 梳理检测流程，检测-更新结果-记录结果
        mc = self.gc.current_model_config
        if mc is None:
            return
        result = survey_image(frame, mc)
        passed = self._update_result(mc, result)
        self._save_record(mc, result, passed, frame)

    def _show_image(self, label: QLabel, frame):
        try:
            if frame.ndim == 2:
                h, w = frame.shape
                qimg = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
            else:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
            pix = QPixmap.fromImage(qimg).scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(pix)
        except Exception as e:
            logger.error(f"显示图像失败: {e}")

    # ---------------- 结果判定 ----------------
    def _update_result(self, mc, result) -> bool:
        inner = float(result.get("inner_d", 0.0))
        outer = float(result.get("outer_d", 0.0))
        inner_ok = (not mc.inner_enabled) or (mc.inner_lower <= inner <= mc.inner_upper)
        outer_ok = (not mc.outer_enabled) or (mc.outer_lower <= outer <= mc.outer_upper)
        fencen_ok = bool(result.get("fencen_ok", True))
        neiling_ok = bool(result.get("neiling_ok", True))
        passed = inner_ok and outer_ok and fencen_ok and neiling_ok

        self.ui.lineEdit_inner_radius.setText(f"{inner:.3f}")
        self.ui.lineEdit_outer_radius.setText(f"{outer:.3f}")
        self.ui.lineEdit_inner_radius.setStyleSheet(f"color:{_ok_color(inner_ok)};")
        self.ui.lineEdit_outer_radius.setStyleSheet(f"color:{_ok_color(outer_ok)};")

        self._set_ok_label(self.ui.label_fencen_isok, fencen_ok, mc.fencen_enabled)
        self._set_ok_label(self.ui.label_neilng_isok, neiling_ok, mc.neiling_enabled)

        self.ui.label_icon_result.setText("合格" if passed else "不合格")
        self.ui.label_icon_result.setStyleSheet(
            f"color:{_ok_color(passed)}; font-weight:bold;")
        return passed

    @staticmethod
    def _set_ok_label(label: QLabel, ok: bool, enabled: bool):
        if not enabled:
            label.setText("--")
            label.setStyleSheet("color:#888;")
            return
        label.setText("OK" if ok else "NG")
        label.setStyleSheet(f"color:{_ok_color(ok)}; font-weight:bold;")

    def _set_state(self, text: str, running: bool):
        self.ui.label_icon_state.setText(text)
        self.ui.label_icon_state.setStyleSheet(
            f"color:{_ok_color(running)}; font-weight:bold;")

    # ---------------- 落库/存图 ----------------
    def _save_record(self, mc, result, passed, frame):
        detail = dict(result.get("detail", {}) or {})
        record = DetectionRecord(
            role=mc.name,
            result="OK" if passed else "NG",
            inner_d=float(result.get("inner_d", 0.0)),
            outer_d=float(result.get("outer_d", 0.0)),
            passed=passed,
            detail=detail,
        )
        try:
            self.db.enqueue_detection(record)   # 后台写线程落盘, 回调驱动首页刷新
        except Exception as e:
            logger.error(f"检测记录入队失败: {e}")

        if self.gc.save_image or mc.save_image:
            self._save_image(mc, frame)

    def _save_image(self, mc, frame):
        try:
            save_dir = self.gc.image_dir
            save_dir.mkdir(parents=True, exist_ok=True)
            name = f"{mc.name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            imwrite_cn(str(save_dir / name), frame)
        except Exception as e:
            logger.error(f"保存图像失败: {e}")
