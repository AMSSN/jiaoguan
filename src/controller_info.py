# -*- coding: utf-8 -*-
"""首页(信息)界面控制: 统计信息 + 最新检测记录表。

数据来源: tools/lm_sql.py 的 DB_Sqlite。
刷新机制: DB 写入回调 -> Qt 信号(跨线程) -> 200ms 节流刷新,
          保证"数据库每新增一条记录, 首页刷新一次"。
"""
import json

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidgetItem, QWidget

from GlobalConfig import GlobalConfig
from tools import logger
from tools.lm_sql import AlarmRecord, DetectionRecord
from ui.page_info import Ui_Form_infoPage

# page_info 表头: ID / CreateTime / Role / Passed / InnerD / OuterD / Detail
_TABLE_LIMIT = 100          # 首页表格最多展示的最新记录条数
_REFRESH_INTERVAL = 200     # 刷新节流(ms)


class _InsertBridge(QObject):
    """DB 落盘线程 -> GUI 线程 的信号桥(QueuedConnection 保证线程安全)。"""
    recordInserted = pyqtSignal()


class InfoController(QWidget):
    def __init__(self, parent=None):
        super(InfoController, self).__init__(parent)
        self.ui = Ui_Form_infoPage()
        self.ui.setupUi(self)

        self.gc = GlobalConfig()
        self.db = self.gc.get_db()

        # DB 写入回调 -> Qt 信号
        self._bridge = _InsertBridge()
        self._bridge.recordInserted.connect(
            self._on_record_inserted, Qt.ConnectionType.QueuedConnection)
        self.db.set_insert_callback(self._db_on_insert)

        # 节流: 高频写入时合并为一次刷新
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_REFRESH_INTERVAL)
        self._timer.timeout.connect(self.refresh)

        self.refresh()

    # ---------------- 写入回调(在 DB 后台线程执行) ----------------
    def _db_on_insert(self, cls, records):
        self._bridge.recordInserted.emit()

    def _on_record_inserted(self):
        if not self._timer.isActive():
            self._timer.start()

    def showEvent(self, event):
        super(InfoController, self).showEvent(event)
        self.refresh()  # 切回首页时兜底刷新

    # ---------------- 刷新 ----------------
    def refresh(self):
        try:
            self._refresh_stats()
            self._refresh_table()
        except Exception as e:
            logger.error(f"首页刷新失败: {e}")

    def _refresh_stats(self):
        ui = self.ui
        total = self.db.count(DetectionRecord)
        ok = self.db.count(DetectionRecord, "passed", True)
        ng = max(total - ok, 0)
        yield_pct = (ok / total * 100.0) if total else 0.0
        warn = self.db.count(AlarmRecord)

        ui.labeltext_total.setText(str(total))
        ui.labeltext_numOK.setText(str(ok))
        ui.labeltext_numNG.setText(str(ng))
        ui.labeltext_yield.setText(f"{yield_pct:.2f}%")
        ui.labeltext_numWarn.setText(str(warn))
        ui.labeltext_time.setText(self._avg_cost_text())

    def _avg_cost_text(self) -> str:
        """平均检测时间: 取最近记录的 detail['cost_ms'] 求均值, 无数据则 '--'。"""
        records = self.db.query_all(DetectionRecord, limit=200, desc=True)
        costs = []
        for r in records:
            try:
                v = (r.detail or {}).get("cost_ms")
                if v is not None:
                    costs.append(float(v))
            except (TypeError, ValueError):
                continue
        if not costs:
            return "--"
        return f"{sum(costs) / len(costs):.1f} ms"

    def _refresh_table(self):
        table = self.ui.tableWidget
        records = self.db.query_all(
            DetectionRecord, order_by="create_time", desc=True, limit=_TABLE_LIMIT)
        table.setRowCount(0)
        for r in records:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                r.id,
                r.create_time.strftime("%Y-%m-%d %H:%M:%S") if r.create_time else "",
                r.role,
                "OK" if r.passed else "NG",
                f"{r.inner_d:.3f}",
                f"{r.outer_d:.3f}",
                json.dumps(r.detail, ensure_ascii=False),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 3:
                    item.setForeground(QColor(0, 150, 0) if r.passed else QColor(200, 0, 0))
                table.setItem(row, col, item)
