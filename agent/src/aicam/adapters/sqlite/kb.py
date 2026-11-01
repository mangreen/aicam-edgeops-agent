"""KnowledgePort 的 FTS5 實作（POC）。正式版可換向量庫 + bge-m3。"""


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
