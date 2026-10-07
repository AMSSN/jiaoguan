#coding=utf-8
"""
demo_cam.py - 硬件触发连续监控示例

功能：
  1. 设置相机参数（以硬件硬触发方式工作）。
  2. 启动一个后台线程持续监控相机：每次相机被外部硬触发一次，
     就抓取一帧图像并以“当前时间”命名保存到本地。

运行方式：
  python demo_cam.py
  按 'q' 或 Ctrl+C 退出程序（后台线程会停止，相机被正常释放）。
"""
import os
import sys
import time
import threading
from datetime import datetime

from mdvs_camera_py import mvsdk
import platform


# ----------------------------------------------------------------------------
# 可调整的配置参数
# ----------------------------------------------------------------------------
SAVE_DIR = "mdvs_camera_py/capture"  # 图片保存目录
EXPOSURE_MS = 30                # 曝光时间（毫秒）
# TRIG_SIGNAL_TYPE = mvsdk.EXT_TRIG_HIGH_LEVEL
TRIG_SIGNAL_TYPE = mvsdk.EXT_TRIG_LEADING_EDGE  # 硬触发信号：上升沿
                                            # 可选：EXT_TRIG_TRAILING_EDGE 下降沿 /
                                            # EXT_TRIG_HIGH_LEVEL / EXT_TRIG_LOW_LEVEL /
                                            # EXT_TRIG_DOUBLE_EDGE
GRAB_TIMEOUT_MS = 5000          # 每次取图的最大等待时间（毫秒），超时则继续循环
IMAGE_FORMAT = mvsdk.FILE_PNG   # 保存格式：FILE_PNG / FILE_JPG / FILE_BMP


class HardTriggerCamera(object):
    """封装一台以硬件触发方式工作的相机，并提供后台监控线程。"""

    def __init__(self):
        self.hCamera = 0
        self.cap = None
        self.pFrameBuffer = 0
        self.monoCamera = False
        self._thread = None
        self._stop_event = threading.Event()

    # ----------------------------- 初始化与参数设置 -----------------------------
    def open(self, dev_index=None):
        # 枚举相机
        DevList = mvsdk.CameraEnumerateDevice()
        nDev = len(DevList)
        if nDev < 1:
            raise RuntimeError("未找到相机，请检查连接。")

        for i, DevInfo in enumerate(DevList):
            print("{}: {} {}".format(i, DevInfo.GetFriendlyName(), DevInfo.GetPortType()))

        if dev_index is None:
            dev_index = 0 if nDev == 1 else int(input("请选择相机序号: "))
        DevInfo = DevList[dev_index]
        print("打开相机: {}".format(DevInfo))

        # 打开相机
        self.hCamera = mvsdk.CameraInit(DevInfo, -1, -1)

        # 获取相机特性描述
        self.cap = mvsdk.CameraGetCapability(self.hCamera)

        # 判断黑白 / 彩色相机
        self.monoCamera = (self.cap.sIspCapacity.bMonoSensor != 0)
        if self.monoCamera:
            mvsdk.CameraSetIspOutFormat(self.hCamera, mvsdk.CAMERA_MEDIA_TYPE_MONO8)
        else:
            mvsdk.CameraSetIspOutFormat(self.hCamera, mvsdk.CAMERA_MEDIA_TYPE_BGR8)

        # ===== 设置触发方式为“硬触发” =====
        # iModeSel=2 ->（使用外部硬触发信号）
        mvsdk.CameraSetTriggerMode(self.hCamera, 2)
        # 配置外部触发信号类型（上升沿 / 下降沿 / 高/低电平 / 双沿）
        mvsdk.CameraSetExtTrigSignalType(self.hCamera, TRIG_SIGNAL_TYPE)
        mvsdk.CameraSetExtTrigJitterTime(self.hCamera, 1000*1000)
        mvsdk.CameraSetExtTrigDelayTime(self.hCamera, 200*1000)
        print("触发方式已设置为：硬件触发（信号类型={}）".format(TRIG_SIGNAL_TYPE))

        # 手动曝光
        mvsdk.CameraSetAeState(self.hCamera, 0)
        mvsdk.CameraSetExposureTime(self.hCamera, EXPOSURE_MS * 1000)

        # 让 SDK 内部取图线程开始工作（触发模式下，Play 后等待硬触发）
        mvsdk.CameraPlay(self.hCamera)

        # 计算并分配 RGB buffer
        FrameBufferSize = (self.cap.sResolutionRange.iWidthMax
                           * self.cap.sResolutionRange.iHeightMax
                           * (1 if self.monoCamera else 3))
        self.pFrameBuffer = mvsdk.CameraAlignMalloc(FrameBufferSize, 16)

        print("相机初始化完成，等待硬件触发...")

    # ----------------------------- 后台监控线程 -----------------------------
    def start_monitor(self):
        if self._thread is not None and self._thread.is_alive():
            print("监控线程已在运行。")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, name="cam-monitor", daemon=True)
        self._thread.start()

    def stop_monitor(self):
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=3)
        self._thread = None

    def _monitor_loop(self):
        """持续监控相机：每收到一次硬触发就抓取一帧并保存到文件。"""
        if not os.path.isdir(SAVE_DIR):
            os.makedirs(SAVE_DIR)

        count = 0
        while not self._stop_event.is_set():
            try:
                # 触发模式下，CameraGetImageBuffer 会阻塞直到收到一次硬触发
                pRawData, FrameHead = mvsdk.CameraGetImageBuffer(self.hCamera, GRAB_TIMEOUT_MS)
                print(f"try-hard-trigger({count})")
            except mvsdk.CameraException as e:
                if e.error_code == mvsdk.CAMERA_STATUS_TIME_OUT:
                    # 超时属于正常情况，继续等待下一次触发
                    continue
                print("取图失败({}): {}".format(e.error_code, e.message))
                break

            # ISP 处理
            mvsdk.CameraImageProcess(self.hCamera, pRawData, self.pFrameBuffer, FrameHead)
            mvsdk.CameraReleaseImageBuffer(self.hCamera, pRawData)

            # Windows 下图像上下颠倒，需翻转为正
            if platform.system() == "Windows":
                mvsdk.CameraFlipFrameBuffer(self.pFrameBuffer, FrameHead, 1)

            # 以当前时间命名图片：YYYY-MM-DD_HH-MM-SS-ffffff.png
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            file_path = os.path.join(SAVE_DIR, "{}.png".format(timestamp))
            # print(f"({count}) file_path:{file_path}")
            status = mvsdk.CameraSaveImage(
                self.hCamera, file_path, self.pFrameBuffer, FrameHead, IMAGE_FORMAT, 100)
            if status == mvsdk.CAMERA_STATUS_SUCCESS:
                count += 1
                print("[第{:>2d}张] 已保存: {}".format(count, file_path))
            else:
                print("保存图片失败, err={}".format(status))

    # ----------------------------- 释放资源 -----------------------------
    def close(self):
        self.stop_monitor()
        if self.hCamera != 0:
            mvsdk.CameraUnInit(self.hCamera)
            self.hCamera = 0
        if self.pFrameBuffer != 0:
            mvsdk.CameraAlignFree(self.pFrameBuffer)
            self.pFrameBuffer = 0


def main():
    cam = HardTriggerCamera()
    try:
        cam.open()
        cam.start_monitor()
        print("后台监控线程已启动，按 'q' 键退出...")
        # 主线程保持运行，等待用户退出
        while True:
            ch = input("输入 'q' 退出: ").strip().lower()
            if ch == 'q':
                break
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在退出...")
    except RuntimeError as e:
        print("错误: {}".format(e))
    finally:
        cam.close()
        print("相机已释放，程序结束。")


if __name__ == "__main__":
    main()
