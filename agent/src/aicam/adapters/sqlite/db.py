import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, ts REAL, lane INT, level TEXT, msg TEXT);
CREATE INDEX IF NOT EXISTS ix_logs ON logs(lane, ts);
CREATE TABLE IF NOT EXISTS metrics(ts REAL, lane INT, name TEXT, value REAL);
CREATE INDEX IF NOT EXISTS ix_metrics ON metrics(lane, name, ts);
CREATE TABLE IF NOT EXISTS spans(trace_id TEXT, span_id TEXT, parent_id TEXT, name TEXT, lane INT, ts REAL, dur_ms REAL, status TEXT);
CREATE INDEX IF NOT EXISTS ix_spans ON spans(lane, ts);
CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY, lane INT, kind TEXT, status TEXT, created REAL, closed REAL, resolved_by TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, issue_id INT, type TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS actions(action_id TEXT PRIMARY KEY, issue_id INT, tool TEXT, args TEXT, level TEXT, actor TEXT, status TEXT, result TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS escalations(id INTEGER PRIMARY KEY, issue_id INT, to_who TEXT, kind TEXT, text TEXT, payload TEXT, status TEXT, response TEXT, created REAL, deadline REAL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, session TEXT, role TEXT, content TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS versions(seq INTEGER PRIMARY KEY, parent_seq INT, content_json TEXT, sha256 TEXT, actor TEXT, reason TEXT, issue_id INT, ts REAL);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, ts REAL, target TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS prompt_layers(name TEXT PRIMARY KEY, scope TEXT, priority INT, enabled INT, content TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS prompt_history(id INTEGER PRIMARY KEY, name TEXT, scope TEXT, priority INT, enabled INT, content TEXT, ts REAL, note TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS kb USING fts5(title, body, kind UNINDEXED, tokenize='trigram');
"""
TABLES = ["logs", "metrics", "spans", "issues", "events", "actions", "escalations",
          "messages", "versions", "outbox", "kb", "prompt_layers", "prompt_history"]


class DB:
    """單一連線 + RLock。同步 SQLite 在 async handler 內呼叫：查詢皆為毫秒級小查詢，POC 可接受
    （見 docs/review.md #10）；高負載時改 Postgres adapter 或 run_in_executor。"""
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args)]

    def x(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def many(self, sql, rows):
        with self.lock:
            self.conn.execute("BEGIN")
            self.conn.executemany(sql, rows)
            self.conn.execute("COMMIT")

    def wipe(self):
        with self.lock:
            for t in TABLES:
                self.conn.execute(f"DELETE FROM {t}")
