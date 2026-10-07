# -*- coding: utf-8 -*-
"""相机封装(my_camera)

- 单台 MVS 相机, 硬件外触发;
- 后台监控线程: 每被触发一次取一帧, 转成 numpy 图像后回调;
- 次要功能: 参数配置(曝光/增益)与连接测试(供系统界面调用)。

用法::

    cam = Camera()
    cam.open(dev_index=0, exposure_ms=30, gain=1.0)
    cam.start_monitor(on_frame)   # on_frame(np.ndarray) 在后台线程执行
    ...
    cam.stop_monitor()
    cam.close()
"""
import platform
import threading

import numpy as np

from tools import logger

try:
    from mdvs_camera_py import mvsdk
except Exception as e:  # SDK 不可用时, 程序其余功能仍可运行
    mvsdk = None
    _SDK_IMPORT_ERROR = str(e)
else:
    _SDK_IMPORT_ERROR = ""

GRAB_TIMEOUT_MS = 500   # 取图等待时间(硬触发下超时属正常路径)


class CameraError(Exception):
    """相机相关异常统一出口。"""


class Camera:
    def __init__(self):
        self.hCamera = 0
        self.cap = None
        self.pFrameBuffer = 0
        self.mono = False
        self.exposure_ms = 30.0
        self.gain = 1.0
        self._callback = None
        self._thread = None
        self._stop_event = threading.Event()
        self._last_error = ""

    # ---------------- 设备信息 ----------------
    @staticmethod
    def list_devices():
        """枚举相机, 返回 [{'index','name','port'}, ...]。"""
        if mvsdk is None:
            raise CameraError(f"相机SDK不可用: {_SDK_IMPORT_ERROR}")
        devs = mvsdk.CameraEnumerateDevice()
        return [{"index": i, "name": d.GetFriendlyName(), "port": d.GetPortType()}
                for i, d in enumerate(devs)]

    def is_open(self) -> bool:
        return self.hCamera != 0

    # ---------------- 打开/参数 ----------------
    def open(self, dev_index=0, exposure_ms=None, gain=None, trigger=True):
        """打开相机; trigger=True 使用硬件外触发, False 为连续采集。"""
        if mvsdk is None:
            raise CameraError(f"相机SDK不可用: {_SDK_IMPORT_ERROR}")
        if self.is_open():
            return
        devs = mvsdk.CameraEnumerateDevice()
        if len(devs) < 1:
            raise CameraError("未找到相机, 请检查连接")
        idx = dev_index if 0 <= dev_index < len(devs) else 0
        dev = devs[idx]
        try:
            self.hCamera = mvsdk.CameraInit(dev, -1, -1)
        except mvsdk.CameraException as e:
            raise CameraError(f"打开相机失败({e.error_code}): {e.message}") from e

        try:
            self.cap = mvsdk.CameraGetCapability(self.hCamera)
            self.mono = (self.cap.sIspCapacity.bMonoSensor != 0)
            fmt = (mvsdk.CAMERA_MEDIA_TYPE_MONO8 if self.mono
                   else mvsdk.CAMERA_MEDIA_TYPE_BGR8)
            mvsdk.CameraSetIspOutFormat(self.hCamera, fmt)

            if trigger:
                mvsdk.CameraSetTriggerMode(self.hCamera, 1)
                mvsdk.CameraSetExtTrigSignalType(
                    self.hCamera, mvsdk.EXT_TRIG_LEADING_EDGE)
            else:
                mvsdk.CameraSetTriggerMode(self.hCamera, 0)

            self.exposure_ms = float(exposure_ms) if exposure_ms else self.exposure_ms
            self.gain = float(gain) if gain else self.gain
            mvsdk.CameraSetAeState(self.hCamera, 0)  # 手动曝光
            mvsdk.CameraSetExposureTime(self.hCamera, self.exposure_ms * 1000.0)
            self._apply_gain()
            mvsdk.CameraPlay(self.hCamera)

            size = (self.cap.sResolutionRange.iWidthMax
                    * self.cap.sResolutionRange.iHeightMax
                    * (1 if self.mono else 3))
            self.pFrameBuffer = mvsdk.CameraAlignMalloc(size, 16)
        except mvsdk.CameraException as e:
            self._release_sdk()
            raise CameraError(f"相机初始化失败({e.error_code}): {e.message}") from e

        logger.info(f"相机已打开: {dev.GetFriendlyName()} "
                    f"(触发={'硬触发' if trigger else '连续'}, "
                    f"曝光={self.exposure_ms}ms, 增益={self.gain})")

    def _apply_gain(self):
        setter = getattr(mvsdk, "CameraSetAnalogGainX", None)
        if setter is not None and self.is_open():
            try:
                setter(self.hCamera, float(self.gain))
            except Exception as e:
                logger.warning(f"设置增益失败: {e}")

    def set_params(self, exposure_ms=None, gain=None):
        """运行时修改曝光/增益(相机未打开时仅记录)。"""
        if exposure_ms is not None:
            self.exposure_ms = float(exposure_ms)
            if self.is_open():
                mvsdk.CameraSetExposureTime(self.hCamera, self.exposure_ms * 1000.0)
        if gain is not None:
            self.gain = float(gain)
            self._apply_gain()
        logger.info(f"相机参数已更新: 曝光={self.exposure_ms}ms, 增益={self.gain}")

    def test_connection(self, dev_index=0):
        """测试相机连接, 返回 (ok: bool, message: str); 不影响已打开的相机。"""
        if mvsdk is None:
            return False, f"相机SDK不可用: {_SDK_IMPORT_ERROR}"
        try:
            devs = mvsdk.CameraEnumerateDevice()
            if len(devs) < 1:
                return False, "未找到相机设备"
            names = ", ".join(d.GetFriendlyName() for d in devs)
            if self.is_open():
                return True, f"已连接 {len(devs)} 台: {names}"
            idx = dev_index if 0 <= dev_index < len(devs) else 0
            h = mvsdk.CameraInit(devs[idx], -1, -1)
            mvsdk.CameraUnInit(h)
            return True, f"连接正常: {names}"
        except mvsdk.CameraException as e:
            return False, f"连接失败({e.error_code}): {e.message}"
        except Exception as e:
            return False, f"连接失败: {e}"

    # ---------------- 后台监控线程 ----------------
    def start_monitor(self, on_frame):
        """启动监控线程; on_frame(frame: np.ndarray) 在后台线程被调用。"""
        if not self.is_open():
            raise CameraError("相机未打开")
        if self._thread is not None and self._thread.is_alive():
            return
        self._callback = on_frame
        self._last_error = ""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, name="cam-monitor", daemon=True)
        self._thread.start()
        logger.info("相机监控线程已启动")

    def stop_monitor(self):
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=3)
        self._thread = None
        logger.info("相机监控线程已停止")

    @property
    def last_error(self) -> str:
        return self._last_error

    def _monitor_loop(self):
        while not self._stop_event.is_set():
            try:
                pRaw, head = mvsdk.CameraGetImageBuffer(self.hCamera, GRAB_TIMEOUT_MS)
            except mvsdk.CameraException as e:
                if e.error_code == mvsdk.CAMERA_STATUS_TIME_OUT:
                    continue  # 未收到触发, 属正常
                self._last_error = f"取图失败({e.error_code}): {e.message}"
                logger.error(self._last_error)
                break
            try:
                mvsdk.CameraImageProcess(self.hCamera, pRaw, self.pFrameBuffer, head)
                mvsdk.CameraReleaseImageBuffer(self.hCamera, pRaw)
                if platform.system() == "Windows":
                    mvsdk.CameraFlipFrameBuffer(self.pFrameBuffer, head, 1)
                frame = self._buffer_to_numpy(head)
                if frame is not None and self._callback is not None:
                    self._callback(frame)
            except Exception as e:
                self._last_error = f"图像处理失败: {e}"
                logger.error(self._last_error)

    def _buffer_to_numpy(self, head):
        data = (mvsdk.c_ubyte * head.uBytes).from_address(self.pFrameBuffer)
        frame = np.frombuffer(data, dtype=np.uint8)
        # 黑白相机返回 2D 灰度(h, w), 彩色返回 (h, w, 3)
        if head.uiMediaType == mvsdk.CAMERA_MEDIA_TYPE_MONO8:
            return frame.reshape((head.iHeight, head.iWidth)).copy()
        return frame.reshape((head.iHeight, head.iWidth, 3)).copy()

    # ---------------- 释放 ----------------
    def _release_sdk(self):
        if self.hCamera:
            try:
                mvsdk.CameraUnInit(self.hCamera)
            except Exception:
                pass
            self.hCamera = 0
        if self.pFrameBuffer:
            try:
                mvsdk.CameraAlignFree(self.pFrameBuffer)
            except Exception:
                pass
            self.pFrameBuffer = 0

    def close(self):
        self.stop_monitor()
        self._release_sdk()
        logger.info("相机已释放")



