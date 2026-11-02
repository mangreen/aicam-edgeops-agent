"""Tool manifest 與 registry。

每個 tool 自帶 manifest（名稱、schema、風險等級、是否可由 Agent 規劃／是否可由對話呼叫）。
沒有合法風險等級的 tool 無法註冊（default-deny）；停用的 tool 不會出現在 registry、
不會提供給 LLM、也不能被執行。
"""
import re
from dataclasses import dataclass, field

LEVELS = ("L0", "L1", "L2", "L3")
_TYPES = {"integer": int, "string": str, "number": (int, float), "object": dict, "boolean": bool, "array": list}


class ConfigError(Exception):
    """設定或外掛宣告錯誤：啟動時即失敗（fail-fast），避免打錯字而默默停用安全工具。"""


@dataclass
class ToolSpec:
    """Tool manifest：名稱、MCP 相容 schema、風險等級與實作。沒有合法等級者無法建立（default-deny）。"""
    name: str
    description: str
    props: dict
    required: tuple
    level: str                 # L0 唯讀 / L1 可逆低風險 / L2 需 Operator / L3 只能升級工程師
    fn: object                 # async fn(rt, call, **args) -> dict（需含 summary）
    plannable: bool = False    # 可由 Agent loop 規劃
    chat: bool = False         # 可由對話呼叫
    source: str = "builtin"    # builtin | python | mcp:<name>

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ConfigError(f"tool {self.name!r} 未宣告合法風險等級（{self.level!r}），預設拒絕")

    def mcp(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": {"type": "object", "properties": self.props, "required": list(self.required)},
                "annotations": {"level": self.level, "source": self.source}}


class Toolbox:
    """模組內收集 tool 的小工具：`box = Toolbox()`、`@box.tool(...)`、`TOOLS = box.tools`。"""
    def __init__(self):
        self.tools: list[ToolSpec] = []

    def tool(self, name, desc, props=None, required=(), *, level, plannable=False, chat=False):
        def deco(fn):
            self.tools.append(ToolSpec(name, desc, props or {}, tuple(required), level, fn, plannable, chat))
            return fn
        return deco


@dataclass
class ToolRegistry:
    """已載入的工具與啟用狀態；停用的工具不可見、不可執行。"""
    specs: dict = field(default_factory=dict)       # name -> ToolSpec（含停用者，供能力面板顯示）
    enabled: dict = field(default_factory=dict)     # name -> bool
    reasons: dict = field(default_factory=dict)     # name -> 啟用／停用原因

    def get(self, name):
        return self.specs[name] if self.enabled.get(name) else None

    def names(self, *, plannable=None, chat=None) -> list[str]:
        return [n for n, s in self.specs.items() if self.enabled.get(n)
                and (plannable is None or s.plannable == plannable) and (chat is None or s.chat == chat)]

    def mcp_tools(self) -> list[dict]:
        return [s.mcp() for n, s in self.specs.items() if self.enabled.get(n)]

    def describe(self) -> list[dict]:
        return [{"name": n, "level": s.level, "source": s.source, "enabled": bool(self.enabled.get(n)),
                 "reason": self.reasons.get(n, ""), "plannable": s.plannable, "chat": s.chat,
                 "description": s.description} for n, s in self.specs.items()]

    def __len__(self):
        return sum(1 for v in self.enabled.values() if v)

    @staticmethod
    def validate(spec: ToolSpec, args: dict) -> str | None:
        """依 inputSchema 驗證參數；回傳錯誤訊息或 None。LLM 提案的參數同樣經過這裡。"""
        for k in spec.required:
            if k not in args:
                return f"缺少必要參數 {k}"
        for k, v in args.items():
            if k not in spec.props:
                return f"未知參數 {k}"
            t = _TYPES.get(spec.props[k].get("type"))
            if v is not None and t and (not isinstance(v, t) or (t is int and isinstance(v, bool))):
                return f"參數 {k} 型別錯誤（應為 {spec.props[k].get('type')}）"
        return None


# ---- LLM 提案參數的容錯校正（只做「安全的」改寫：改名、型別轉換、單位換算；不放寬權限）----
# 別名只在「目標參數存在於該工具的 schema、且原名不在 schema」時才套用。
ALIASES = {"lane_id": "lane", "laneid": "lane", "lane_no": "lane", "lane_number": "lane", "lane_index": "lane",
           "hours": "since_hours", "hour": "since_hours", "duration": "since_hours", "time_range": "since_hours",
           "timerange": "since_hours", "period": "since_hours", "window": "since_hours", "since": "since_hours",
           "metric": "name", "metric_name": "name", "keyword": "contains", "pattern": "contains",
           "version": "seq", "version_id": "seq", "from": "a", "to": "b", "from_version": "a", "to_version": "b",
           "target_version": "to_seq", "version_seq": "to_seq"}
_UNIT_H = {"d": 24, "day": 24, "days": 24, "天": 24, "日": 24, "h": 1, "hr": 1, "hrs": 1, "hour": 1, "hours": 1, "小時": 1,
           "m": 1 / 60, "min": 1 / 60, "mins": 1 / 60, "minute": 1 / 60, "minutes": 1 / 60, "分": 1 / 60, "分鐘": 1 / 60,
           "w": 168, "week": 168, "weeks": 168, "週": 168, "周": 168}
_DUR = re.compile(r"(\d+(?:\.\d+)?)\s*([a-zA-Z\u4e00-\u9fff]*)")


def parse_hours(v) -> float | None:
    """'2d' / '48h' / '30 min' / '2 days' / 48 → 小時數；無法解析回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = _DUR.search(str(v).strip().lower())
    if not m:
        return None
    unit = m.group(2) or "h"
    return float(m.group(1)) * _UNIT_H[unit] if unit in _UNIT_H else None


def _coerce(key: str, typ: str, v):
    """依 schema 型別轉換字串值；轉不了就原樣回傳，交給後續驗證拒絕。"""
    if typ == "integer" and isinstance(v, (str, float)) and not isinstance(v, bool):
        m = re.search(r"-?\d+", str(v)) if isinstance(v, str) else None
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if m and (key in ("lane", "seq", "to_seq", "a", "b", "limit") or str(v).strip().lstrip("-").isdigit()):
            return int(m.group(0))
    if typ == "number" and not isinstance(v, bool):
        if key == "since_hours":
            h = parse_hours(v)
            return h if h is not None else v
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                return v
    if typ == "boolean" and isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    if typ == "string" and isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return v


def normalize_args(spec: ToolSpec, args: dict) -> tuple[dict, list[str]]:
    """校正 LLM 提案的參數，回傳 (新參數, 校正說明)。

    - 套用別名（lane_id→lane、duration→since_hours…）
    - 依 schema 轉型（"1"→1、"2d"→48 小時）
    - 唯讀（L0）工具丟棄未知參數；其他等級保留，交給驗證拒絕（不默默忽略高風險工具的怪參數）
    """
    out, notes = {}, []
    for k, v in args.items():
        tgt = ALIASES.get(k.lower()) if k not in spec.props else None
        if tgt and tgt in spec.props and tgt not in args and tgt not in out:
            notes.append(f"{k}→{tgt}")
            k = tgt
        out[k] = v
    for k in list(out):
        if k in spec.props:
            nv = _coerce(k, spec.props[k].get("type", ""), out[k])
            if nv != out[k]:
                notes.append(f"{k}: {out[k]!r}→{nv!r}")
            out[k] = nv
        elif spec.level == "L0":
            notes.append(f"丟棄未知參數 {k}")
            del out[k]
    return out, notes
