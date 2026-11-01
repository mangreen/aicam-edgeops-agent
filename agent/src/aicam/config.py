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
class Settings:
    """不可變設定。TOML 區段保存在 raw，由 plugins／guards／prompts 各自解析。"""
    db_path: str = ":memory:"
    sim_url: str = "http://sim:8001"
    verify_wait: float = 7.0
    operator_timeout: float = 30.0
    detect_samples: int = 3
    lanes: tuple = (1, 2)
    detector: DetectorCfg = field(default_factory=DetectorCfg)
    policy: PolicyCfg = field(default_factory=PolicyCfg)
    raw: dict = field(default_factory=dict)   # 完整 TOML，供 plugins / guards / rbac 解析
    config_path: str = ""

    def feature(self, name: str) -> bool:
        return bool(self.raw.get("features", {}).get(name, FEATURE_DEFAULTS[name]))

    def section(self, name: str) -> dict:
        return self.raw.get(name, {})


def _read_toml(path: str) -> dict:
    p = Path(path)
    if not path or not p.is_file():
        return {}
    with p.open("rb") as f:
        return tomllib.load(f)


def load_settings(path: str | None = None, env=None) -> Settings:
    env = os.environ if env is None else env
    path = path or env.get("AICAM_CONFIG", "config/agent.toml")
    raw = _read_toml(path)
    rt = raw.get("runtime", {})
    s = Settings(
        db_path=env.get("DB_PATH", rt.get("db_path", "/data/agent.db")),
        sim_url=env.get("SIM_URL", rt.get("sim_url", "http://sim:8001")),
        verify_wait=float(env.get("VERIFY_WAIT", rt.get("verify_wait", 7))),
        operator_timeout=float(env.get("OPERATOR_TIMEOUT", rt.get("operator_timeout", 30))),
        detect_samples=int(rt.get("detect_samples", 3)),
        lanes=tuple(rt.get("lanes", (1, 2))),
        detector=DetectorCfg(**raw.get("detector", {})),
        policy=PolicyCfg(**{**raw.get("policy", {}), **({"agent_writable": tuple(raw["policy"]["agent_writable"])} if "agent_writable" in raw.get("policy", {}) else {})}),
        raw=raw, config_path=path,
    )
    return s
