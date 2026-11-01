"""Runtime = 所有 port 的實例集合（composition root 的產物）。核心邏輯只透過它取用依賴。"""
from dataclasses import dataclass

from aicam.adapters.sqlite import DB, FtsKnowledge, OutboxNotifier, SqliteIssues, SqliteObs, SqliteVersions
from aicam.config import Settings


@dataclass
class Runtime:
    s: Settings
    db: DB
    obs: SqliteObs
    issues: SqliteIssues
    versions: SqliteVersions
    kb: FtsKnowledge
    notifier: OutboxNotifier
    edge: object = None   # EdgeControlPort
    llm: object = None    # LLMProvider


def build(settings: Settings, edge=None, llm=None) -> Runtime:
    db = DB(settings.db_path)
    return Runtime(settings, db, SqliteObs(db), SqliteIssues(db), SqliteVersions(db),
                   FtsKnowledge(db), OutboxNotifier(db), edge, llm)
