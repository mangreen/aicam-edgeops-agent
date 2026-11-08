"""設定載入：預設值 → config/agent.toml → 環境變數覆寫。

機密（API key）只從環境變數讀取，不寫入 TOML。TOML 區段（tools、guards、rbac…）
保留在 `raw`，由各自的模組解析，避免設定模型與功能耦合。
"""
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# 超出 Operator 權限的功能由設定檔 [features] 開關控制（POC 不實作 RBAC；使用者固定為 Operator）。
# 預設只開聊天；其餘需在設定檔明確開啟。
FEATURE_DEFAULTS = {"chat": True, "tool_toggle": False, "admin_reload": False, "prompt_edit": False,
                    "llm_probe": False, "demo_controls": False}


@dataclass(frozen=True)
class DetectorCfg:
    """偵測與驗證用的門檻（原本散落在程式中的魔術數字）。"""
    window_sec: float = 20.0          # 只看最近 N 秒的樣本，避免舊資料觸發
    min_detections: float = 4.0       # 偵測數低於此值視為驟降／高於此值視為健康
    suspect_window_sec: float = 900.0  # 變更與異常的關聯視窗
    drop_ratio: float = 0.5           # 變更後平均 < 變更前 × ratio 才視為相關
    healthy_min_samples: int = 2      # Verify 至少需要的新樣本數


@dataclass(frozen=True)
class PolicyCfg:
    """Policy gate 的頻率限制與 Agent 可自行修改的設定白名單。"""
    l1_max_per_10min: int = 2         # L1 動作頻率上限，防止重啟風暴
    rate_window_sec: float = 600.0
    # Agent 自行 apply_config 時只能改這些設定路徑（fnmatch）；其他需 Operator 確認
    agent_writable: tuple = ("lanes.*.decoder_profile", "lanes.*.fps_threshold")


@dataclass(frozen=True)
class IngestCfg:
    """/ingest 允許的時間戳範圍（相對於接收時間）：擋掉明顯錯誤或惡意的 ts。"""
    max_future_sec: float = 300.0
    max_past_sec: float = 30 * 86400.0


@dataclass(frozen=True)
class Settings:
    """不可變設定。TOML 區段保存在 raw，由 plugins／guards／prompts 各自解析。"""
    db_path: str = ":memory:"
    sim_url: str = "http://sim:8001"
    verify_wait: float = 7.0
    operator_timeout: float = 30.0
    detect_samples: int = 3
    max_attempts: int = 2             # Agent 對同一個 issue 自動修復的最多嘗試次數；用完仍失敗就升級 Operator（調小可加快 demo）
    tool_timeout: float = 30.0        # 單一工具執行的上限秒數；逾時視為失敗，避免卡住整個 loop
    lanes: tuple = (1, 2)
    detector: DetectorCfg = field(default_factory=DetectorCfg)
    policy: PolicyCfg = field(default_factory=PolicyCfg)
    ingest: IngestCfg = field(default_factory=IngestCfg)
    raw: dict = field(default_factory=dict)   # 合併後的完整 TOML，供 plugins / guards / rbac 解析
    config_path: str = ""                     # 基礎設定檔（prompts／skills 目錄以它所在的資料夾為準）
    config_files: tuple = ()                  # 實際載入的檔案：基礎檔，以及存在時的 *.local.toml

    def feature(self, name: str) -> bool:
        return bool(self.raw.get("features", {}).get(name, FEATURE_DEFAULTS[name]))

    def section(self, name: str) -> dict:
        return self.raw.get(name, {})


class ConfigFileError(ValueError):
    """設定檔語法錯誤；訊息含檔名，方便知道是基礎檔還是本機覆寫檔。"""


def _read_toml(path: str) -> dict:
    p = Path(path)
    if not path or not p.is_file():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigFileError(f"{path}: {e}") from e


def deep_merge(base: dict, over: dict) -> dict:
    """table 逐鍵遞迴合併；數值與清單整個取代（例如 [skills] enabled 在 local 出現就取代整份清單）。"""
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def local_config_path(path: str, env) -> str:
    """本機覆寫檔：agent.toml → agent.local.toml（已加入 .gitignore）。
    `AICAM_CONFIG_LOCAL` 可指定其他路徑；設成空字串＝停用（測試用，避免本機設定影響結果）。"""
    if not path:
        return ""
    if "AICAM_CONFIG_LOCAL" in env:
        return env["AICAM_CONFIG_LOCAL"]
    p = Path(path)
    return str(p.with_name(f"{p.stem}.local{p.suffix}"))


def load_settings(path: str | None = None, env=None) -> Settings:
    env = os.environ if env is None else env
    path = path or env.get("AICAM_CONFIG", "config/agent.toml")
    raw = _read_toml(path)
    files = [path] if path and Path(path).is_file() else []
    local = local_config_path(path, env)
    if local and Path(local).is_file():          # 有本機覆寫檔才疊加；沒有就直接用基礎設定檔
        raw = deep_merge(raw, _read_toml(local))
        files.append(local)
    rt = raw.get("runtime", {})
    s = Settings(
        db_path=env.get("DB_PATH", rt.get("db_path", "/data/agent.db")),
        sim_url=env.get("SIM_URL", rt.get("sim_url", "http://sim:8001")),
        # 時間／次數類的調校只由 agent.toml 決定（不讀環境變數）：舊的 .env 若殘留 VERIFY_WAIT 之類的值，
        # 會靜默蓋掉你在 TOML 的修改，而且容器環境變數無法熱重載。
        verify_wait=float(rt.get("verify_wait", 7)),
        operator_timeout=float(rt.get("operator_timeout", 30)),
        detect_samples=int(rt.get("detect_samples", 3)),
        max_attempts=max(1, int(rt.get("max_attempts", 2))),
        tool_timeout=float(rt.get("tool_timeout", 30)),
        lanes=tuple(rt.get("lanes", (1, 2))),
        detector=DetectorCfg(**raw.get("detector", {})),
        ingest=IngestCfg(**raw.get("ingest", {})),
        policy=PolicyCfg(**{**raw.get("policy", {}), **({"agent_writable": tuple(raw["policy"]["agent_writable"])} if "agent_writable" in raw.get("policy", {}) else {})}),
        raw=raw, config_path=path, config_files=tuple(files),
    )
    return s


def load_dotenv(path: str) -> dict:
    """讀取 .env（KEY=VALUE；支援 # 註解與引號）。檔案不存在回 {}。

    容器的環境變數在建立時就固定；.env 以唯讀掛入容器，讓 Reset 能在不重啟的情況下重新讀取 LLM 設定。
    """
    p = Path(path) if path else None
    if not p or not p.is_file():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) >= 2:
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].strip()
        out[k.strip().removeprefix("export ").strip()] = v
    return out
