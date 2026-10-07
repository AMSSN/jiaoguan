# -*- coding: utf-8 -*-
"""全局配置(单例) —— JSON 版

职责:
1. 记录 app 相关信息(读取 config/app.json), 供 info/系统界面展示;
2. 作为各界面之间的数据传递通道(如 current_model / 任意 data);
3. 产品型号配置的读取与写入(config/models/*.json);
4. 提供全局唯一的数据库句柄 DB_Sqlite。
"""
import json
from datetime import datetime
from pathlib import Path

from tools import *
from tools.lm_sql import DB_Sqlite, DetectionRecord, AlarmRecord

# 项目根目录: src/GlobalConfig.py -> parents[1]
ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT_DIR / "config"
APP_CONFIG_PATH = CONFIG_DIR / "app.json"
MODEL_DIR = CONFIG_DIR / "models"
DB_PATH = ROOT_DIR / "data" / "detect.db"


# --------------------------------------------------------------------------- #
# 产品型号配置
# --------------------------------------------------------------------------- #
class ModelConfig:
    """单个产品型号配置(包装 config/models/*.json 的 dict)。"""

    def __init__(self, data: dict = None, file_path=None):
        self.data = dict(data or {})
        self.file_path = Path(file_path) if file_path else None

    # ---------------- 基础字段 ----------------
    @property
    def name(self) -> str:
        return str(self.data.get("name", ""))

    @property
    def desc(self) -> str:
        return str(self.data.get("desc", ""))

    @property
    def items(self) -> dict:
        return self.data.get("items", {}) or {}

    @property
    def camera(self) -> dict:
        return self.data.get("camera", {}) or {}

    @property
    def save_image(self):
        return self.data.get("save_image")

    def item(self, key: str) -> dict:
        return self.items.get(key, {}) or {}

    # ---------------- 检测项便捷访问 ----------------
    @staticmethod
    def _range(key: str, items: dict, bound: str) -> float:
        try:
            return float((items.get(key) or {}).get(bound, 0.0))
        except (TypeError, ValueError):
            return 0.0

    @property
    def inner_lower(self) -> float:
        return self._range("inner_radius", self.items, "lower")

    @property
    def inner_upper(self) -> float:
        return self._range("inner_radius", self.items, "upper")

    @property
    def outer_lower(self) -> float:
        return self._range("outer_radius", self.items, "lower")

    @property
    def outer_upper(self) -> float:
        return self._range("outer_radius", self.items, "upper")

    @property
    def inner_enabled(self) -> bool:
        return bool(self.item("inner_radius").get("enabled", False))

    @property
    def outer_enabled(self) -> bool:
        return bool(self.item("outer_radius").get("enabled", False))

    @property
    def fencen_enabled(self) -> bool:
        return bool(self.item("fencen").get("enabled", False))

    @property
    def neiling_enabled(self) -> bool:
        return bool(self.item("neiling").get("enabled", False))

    @property
    def camera_exposure(self) -> float:
        try:
            return float(self.camera.get("exposure", 5000.0))
        except (TypeError, ValueError):
            return 5000.0

    @property
    def camera_gain(self) -> float:
        try:
            return float(self.camera.get("gain", 1.0))
        except (TypeError, ValueError):
            return 1.0

    def to_dict(self) -> dict:
        return self.data

    def __str__(self):
        return (f"{self.__class__.__name__}(name={self.name}, "
                f"inner=[{self.inner_lower},{self.inner_upper}], "
                f"outer=[{self.outer_lower},{self.outer_upper}], "
                f"fencen={self.fencen_enabled}, neiling={self.neiling_enabled})")


def read_ModelConfig_file(file_path) -> "ModelConfig | None":
    """读取单个型号配置文件, 不存在或解析失败返回 None。"""
    p = Path(file_path)
    if not p.exists():
        logger.warning(f"型号配置文件不存在: {p}")
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"读取型号配置失败: {p} ({e})")
        return None
    return ModelConfig(data, p)


def write_ModelConfig_file(mc: "ModelConfig", file_path=None) -> Path:
    """写入型号配置文件(自动刷新 updated_at)。"""
    path = Path(file_path or mc.file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mc.data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mc.data, f, ensure_ascii=False, indent=4)
    mc.file_path = path
    logger.info(f"型号配置已保存: {path}")
    return path


def load_model_configs(model_dir=MODEL_DIR) -> dict:
    """扫描型号配置目录, 返回 {型号名: ModelConfig}。"""
    result = {}
    for p in sorted(Path(model_dir).glob("*.json")):
        mc = read_ModelConfig_file(p)
        if mc is not None:
            result[mc.name or p.stem] = mc
    return result


# --------------------------------------------------------------------------- #
# 全局配置(单例)
# --------------------------------------------------------------------------- #
class GlobalConfig:
    """全局配置与环境句柄 => 唯一实例。"""

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(GlobalConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # 路径
        self.root_dir = ROOT_DIR
        self.config_dir = CONFIG_DIR
        self.app_config_path = APP_CONFIG_PATH
        self.model_dir = MODEL_DIR
        self.db_path = DB_PATH
        # app 相关信息
        self.app = {}
        self.cameras = []
        self.detection = {}
        self.log = {}
        # 型号配置
        self.modelConfigs = {}          # {型号名: ModelConfig}
        self.current_model = ""
        self.current_model_config = None
        # 跨界面数据传递
        self.data = {}
        # 共享数据库(懒加载)
        self._db = None

    # ---------------- 通用 get/set ----------------
    def set(self, key: str, value):
        self.data[key] = value

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.data

    # ---------------- app 配置 ----------------
    def load_app(self, path=None) -> bool:
        p = Path(path or self.app_config_path)
        if not p.exists():
            logger.error(f"app 配置文件不存在: {p}")
            return False
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"读取 app 配置失败: {p} ({e})")
            return False
        self.app = cfg.get("app", {}) or {}
        self.cameras = cfg.get("cameras", []) or []
        self.detection = cfg.get("detection", {}) or {}
        self.log = cfg.get("log", {}) or {}
        self.app_config_path = p
        logger.info(f"app 配置已加载: {p} (name={self.app_name})")
        return True

    def save_app(self) -> None:
        cfg = {
            "app": self.app,
            "cameras": self.cameras,
            "detection": self.detection,
            "log": self.log,
        }
        self.app_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.app_config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        logger.info(f"app 配置已保存: {self.app_config_path}")

    @property
    def app_name(self) -> str:
        return str(self.app.get("name", "检测系统"))

    @property
    def save_image(self) -> bool:
        return bool(self.app.get("save_image", False))

    @property
    def image_dir(self) -> Path:
        d = self.app.get("image_dir", "images")
        return self.root_dir / d if not Path(d).is_absolute() else Path(d)

    def first_camera(self) -> dict:
        """返回第一台相机配置(本项目只用一台)。"""
        return self.cameras[0] if self.cameras else {}

    # ---------------- 型号配置 ----------------
    def load_models(self) -> dict:
        self.modelConfigs = load_model_configs(self.model_dir)
        logger.info(f"型号配置已加载 {len(self.modelConfigs)} 个: {list(self.modelConfigs)}")
        return self.modelConfigs

    def find_model(self, name) -> "ModelConfig | None":
        if name is None:
            return None
        name = str(name)
        if name in self.modelConfigs:
            return self.modelConfigs[name]
        for mc in self.modelConfigs.values():
            if mc.name == name or (mc.file_path and mc.file_path.stem == name):
                return mc
        return None

    def set_current_model(self, name) -> "ModelConfig | None":
        mc = self.find_model(name)
        if mc is None:
            logger.warning(f"未找到型号配置: {name}")
            return None
        self.current_model = mc.name
        self.current_model_config = mc
        logger.info(f"当前型号切换为: {self.current_model}")
        return mc

    # ---------------- 共享数据库 ----------------
    def get_db(self) -> DB_Sqlite:
        if self._db is None:
            self._db = DB_Sqlite(str(self.db_path))
            logger.info(f"数据库已初始化: {self.db_path}")
        return self._db

    def __str__(self):
        return (f"{self.__class__.__name__}(app={self.app_name}, "
                f"models={list(self.modelConfigs)}, current={self.current_model})")


if __name__ == '__main__':
    gc = GlobalConfig()
    gc.load_app()
    gc.load_models()
    gc.set_current_model("Type01")
    print(gc)
    print(gc.current_model_config)
