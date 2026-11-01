"""KnowledgePort 的 FTS5 實作（POC）。正式版可換向量庫 + bge-m3。"""


class FtsKnowledge:
    """FTS5（trigram，支援中文）全文檢索；2 字以下查詢退回 LIKE。"""
    def __init__(self, db): self.db = db

    def index(self, title, body, kind):
        self.db.x("INSERT INTO kb(title,body,kind) VALUES(?,?,?)", (title, body, kind))

    def search(self, query, k=3, kinds=None):
        kf = f"AND kind IN ({','.join('?' * len(kinds))})" if kinds else ""
        ka = tuple(kinds or ())
        terms = [t for t in query.replace('"', " ").split() if len(t) >= 3]
        rows = []
        if terms:
            m = " OR ".join(f'"{t}"' for t in terms)
            try:
                rows = self.db.q("SELECT title, kind, snippet(kb,1,'[',']','…',24) sn, bm25(kb) s FROM kb "
                                 f"WHERE kb MATCH ? {kf} ORDER BY s LIMIT ?", (m, *ka, k))
            except Exception:
                rows = []
        if not rows:  # 短查詢（如中文 2 字）退回 LIKE
            rows = self.db.q("SELECT title, kind, substr(body,1,120) sn, 0 s FROM kb "
                             f"WHERE (body LIKE ? OR title LIKE ?) {kf} LIMIT ?", (f"%{query}%", f"%{query}%", *ka, k))
        return rows
