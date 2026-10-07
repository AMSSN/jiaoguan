# -*- coding: utf-8 -*-
"""报表界面控制: 按时间范围查询结果表/报警表并展示, 支持导出 CSV。"""
import csv
import json

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem, QWidget, QHeaderView

from GlobalConfig import GlobalConfig
from tools import logger
from tools.lm_sql import AlarmRecord, DetectionRecord
from ui.page_data import Ui_Form_dataPage

# 下拉项索引 -> 记录类型
_RESULT_INDEX = 0   # 结果表
_ALARM_INDEX = 1    # 报警表

_RESULT_HEADERS = ["ID", "CreateTime", "Role", "Passed", "InnerD", "OuterD", "Detail"]
_ALARM_HEADERS = ["ID", "CreateTime", "AlarmType", "AlarmInfo"]


class DataController(QWidget):
    def __init__(self, parent=None):
        super(DataController, self).__init__(parent)
        self.ui = Ui_Form_dataPage()
        self.ui.setupUi(self)

        self.gc = GlobalConfig()
        self.db = self.gc.get_db()

        self._init_time_range()
        self._apply_table_type()
        self.connects()
        self.on_select()

    # ---------------- 初始化 ----------------
    def _init_time_range(self):
        now = QDateTime.currentDateTime()
        self.ui.dateTimeEdit_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.ui.dateTimeEdit_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.ui.dateTimeEdit_start.setDateTime(now.date().startOfDay())  # 今日 0 点
        self.ui.dateTimeEdit_end.setDateTime(now)
        # 设置弹出选择日历
        self.ui.dateTimeEdit_start.setCalendarPopup(True)
        self.ui.dateTimeEdit_end.setCalendarPopup(True)

    def connects(self):
        self.ui.comboBox.currentIndexChanged.connect(self._apply_table_type)
        self.ui.pushButton_select.clicked.connect(self.on_select)
        self.ui.pushButton_export.clicked.connect(self.on_export)

    # ---------------- 表类型 ----------------
    def _is_alarm(self) -> bool:
        return self.ui.comboBox.currentIndex() == _ALARM_INDEX

    def _current_cls(self):
        return AlarmRecord if self._is_alarm() else DetectionRecord

    def _apply_table_type(self):
        """切换下拉框时重置表头。"""
        headers = _ALARM_HEADERS if self._is_alarm() else _RESULT_HEADERS
        table = self.ui.tableWidget
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(0)
        # 设置表格的行宽
        _header = self.ui.tableWidget.horizontalHeader()
        _header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        _header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        _header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        _header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        _header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        _header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        _header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

    # ---------------- 查询 ----------------
    def on_select(self):
        cls = self._current_cls()
        start = self.ui.dateTimeEdit_start.dateTime().toPyDateTime()
        end = self.ui.dateTimeEdit_end.dateTime().toPyDateTime()
        try:
            records = self.db.query_by_time(cls, start, end)
        except Exception as e:
            logger.error(f"报表查询失败: {e}")
            QMessageBox.warning(self, "查询失败", str(e))
            return
        self._fill_table(records)
        logger.info(f"报表查询 {cls.__name__} [{start} ~ {end}] 共 {len(records)} 条")

    def _fill_table(self, records):
        table = self.ui.tableWidget
        table.setRowCount(0)
        for r in records:
            row = table.rowCount()
            table.insertRow(row)
            values = self._row_values(r)
            for col, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if not self._is_alarm() and col == 3:
                    item.setForeground(QColor(0, 150, 0) if r.passed else QColor(200, 0, 0))
                table.setItem(row, col, item)

    @staticmethod
    def _row_values(r):
        ts = r.create_time.strftime("%Y-%m-%d %H:%M:%S") if r.create_time else ""
        if isinstance(r, AlarmRecord):
            return [r.id, ts, r.alarm_type, r.alarm_info]
        return [r.id, ts, r.role, "OK" if r.passed else "NG",
                f"{r.inner_d:.3f}", f"{r.outer_d:.3f}",
                json.dumps(r.detail, ensure_ascii=False)]

    # ---------------- 导出 ----------------
    def on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出CSV", "report.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        table = self.ui.tableWidget
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    table.horizontalHeaderItem(c).text()
                    for c in range(table.columnCount())])
                for row in range(table.rowCount()):
                    writer.writerow([
                        table.item(row, c).text() if table.item(row, c) else ""
                        for c in range(table.columnCount())])
        except OSError as e:
            logger.error(f"报表导出失败: {e}")
            QMessageBox.warning(self, "导出失败", str(e))
            return
        logger.info(f"报表已导出: {path}")
        QMessageBox.information(self, "导出成功", f"已导出到:\n{path}")
