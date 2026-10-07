# -*- coding: utf-8 -*-
import json
import sqlite3
import threading
import time
import collections
from dataclasses import MISSING, dataclass, field, fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union, get_args, get_origin, get_type_hints


class SqliteDBError(Exception):
    """模块统一异常出口。"""


# --------------------------------------------------------------------------- #
# 1. 用户自定义的"一条数据的封装类"(同时就是表头结构)
# --------------------------------------------------------------------------- #
@dataclass
class DetectionRecord:
    # 示例封装类: 一条检测记录(同时就是表头结构)
    __table__ = "detection_record"
    id: int = field(default=0, metadata={"pk": True, "auto": True})
    create_time: datetime = field(default_factory=datetime.now, metadata={"index": True})
    role: str = field(default="", metadata={"len": 64, "index": True})
    result: str = field(default="None")
    inner_d: float = field(default=0.0)
    outer_d: float = field(default=0.0)
    passed: bool = field(default=True)
    detail: dict = field(default_factory=dict)


@dataclass
class AlarmRecord:
    # 示例封装类: 一条报警记录(同时就是表头结构)
    __table__ = "alarm_record"

    id: int = field(default=0, metadata={"pk": True, "auto": True})
    create_time: datetime = field(default_factory=datetime.now, metadata={"index": True})
    alarm_type: str = field(default="None")
    alarm_info: str = field(default="", metadata={"len": 64, "index": True})


# --------------------------------------------------------------------------- #
# 2. 先进先出队列 (按原文件类名 SingleTon 保留)
# --------------------------------------------------------------------------- #
class SingleTon():
    '''
    先进先出的一个队列，提供enQueue、deQueue、isEmpty、isFull、getSize等功能
    '''
    m_maxSize = 100

    def __init__(self, max_size: int = 100) -> None:
        self.m_maxSize = max_size
        self._queue: "collections.deque" = collections.deque()
        self._lock = threading.Lock()

    def enQueue(self, item: Any) -> bool:
        """入队; 队列已满返回 False。"""
        with self._lock:
            if len(self._queue) >= self.m_maxSize:
                return False
            self._queue.append(item)
            return True

    def deQueue(self) -> Any:
        """出队; 队列为空返回 None。"""
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def isEmpty(self) -> bool:
        with self._lock:
            return len(self._queue) == 0

    def isFull(self) -> bool:
        with self._lock:
            return len(self._queue) >= self.m_maxSize

    def getSize(self) -> int:
        with self._lock:
            return len(self._queue)

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()


# --------------------------------------------------------------------------- #
# 3. 列定义 / 类型映射 / 值转换 (表头结构由 dataclass 单一来源推导)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _Column:
    attr: str
    column: str
    sql_type: str
    py_type: Any
    pk: bool = False
    auto: bool = False
    not_null: bool = False
    unique: bool = False
    index: bool = False
    default_sql: str = ""


_TYPE_MAP: Dict[Any, str] = {
    int: "INTEGER", float: "REAL", str: "TEXT", bool: "INTEGER", bytes: "BLOB",
    datetime: "TEXT", date: "TEXT", Decimal: "NUMERIC",
    dict: "TEXT", list: "TEXT", tuple: "TEXT",
}


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _unwrap_optional(tp: Any) -> Any:
    if tp is Any:
        return str
    origin = get_origin(tp)
    if origin is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        return _unwrap_optional(args[0]) if args else str
    if origin in (dict, Dict):
        return dict
    if origin in (list, List, set, frozenset, tuple, Tuple):
        return list
    if isinstance(tp, str):  # 注解未被解析时的残留
        return str
    return tp


def _default_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return "'" + value.isoformat(sep=" ", timespec="seconds") + "'"
    if isinstance(value, date):
        return "'" + value.isoformat() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _resolve_columns(cls: type) -> List[_Column]:
    try:
        hints = get_type_hints(cls)
    except Exception:
        hints = {}

    cols: List[_Column] = []
    for f in fields(cls):
        meta: dict = dict(f.metadata or {})
        py_type = _unwrap_optional(hints.get(f.name, f.type))
        if not isinstance(py_type, type):
            py_type = str

        is_pk = bool(meta.get("pk"))
        if not is_pk and f.name == "id" and py_type is int:
            is_pk = True
        is_auto = bool(meta.get("auto", py_type is int and is_pk))

        default_sql = ""
        if not is_pk:
            if meta.get("default") is not None:
                default_sql = str(meta["default"])
            elif f.default is not MISSING and f.default is not None:
                default_sql = _default_literal(f.default)

        sql_type = str(meta["type"]) if meta.get("type") else (
            "VARCHAR(%d)" % int(meta["len"]) if (py_type is str and meta.get("len")) else
            _TYPE_MAP.get(py_type, "TEXT"))

        cols.append(_Column(
            attr=f.name, column=str(meta.get("column", f.name)), sql_type=sql_type,
            py_type=py_type, pk=is_pk, auto=is_auto,
            not_null=bool(meta.get("not_null", is_pk)),
            unique=bool(meta.get("unique", False)),
            index=bool(meta.get("index", False)),
            default_sql=default_sql,
        ))

    if not cols:
        raise SqliteDBError("封装类 %s 没有任何字段, 无法建表" % cls.__name__)
    auto_idx = [i for i, c in enumerate(cols) if c.auto]
    for i in auto_idx[1:]:
        cols[i] = replace(cols[i], auto=False)
    return cols


def _py_to_db(value: Any, col: _Column) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="milliseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bytes):
        return sqlite3.Binary(value)
    return value


def _db_to_py(value: Any, col: _Column) -> Any:
    if value is None:
        return None
    tp = col.py_type
    try:
        if tp is datetime and isinstance(value, str):
            return datetime.fromisoformat(value)
        if tp is date and isinstance(value, str):
            return date.fromisoformat(value)
        if tp is bool:
            return bool(value)
        if tp is Decimal:
            return Decimal(str(value))
        if tp in (dict, list) and isinstance(value, (bytes, memoryview)):
            value = bytes(value).decode("utf-8")
        if tp in (dict, list) and isinstance(value, str):
            return json.loads(value)
        if tp is int and value is not None:
            return int(value)
        if tp is float and value is not None:
            return float(value)
    except Exception:
        return value
    return value


# --------------------------------------------------------------------------- #
# 4. DB_Sqlite: 单库双表访问类 + 队列缓冲 + 后台写入线程
# --------------------------------------------------------------------------- #
class DB_Sqlite:
    """单表 SQLite 访问类。
    管理 detection_record / alarm_record 两张表,
    提供单条/多条插入、按时间/列查询, 以及"队列 + 后台线程"的批量落盘。
    """

    def __init__(
            self,
            db_path: Union[str, Path],
            auto_connect: bool = True,
            auto_create_table: bool = True,
            timeout: float = 5.0,
            on_insert=None,
    ) -> None:

        self.db_path = str(db_path)
        self.timeout = timeout
        # 可选写入回调: 每成功落盘后调用 cb(记录类型, 新增记录列表), 在落盘线程中执行
        self._on_insert = on_insert

        self._tables: Dict[type, Dict[str, Any]] = {}
        for cls in (DetectionRecord, AlarmRecord):
            cols = _resolve_columns(cls)
            self._tables[cls] = {
                "name": getattr(cls, "__table__", cls.__name__),
                "columns": cols,
                "pk": next((c for c in cols if c.pk), None),
                "insert_cols": [c for c in cols if not (c.pk and c.auto)],
            }

        self._local = threading.local()
        self._conns: List[sqlite3.Connection] = []
        self._lock = threading.RLock()

        self._running = False
        self._worker: Optional[threading.Thread] = None

        if auto_connect:
            self.connect()
        if auto_connect and auto_create_table:
            self.create_table()

        self.detectTon = SingleTon()
        self.alarmTon = SingleTon()

    # -------------------------------------------------------------- 连接管理
    def connect(self) -> None:
        if getattr(self._local, "conn", None) is not None:
            return
        try:
            p = Path(self.db_path)
            if p.parent and str(p.parent) not in (".", ""):
                p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=self.timeout)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=%d" % int(self.timeout * 1000))
            except sqlite3.DatabaseError:
                pass
        except sqlite3.Error as e:
            raise SqliteDBError("连接数据库失败: %s (%s)" % (self.db_path, e)) from e
        self._local.conn = conn
        with self._lock:
            self._conns.append(conn)

    @property
    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        return conn if conn is not None else self.connect() or getattr(self._local, "conn")

    def is_connected(self) -> bool:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return False
        try:
            conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def disconnect(self) -> None:
        self.stop()
        with self._lock:
            for c in self._conns:
                try:
                    c.commit()
                    c.close()
                except sqlite3.Error:
                    pass
            self._conns.clear()
        self._local.conn = None

    # -------------------------------------------------------------- 建表
    def create_table(self) -> None:
        """如果表不存在就根据 AlarmRecord 和 DetectionRecord 的结构创建 2 个表。"""
        for cls, info in self._tables.items():
            defs = []
            for c in info["columns"]:
                piece = "%s %s" % (_quote_ident(c.column), c.sql_type)
                if c.pk:
                    piece += " PRIMARY KEY"
                    if c.auto:
                        piece += " AUTOINCREMENT"
                if c.not_null and not c.pk:
                    piece += " NOT NULL"
                if c.unique:
                    piece += " UNIQUE"
                if c.default_sql:
                    piece += " DEFAULT %s" % c.default_sql
                defs.append(piece)
            sql = "CREATE TABLE IF NOT EXISTS %s (\n  %s\n)" % (
                _quote_ident(info["name"]), ",\n  ".join(defs))
            try:
                with self._lock:
                    conn = self.connection
                    conn.execute(sql)
                    for c in info["columns"]:
                        if c.index and not c.pk:
                            conn.execute(
                                "CREATE INDEX IF NOT EXISTS %s ON %s(%s)" % (
                                    _quote_ident("idx_%s_%s" % (info["name"], c.column)),
                                    _quote_ident(info["name"]), _quote_ident(c.column)))
                    conn.commit()
            except sqlite3.Error as e:
                raise SqliteDBError("创建表 %s 失败: %s" % (info["name"], e)) from e

    def table_exists(self, cls: type) -> bool:
        info = self._tables[cls]
        try:
            row = self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (info["name"],)).fetchone()
            return row is not None
        except sqlite3.Error as e:
            raise SqliteDBError("查询表失败: %s" % e) from e

    # -------------------------------------------------------------- 内部工具
    def _check_cls(self, cls: type) -> Dict[str, Any]:
        if cls not in self._tables:
            raise SqliteDBError("未知的记录类型: %s" % cls.__name__)
        return self._tables[cls]

    def _check_column(self, info: Dict[str, Any], column: str) -> _Column:
        for c in info["columns"]:
            if c.column == column or c.attr == column:
                return c
        raise SqliteDBError("列 %s 不存在, 可用列: %s" % (
            column, ", ".join(c.column for c in info["columns"])))

    def _entity_to_params(self, info: Dict[str, Any], obj: Any) -> Tuple[Any, ...]:
        return tuple(_py_to_db(getattr(obj, c.attr, None), c) for c in info["insert_cols"])

    # -------------------------------------------------------------- 写入回调
    def set_insert_callback(self, cb) -> None:
        """设置写入回调: cb(记录类型, 新增记录列表), 在落盘线程执行。传 None 取消。"""
        self._on_insert = cb

    def _notify_insert(self, cls: type, records: Sequence[Any]) -> None:
        cb = self._on_insert
        if cb is None or not records:
            return
        try:
            cb(cls, list(records))
        except Exception:
            # 回调异常绝不能影响落盘主流程
            pass

    def _row_to_entity(self, cls: type, row: sqlite3.Row) -> Any:
        info = self._tables[cls]
        data = {}
        for c in info["columns"]:
            if c.column in row.keys():
                data[c.attr] = _db_to_py(row[c.column], c)
        return cls(**data)

    def _select(self, cls: type, where: str, params: Sequence[Any], order_by: Optional[str],
                desc: bool, limit: Optional[int], offset: int) -> List[Any]:
        info = self._check_cls(cls)
        sql = "SELECT * FROM %s" % _quote_ident(info["name"])
        if where:
            sql += " WHERE " + where
        if order_by:
            col = self._check_column(info, order_by)
            sql += " ORDER BY %s %s" % (_quote_ident(col.column), "DESC" if desc else "ASC")
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = list(params) + [int(limit), int(offset)]
        try:
            cur = self.connection.execute(sql, tuple(params))
            return [self._row_to_entity(cls, r) for r in cur.fetchall()]
        except sqlite3.Error as e:
            raise SqliteDBError("查询失败: %s | SQL=%s" % (e, sql)) from e

    # -------------------------------------------------------------- 增: 直接写
    def add_record(self, record: Any) -> int:
        """增加一条数据(按对象类型自动路由到对应表), 返回自增 id。"""
        cls = type(record)
        info = self._check_cls(cls)
        cols = ",".join(_quote_ident(c.column) for c in info["insert_cols"])
        marks = ",".join("?" * len(info["insert_cols"]))
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (
            _quote_ident(info["name"]), cols, marks)
        params = self._entity_to_params(info, record)
        try:
            with self._lock:
                cur = self.connection.execute(sql, params)
                self.connection.commit()
                new_id = cur.lastrowid or 0
        except sqlite3.Error as e:
            raise SqliteDBError("插入数据失败: %s" % e) from e
        pk = info["pk"]
        if pk and pk.auto and getattr(record, pk.attr, None) in (0, None):
            try:
                setattr(record, pk.attr, new_id)
            except Exception:
                pass
        self._notify_insert(cls, [record])
        return new_id

    def add_records(self, records: Sequence[Any]) -> int:
        """批量增加多条数据(单次 executemany + 一次提交), 返回条数。"""
        records = list(records)
        if not records:
            return 0
        cls = type(records[0])
        info = self._check_cls(cls)
        cols = ",".join(_quote_ident(c.column) for c in info["insert_cols"])
        marks = ",".join("?" * len(info["insert_cols"]))
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (
            _quote_ident(info["name"]), cols, marks)
        params = [self._entity_to_params(info, r) for r in records]
        try:
            with self._lock:
                self.connection.executemany(sql, params)
                self.connection.commit()
        except sqlite3.Error as e:
            raise SqliteDBError("批量插入失败: %s" % e) from e
        self._notify_insert(cls, records)
        return len(records)

    # 便捷别名(对应两张表的语义化方法)
    def add_detection_one(self, record: DetectionRecord) -> int:
        return self.add_record(record)

    def add_detection_many(self, records: Sequence[DetectionRecord]) -> int:
        return self.add_records(records)

    def add_alarm_one(self, record: AlarmRecord) -> int:
        return self.add_record(record)

    def add_alarm_many(self, records: Sequence[AlarmRecord]) -> int:
        return self.add_records(records)

    # -------------------------------------------------------------- 增: 入队
    def enqueue_detection(self, record: DetectionRecord) -> bool:
        return self.detectTon.enQueue(record)

    def enqueue_alarm(self, record: AlarmRecord) -> bool:
        return self.alarmTon.enQueue(record)

    # -------------------------------------------------------------- 查
    def query_by_time(self, cls: type,
                      start: Union[datetime, date, str, int, float, None],
                      end: Union[datetime, date, str, int, float, None] = None,
                      column: str = "create_time",
                      order_by: Optional[str] = None,
                      desc: bool = True,
                      limit: Optional[int] = None,
                      offset: int = 0) -> List[Any]:
        """根据时间范围查询(闭区间)。start/end 为 None 表示不限该边界。"""
        info = self._check_cls(cls)
        col = self._check_column(info, column)
        where, params = [], []
        if start is not None:
            where.append("%s >= ?" % _quote_ident(col.column))
            params.append(_py_to_db(start, col))
        if end is not None:
            where.append("%s <= ?" % _quote_ident(col.column))
            params.append(_py_to_db(end, col))
        return self._select(cls, " AND ".join(where), params,
                            order_by or column, desc, limit, offset)

    def query_by_column(self, cls: type,
                        column: str, value: Any = None,
                        fuzzy: bool = False,
                        start: Any = None, end: Any = None,
                        order_by: Optional[str] = None,
                        desc: bool = True,
                        limit: Optional[int] = None,
                        offset: int = 0) -> List[Any]:
        """根据某一列表头查询; fuzzy=True 时用 LIKE %%value%%。"""
        info = self._check_cls(cls)
        col = self._check_column(info, column)
        where, params = [], []
        if value is not None:
            if fuzzy:
                where.append("%s LIKE ?" % _quote_ident(col.column))
                params.append("%%%s%%" % str(_py_to_db(value, col)))
            else:
                where.append("%s = ?" % _quote_ident(col.column))
                params.append(_py_to_db(value, col))
        if start is not None:
            where.append("%s >= ?" % _quote_ident(col.column))
            params.append(_py_to_db(start, col))
        if end is not None:
            where.append("%s <= ?" % _quote_ident(col.column))
            params.append(_py_to_db(end, col))
        return self._select(cls, " AND ".join(where), params,
                            order_by, desc, limit, offset)

    def query_all(self, cls: type, order_by: Optional[str] = None,
                  desc: bool = True, limit: Optional[int] = None,
                  offset: int = 0) -> List[Any]:
        return self._select(cls, "", [], order_by, desc, limit, offset)

    def count(self, cls: type, column: Optional[str] = None, value: Any = None) -> int:
        info = self._check_cls(cls)
        sql = "SELECT COUNT(*) FROM %s" % _quote_ident(info["name"])
        params: Tuple[Any, ...] = ()
        if column is not None:
            col = self._check_column(info, column)
            sql += " WHERE %s = ?" % _quote_ident(col.column)
            params = (_py_to_db(value, col),)
        try:
            row = self.connection.execute(sql, params).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error as e:
            raise SqliteDBError("统计失败: %s" % e) from e

    # -------------------------------------------------------------- 删
    def delete_one(self, cls: type, pk_value: Any) -> bool:
        info = self._check_cls(cls)
        pk = info["pk"]
        if pk is None:
            raise SqliteDBError("表 %s 没有主键" % info["name"])
        sql = "DELETE FROM %s WHERE %s = ?" % (
            _quote_ident(info["name"]), _quote_ident(pk.column))
        try:
            with self._lock:
                cur = self.connection.execute(sql, (_py_to_db(pk_value, pk),))
                self.connection.commit()
                return cur.rowcount > 0
        except sqlite3.Error as e:
            raise SqliteDBError("删除失败: %s" % e) from e

    def delete_many(self, cls: type, pk_values: Sequence[Any]) -> int:
        info = self._check_cls(cls)
        pk = info["pk"]
        if pk is None:
            raise SqliteDBError("表 %s 没有主键" % info["name"])
        values = list(pk_values)
        if not values:
            return 0
        sql = "DELETE FROM %s WHERE %s = ?" % (
            _quote_ident(info["name"]), _quote_ident(pk.column))
        total = 0
        try:
            with self._lock:
                conn = self.connection
                for v in values:
                    total += conn.execute(sql, (_py_to_db(v, pk),)).rowcount
                conn.commit()
        except sqlite3.Error as e:
            raise SqliteDBError("批量删除失败: %s" % e) from e
        return total

    # -------------------------------------------------------------- 改(占位)
    def update_one(self, *args, **kwargs) -> None:
        """TODO: 修改一条数据(占位, 暂未实现)。建议: update_one(cls, pk_value, **fields)"""
        pass

    # -------------------------------------------------------------- 后台写线程
    def start(self) -> None:
        '''监控数据队列，如果队列有数据，就出队并在两张表中添加记录'''
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._monitor, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._running = False

    def _monitor(self) -> None:
        """后台线程: 从两张表的队列中批量取出并落盘。"""
        while self._running:
            # 检测记录
            det_batch = []
            while len(det_batch) < 50:
                item = self.detectTon.deQueue()
                if item is None:
                    break
                det_batch.append(item)
            if det_batch:
                self.add_records(det_batch)

            # 报警记录
            alm_batch = []
            while len(alm_batch) < 50:
                item = self.alarmTon.deQueue()
                if item is None:
                    break
                alm_batch.append(item)
            if alm_batch:
                self.add_records(alm_batch)

            if not det_batch and not alm_batch:
                time.sleep(0.02)

    def __repr__(self) -> str:
        return "DB_Sqlite(demo=%r, connected=%s)" % (self.db_path, self.is_connected())


# --------------------------------------------------------------------------- #
# 5. 测试用例
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    tmp = "app.demo"
    # 清理上次遗留, 保证计数可预期
    f = Path(tmp)
    if f.exists():
        try:
            f.unlink()
        except OSError:
            pass

    print("=== 初始化 ===")
    db = DB_Sqlite(tmp)
    print("连接状态:", db.is_connected())
    print("detection 表存在:", db.table_exists(DetectionRecord))
    print("alarm 表存在:", db.table_exists(AlarmRecord))

    now = datetime.now()

    print("\n=== 单条添加 ===")
    db.add_detection_one(DetectionRecord(
        create_time=now, role="Type01", result="OK",
        inner_d=12.34, outer_d=20.10, passed=True, detail={"note": "正常"}))
    db.add_alarm_one(AlarmRecord(
        create_time=now, alarm_type="温度", alarm_info="过温"))
    print("detection 数量:", db.count(DetectionRecord))
    print("alarm 数量:", db.count(AlarmRecord))

    print("\n=== 多条添加 ===")
    db.add_detection_many([
        DetectionRecord(create_time=now, role="Type02", result="NG",
                        inner_d=11.0, outer_d=19.0, passed=False),
        DetectionRecord(create_time=now, role="Type01", result="OK",
                        inner_d=12.0, outer_d=20.0, passed=True),
    ])
    print("detection 数量:", db.count(DetectionRecord))

    print("\n=== 队列 + 后台线程写入 ===")
    db.enqueue_detection(DetectionRecord(
        create_time=now, role="Type03", result="OK", inner_d=13.0, outer_d=21.0))
    db.enqueue_alarm(AlarmRecord(
        create_time=now, alarm_type="压力", alarm_info="超压"))
    db.start()
    time.sleep(0.3)
    db.stop()
    print("detection 队列剩余:", db.detectTon.getSize())
    print("alarm 队列剩余:", db.alarmTon.getSize())
    print("detection 数量(含队列写入):", db.count(DetectionRecord))
    print("alarm 数量(含队列写入):", db.count(AlarmRecord))

    print("\n=== 按时间查询 ===")
    recs = db.query_by_time(DetectionRecord, now.replace(hour=0), now)
    print("今天 creation 全部条数:", len(recs))
    for r in recs[:3]:
        print("  ", r.id, r.create_time, r.role, r.result, r.passed, r.detail)

    print("\n=== 按列查询 ===")
    recs2 = db.query_by_column(DetectionRecord, "role", "Type01")
    print("role=Type01 条数:", len(recs2))
    recs3 = db.query_by_column(DetectionRecord, "result", "NG")
    print("result=NG 条数:", len(recs3))

    print("\n=== 删除 ===")
    first = db.query_all(DetectionRecord, limit=1)[0]
    print("删除 id=%s 是否成功:" % first.id, db.delete_one(DetectionRecord, first.id))
    print("删除后 detection 数量:", db.count(DetectionRecord))

    print("\n=== 断开 ===")
    db.disconnect()
    print("断开后连接状态:", db.is_connected())
