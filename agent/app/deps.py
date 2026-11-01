import os
from dataclasses import dataclass, field
from . import adapters as A
from .db import DB


@dataclass
class Settings:
    db_path: str = os.getenv("DB_PATH", "/data/agent.db")
    sim_url: str = os.getenv("SIM_URL", "http://sim:8001")
    verify_wait: float = float(os.getenv("VERIFY_WAIT", "7"))
    operator_timeout: float = float(os.getenv("OPERATOR_TIMEOUT", "30"))
    detect_samples: int = 3
    lanes: tuple = (1, 2)


@dataclass
class Deps:
    s: Settings
    db: DB
    obs: A.SqliteObs
    issues: A.SqliteIssues
    versions: A.SqliteVersions
    kb: A.FtsKnowledge
    notifier: A.OutboxNotifier
    sim: object = None
    llm: object = None


def build(settings: Settings, sim=None, llm=None) -> Deps:
    db = DB(settings.db_path)
    return Deps(settings, db, A.SqliteObs(db), A.SqliteIssues(db), A.SqliteVersions(db),
                A.FtsKnowledge(db), A.OutboxNotifier(db), sim, llm)
