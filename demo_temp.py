from pathlib import Path
from datetime import date, datetime
import time
from tools.lm_sql import DB_Sqlite, DetectionRecord, AlarmRecord

# --------------------------------------------------------------------------- #
# 5. 测试用例
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    db_tmp = "data/detect.db"

    print("=== 初始化 ===")
    db = DB_Sqlite(db_tmp)
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
    for r in recs:
        print("  ", r.id, r.create_time, r.role, r.result, r.passed, r.detail)

    print("\n=== 按列查询 ===")
    recs2 = db.query_by_column(DetectionRecord, "role", "Type01")
    print("role=Type01 条数:", len(recs2))
    recs3 = db.query_by_column(DetectionRecord, "result", "NG")
    print("result=NG 条数:", len(recs3))

    # print("\n=== 删除 ===")
    # first = db.query_all(DetectionRecord, limit=1)[0]
    # print("删除 id=%s 是否成功:" % first.id, db.delete_one(DetectionRecord, first.id))
    # print("删除后 detection 数量:", db.count(DetectionRecord))

    print("\n=== 断开 ===")
    db.disconnect()
    print("断开后连接状态:", db.is_connected())
