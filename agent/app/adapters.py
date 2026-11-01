"""SQLite 版 adapters（POC）。正式版替換成 Loki/Prometheus/Tempo、Postgres、向量庫等。"""
import json, time
from . import versions as V


class SqliteObs:
    def __init__(self, db): self.db = db

    def ingest(self, logs, metrics, spans):
        self.db.many("INSERT INTO logs(ts,lane,level,msg) VALUES(?,?,?,?)",
                     [(x["ts"], x["lane"], x["level"], x["msg"]) for x in logs])
        self.db.many("INSERT INTO metrics VALUES(?,?,?,?)",
                     [(x["ts"], x["lane"], x["name"], x["value"]) for x in metrics])
        self.db.many("INSERT INTO spans VALUES(?,?,?,?,?,?,?,?)",
                     [(x["trace_id"], x["span_id"], x["parent_id"], x["name"], x["lane"], x["ts"],
                       x["dur_ms"], x["status"]) for x in spans])

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
        sql = "SELECT ts,value FROM metrics WHERE lane=? AND name=? AND ts>? ORDER BY ts DESC"
        return self.db.q(sql + (f" LIMIT {int(limit)}" if limit else ""), (lane, name, since))

    def spans(self, lane=None, since=0, status=None, limit=10):
        w, a = ["ts>=?"], [since]
        if lane is not None: w.append("lane=?"); a.append(lane)
        if status: w.append("status=?"); a.append(status)
        return self.db.q(f"SELECT * FROM spans WHERE {' AND '.join(w)} ORDER BY ts DESC LIMIT ?", (*a, limit))


class SqliteIssues:
    def __init__(self, db): self.db = db

    def create(self, lane, kind):
        return self.db.x("INSERT INTO issues(lane,kind,status,created) VALUES(?,?,?,?)",
                         (lane, kind, "detected", time.time()))

    def update(self, iid, **f):
        self.db.x(f"UPDATE issues SET {','.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), iid))

    def get(self, iid):
        r = self.db.q("SELECT * FROM issues WHERE id=?", (iid,))
        return r[0] if r else None

    def list(self, limit=20, kind=None, lane=None, open_only=False):
        w, a = ["1=1"], []
        if kind: w.append("kind=?"); a.append(kind)
        if lane is not None: w.append("lane=?"); a.append(lane)
        if open_only: w.append("closed IS NULL")
        return self.db.q(f"SELECT * FROM issues WHERE {' AND '.join(w)} ORDER BY created DESC LIMIT ?", (*a, limit))

    def event(self, issue_id, type_, text):
        return self.db.x("INSERT INTO events(ts,issue_id,type,text) VALUES(?,?,?,?)",
                         (time.time(), issue_id, type_, text))

    def events(self, after=0, limit=200, issue_id=None):
        if issue_id is not None:
            return self.db.q("SELECT * FROM events WHERE issue_id=? ORDER BY id", (issue_id,))
        return self.db.q("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit))

    # actions
    def action_start(self, aid, issue_id, tool, args, level, actor):
        self.db.x("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, issue_id, tool, json.dumps(args, ensure_ascii=False), level, actor, "running", None, time.time()))

    def action_finish(self, aid, ok, result):
        self.db.x("UPDATE actions SET status=?, result=? WHERE action_id=?",
                  ("ok" if ok else "failed", json.dumps(result, ensure_ascii=False, default=str), aid))

    def actions(self, issue_id=None, since=0):
        if issue_id is not None:
            return self.db.q("SELECT * FROM actions WHERE issue_id=? ORDER BY ts", (issue_id,))
        return self.db.q("SELECT * FROM actions WHERE ts>? ORDER BY ts", (since,))

    # escalations
    def esc_create(self, issue_id, to_who, kind, text, payload=None, timeout=None):
        now = time.time()
        return self.db.x("INSERT INTO escalations(issue_id,to_who,kind,text,payload,status,created,deadline) "
                         "VALUES(?,?,?,?,?,?,?,?)",
                         (issue_id, to_who, kind, text, json.dumps(payload or {}, ensure_ascii=False),
                          "pending", now, now + timeout if timeout else None))

    def esc_get(self, eid):
        r = self.db.q("SELECT * FROM escalations WHERE id=?", (eid,))
        return r[0] if r else None

    def esc_pending(self):
        return self.db.q("SELECT * FROM escalations WHERE status='pending' ORDER BY id")

    def esc_respond(self, eid, response, status="done"):
        self.db.x("UPDATE escalations SET status=?, response=? WHERE id=? AND status='pending'",
                  (status, response, eid))

    # messages
    def msg_add(self, role, content, session="default", ts=None):
        self.db.x("INSERT INTO messages(session,role,content,ts) VALUES(?,?,?,?)",
                  (session, role, content, ts or time.time()))

    def msgs(self, session="default", limit=50):
        return list(reversed(self.db.q("SELECT role,content,ts FROM messages WHERE session=? "
                                       "ORDER BY id DESC LIMIT ?", (session, limit))))

    def msg_search(self, q, limit=5):
        return self.db.q("SELECT role,content,ts FROM messages WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
                         (f"%{q}%", limit))


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


class FtsKnowledge:
    def __init__(self, db): self.db = db

    def index(self, title, body, kind):
        self.db.x("INSERT INTO kb(title,body,kind) VALUES(?,?,?)", (title, body, kind))

    def search(self, query, k=3):
        terms = [t for t in query.replace('"', " ").split() if len(t) >= 3]
        rows = []
        if terms:
            m = " OR ".join(f'"{t}"' for t in terms)
            try:
                rows = self.db.q("SELECT title, kind, snippet(kb,1,'[',']','…',24) sn, bm25(kb) s FROM kb "
                                 "WHERE kb MATCH ? ORDER BY s LIMIT ?", (m, k))
            except Exception:
                rows = []
        if not rows:  # 短查詢（如中文 2 字）退回 LIKE
            rows = self.db.q("SELECT title, kind, substr(body,1,120) sn, 0 s FROM kb WHERE body LIKE ? OR title LIKE ? LIMIT ?",
                             (f"%{query}%", f"%{query}%", k))
        return rows


class OutboxNotifier:
    """POC：寫入 outbox（UI 的遠端工程師面板讀取）。正式版換 PagerDuty / LINE / Slack。"""
    def __init__(self, db): self.db = db

    def notify(self, target, payload):
        self.db.x("INSERT INTO outbox(ts,target,payload) VALUES(?,?,?)",
                  (time.time(), target, json.dumps(payload, ensure_ascii=False, default=str)))
