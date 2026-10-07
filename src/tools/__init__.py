__version__ = "2.0.0"
__author__ = "jlm"

# 只能导入一次该文件夹  from tools import *


# from .globalM import set_value, get_value
from .lm_log2 import (
    MyLogger, log_init, HAS_QT,
    DEBUG, INFO, WARNING, ERROR, CRITICAL,
)
# from .lm_sql import init_db
from .lm_tools import OrderedSetList, imread_cn, imwrite_cn
# from .authorize import MachineCodeThread, ActivationDialog, CodeDecryted
import os
import cv2
import numpy as np


# # 初始化相关工具
logger = log_init()

# res = init_db()
# logger.info(f"init SQL {res}")
#
__all__ = ["os", "cv2", "np",  # 通用库
           "logger", "log_init", "HAS_QT", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL",  # log相关
           # "set_value", "get_value",  # tools相关
           "OrderedSetList",  "imread_cn", "imwrite_cn", # tools相关
           # "MachineCodeThread", "ActivationDialog", "CodeDecryted", # 授权相关
           ]
