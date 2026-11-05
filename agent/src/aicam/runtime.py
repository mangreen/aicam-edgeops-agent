"""Runtime = 所有 port 的實例集合（composition root 的產物）。核心邏輯只透過它取用依賴。"""
import os
from dataclasses import dataclass, field

from aicam.adapters.guards import build_pipeline
from aicam.adapters.llm import make_llm
from aicam.adapters.sqlite import DB, FtsKnowledge, OutboxNotifier, SqliteIssues, SqliteObs, SqliteVersions
from aicam.config import Settings, load_dotenv, load_settings
from aicam.plugins.loader import build_registry
from aicam.plugins.skills import load_skills
from aicam.prompts import PromptStore


@dataclass
class Runtime:
    """所有 port 實例與可熱重載的外掛狀態（tools / skills / guards / prompts）。核心邏輯只依賴它。"""
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
    config_synced: bool = True   # 目前版本是否已成功推送到邊緣端；False 時由 Agent 背景重試
    guards: object = None   # GuardPipeline
    prompts: object = None  # PromptStore

    def _on_guard_hit(self, stage, r, ctx):
        self.issues.event(ctx.get("issue_id"), "guard", f"[{stage}/{r.guard}] {r.action}：{r.reason}")

    def attach_llm(self, llm):
        """掛上 LLM，並讓它從 PromptStore 取得目前生效的 system prompt。"""
        self.llm = llm
        llm.set_prompt_source(lambda scope: self.prompts.compose(scope))

    def reset_llm(self, env_file: str | None = None) -> dict:
        """依 .env（優先）與容器環境變數重建 LLM provider，並清除退回 Mock 的狀態。

        用於 Reset：雲端曾失敗而退回 Mock、或使用者剛改了 .env 的 provider／金鑰，都不必重啟容器。
        """
        path = env_file if env_file is not None else os.environ.get("AICAM_ENV_FILE", "/app/.env")
        file_env = load_dotenv(path)
        llm = make_llm(lambda m: self.issues.event(None, "llm", m), {**os.environ, **file_env})
        self.attach_llm(llm)
        info = llm.info()
        src = ".env" if file_env else "容器環境變數（找不到 .env）"
        self.issues.event(None, "llm", f"LLM 已重新載入：{info['configured']}/{info['model']}（來源：{src}）"
                          + (f"；{llm.last_error}" if llm.last_error else ""))
        return {**info, "source": src}

    def rebuild_plugins(self):
        self.tools = build_registry(self.s, self.overrides)
        self.skills = load_skills(self.s, self.tools)
        self.guards = build_pipeline(self.s, self._on_guard_hit)

    def reload(self):
        """重讀設定檔並重建 registry／skills；設定有誤時丟出 ConfigError，保留原狀態。"""
        new = load_settings(self.s.config_path, {**os.environ, "DB_PATH": self.s.db_path, "SIM_URL": self.s.sim_url})
        tools = build_registry(new, None)
        guards = build_pipeline(new, self._on_guard_hit)     # 先全部建好再切換，設定有誤時維持原狀
        self.s, self.overrides, self.tools, self.guards = new, {}, tools, guards
        self.skills = load_skills(new, tools)


def build(settings: Settings, edge=None, llm=None) -> Runtime:
    db = DB(settings.db_path)
    rt = Runtime(settings, db, SqliteObs(db), SqliteIssues(db), SqliteVersions(db),
                 FtsKnowledge(db), OutboxNotifier(db), edge, llm)
    rt.prompts = PromptStore(rt)
    rt.rebuild_plugins()
    if llm:
        rt.attach_llm(llm)
    return rt
