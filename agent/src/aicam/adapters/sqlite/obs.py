"""ObservabilityPort 的 SQLite 實作（POC）。正式版換成 Loki / Prometheus / Tempo。"""


class SqliteObs:
    """logs / metrics / spans 的 SQLite 儲存與查詢。"""
    def __init__(self, db): self.db = db

    def ingest(self, logs, metrics, spans):
        # 三張表在同一個交易內寫入：任何一筆失敗都整批 rollback，不會留下半批資料
        self.db.many_multi([
            ("INSERT INTO logs(ts,lane,level,msg) VALUES(?,?,?,?)",
             [(x["ts"], x["lane"], x["level"], x["msg"]) for x in logs]),
            ("INSERT INTO metrics VALUES(?,?,?,?)",
             [(x["ts"], x["lane"], x["name"], x["value"]) for x in metrics]),
            ("INSERT INTO spans VALUES(?,?,?,?,?,?,?,?)",
             [(x["trace_id"], x["span_id"], x["parent_id"], x["name"], x["lane"], x["ts"],
               x["dur_ms"], x["status"]) for x in spans])])

    def _where(self, lane, contains, since):
        w, a = ["ts>=?"], [since]
        if lane is not None: w.append("lane=?"); a.append(lane)
        if contains: w.append("msg LIKE ?"); a.append(f"%{contains}%")
        return " AND ".join(w), a

    def logs(self, lane=None, contains=None, since=0, limit=20):
        w, a = self._where(lane, contains, since)
        return self.db.q(f"SELECT ts,lane,level,msg FROM logs WHERE {w} ORDER BY ts DESC LIMIT ?", (*a, limit))

    def count_logs(self, lane=None, contains=None, since=0):
        w, a = self._where(lane, contains, since)
        return self.db.q(f"SELECT COUNT(*) n FROM logs WHERE {w}", a)[0]["n"]

    def metrics(self, lane, name, since=0, limit=None):
        sql = "SELECT ts,value FROM metrics WHERE lane=? AND name=? AND ts>? AND value IS NOT NULL ORDER BY ts DESC"
        return self.db.q(sql + (f" LIMIT {int(limit)}" if limit else ""), (lane, name, since))

    def spans(self, lane=None, since=0, status=None, limit=10):
        w, a = ["ts>=?"], [since]
        if lane is not None: w.append("lane=?"); a.append(lane)
        if status: w.append("status=?"); a.append(status)
        return self.db.q(f"SELECT * FROM spans WHERE {' AND '.join(w)} ORDER BY ts DESC LIMIT ?", (*a, limit))
