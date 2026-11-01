"""Runtime = 所有 port 的實例集合（composition root 的產物）。核心邏輯只透過它取用依賴。"""
import os
from dataclasses import dataclass, field

from aicam.adapters.sqlite import DB, FtsKnowledge, OutboxNotifier, SqliteIssues, SqliteObs, SqliteVersions
from aicam.config import Settings, load_settings
from aicam.plugins.loader import build_registry
from aicam.plugins.skills import load_skills


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
    tools: object = None  # ToolRegistry
    skills: list = field(default_factory=list)
    overrides: dict = field(default_factory=dict)   # 執行期工具開關（重載設定檔時清除）

    def rebuild_plugins(self):
        self.tools = build_registry(self.s, self.overrides)
        self.skills = load_skills(self.s, self.tools)

    def reload(self):
        """重讀設定檔並重建 registry／skills；設定有誤時丟出 ConfigError，保留原狀態。"""
        new = load_settings(self.s.config_path, {**os.environ, "DB_PATH": self.s.db_path, "SIM_URL": self.s.sim_url})
        tools = build_registry(new, None)
        self.s, self.overrides, self.tools = new, {}, tools
        self.skills = load_skills(new, tools)


def build(settings: Settings, edge=None, llm=None) -> Runtime:
    db = DB(settings.db_path)
    rt = Runtime(settings, db, SqliteObs(db), SqliteIssues(db), SqliteVersions(db),
                 FtsKnowledge(db), OutboxNotifier(db), edge, llm)
    rt.rebuild_plugins()
    return rt
