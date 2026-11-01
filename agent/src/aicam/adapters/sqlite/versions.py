"""VersionStore 的 SQLite 實作（POC）。正式版可換 Git / S3 / 設定中心。"""
import json, time
from aicam.core import versions as V


class SqliteVersions:
    def __init__(self, db): self.db = db

    def _row(self, r):
        r["content"] = json.loads(r.pop("content_json"))
        return r

    def head(self):
        r = self.db.q("SELECT * FROM versions ORDER BY seq DESC LIMIT 1")
        return self._row(r[0]) if r else None

    def get(self, seq):
        r = self.db.q("SELECT * FROM versions WHERE seq=?", (seq,))
        return self._row(r[0]) if r else None

    def list(self, limit=10):
        return [self._row(r) for r in self.db.q("SELECT * FROM versions ORDER BY seq DESC LIMIT ?", (limit,))]

    def add(self, content, parent, actor, reason, issue_id, ts=None):
        seq = self.db.x("INSERT INTO versions(parent_seq,content_json,sha256,actor,reason,issue_id,ts) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (parent, V.canon(content), V.sha(content), actor, reason, issue_id, ts or time.time()))
        return self.get(seq)
