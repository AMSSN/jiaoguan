# 通用检测上位机

基于 PyQt5 的通用环形零件检测上位机。分层架构 + 依赖注入 + 事件总线，
数据库 / 相机 / 算法 / 型号全部可替换，界面与逻辑解耦。

## 1. 运行

```bash
pip install -r requirements.txt
python src/main.py
```

首次运行会自动创建 `config/`、`data/`、`logs/`、`images/` 目录，
生成 `config/app.json`（默认配置）与示例型号 `Type01 / Type02 / Type03`。

默认使用 **Mock 相机**（合成环形图像）与 **SQLite**，无需任何硬件即可跑通全流程。

## 2. 目录说明

```
config/        全局配置 app.json 与型号参数（一个型号一个 JSON）
data/          SQLite 数据库文件
logs/          按天轮转的运行日志
images/        检测留档图片（按日期分目录）
ui/            Qt Designer 的 .ui 与 pyuic 生成的 .py（禁止手改生成的 .py）
src/
  main.py      程序入口
  core/        基础设施：配置中心、日志、异常、事件总线、服务容器、图像转换
  data/        数据访问：DAO 抽象 + SQLite/MySQL 实现、记录仓储、统计仓储、导出器
  device/      相机：CameraBase 抽象、Mock 相机、相机管理器、取流线程、品牌适配器
  algorithm/   算法插件：Inspector 接口、注册表、四个检测项插件、通用测量工具
  model/       型号：ModelSpec 与 ModelManager（JSON 增删改查、热重载）
  service/     业务编排：检测服务、统计服务、系统服务
  ui_impl/     界面：主窗口、四个页面、通用控件（ImageView / 统计卡片 / Toast）
```

## 3. 分层与依赖关系

```
ui_impl  →  service  →  device / algorithm / data / model  →  core
              ↑                        ↓
          依赖注入（AppContext）   事件总线（SignalBus）
```

* 上层只依赖服务接口与 SignalBus，模块之间不互相硬引用；
* `AppContext` 统一装配与释放，`shutdown()` 保证相机、线程、数据库被正确关闭；
* 子线程（取流 / 算法）只允许通过 `pyqtSignal` 回传数据，禁止直接操作控件。

## 4. 常见扩展

### 4.1 换相机品牌

1. 在 `src/device/adapters/` 下新建 `hikvision.py`，继承 `CameraBase` 实现接口；
2. 在装配阶段注册：`camera_manager.register_driver("hikvision", HikCamera)`；
3. 把 `config/app.json` 中对应相机的 `driver` 改为 `"hikvision"`。

上层（服务层、界面）零改动。

### 4.2 换数据库

把 `config/app.json` 中 `database.type` 改为 `"mysql"` 并填写连接参数，安装 `PyMySQL` 即可。
`MysqlRepository` 与 `SqliteRepository` 实现同一套 `BaseRepository` 接口。

### 4.3 新增检测项

1. 在 `src/algorithm/plugins/` 下新建模块，继承 `Inspector`，设置唯一 `key`；
2. 在型号 JSON 的 `items` 中增加同名配置节点（阈值、是否启用、标定系数）；
3. 注册表自动发现，系统页的参数编辑区会自动生成对应控件。

### 4.4 修改界面

业务代码写在 `src/ui_impl/`（页面类多重继承挂载 pyuic 生成的类）：

```python
class DetectPage(QWidget, Ui_Form_detect):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setupUi(self)
```

修改控件需在 Qt Designer 中改 `.ui` 后重新生成（**不要手改 `ui/*.py`**）：

```bash
python -m PyQt5.uic.pyuic ui/page_system.ui -o ui/page_system.py
```

## 5. 数据说明

* 检测记录表 `detection_record`：时间、型号、序列号、判定、内径、外径、分层、内菱、耗时、存图路径、明细 JSON；
* 报警表 `alarm_log`：NG、相机异常等；
* 写库走批量缓冲（满批或定时落盘），SQLite 开启 WAL；
* 统计全部下推 SQL 聚合，不做全表遍历；导出支持 CSV / Excel。

## 6. 快捷键与操作提示

* 检测页：选择型号 → 「启动检测」连续检测；「单次检测」跑一帧；「预览」只看画面不跑算法（与检测互斥）；
* 系统页：相机配置页可保存 / 测试连接 / 开关相机；型号管理页可新建 / 复制 / 重命名 / 删除型号并编辑各检测项阈值；
* 数据页：按时间、型号、判定、关键字查询，支持翻页与导出。







# TODO

1、my_camera.py设置曝光时间逻辑：初始化时根据配置文件的内容设置，“系统”界面上设置曝光和增益时，对相机生效的同时写入配置文件。这里要根据API文档确定曝光时间的单位是毫秒ms还是微妙um

2、my_camera.py，设置去抖动时间、间隔、延迟。

3、整个逻辑要从双相机改为单相机！！！！

















