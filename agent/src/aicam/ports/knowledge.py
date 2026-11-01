"""KnowledgePort：runbook 與歷史 issue 檢索。POC：FTS5；正式版：向量庫 + bge-m3。"""
from typing import Protocol


class KnowledgePort(Protocol):
    def index(self, title: str, body: str, kind: str) -> None: ...
    def search(self, query: str, k: int = 3, kinds: list | None = None) -> list: ...
