"""IssueStore 的 SQLite 實作（POC）：issue、事件、action、升級、對話。正式版可換 Postgres。"""
import json
import time


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
