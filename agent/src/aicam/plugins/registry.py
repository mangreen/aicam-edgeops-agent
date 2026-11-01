"""Tool manifest 與 registry。

每個 tool 自帶 manifest（名稱、schema、風險等級、是否可由 Agent 規劃／是否可由對話呼叫）。
沒有合法風險等級的 tool 無法註冊（default-deny）；停用的 tool 不會出現在 registry、
不會提供給 LLM、也不能被執行。
"""
from dataclasses import dataclass, field

LEVELS = ("L0", "L1", "L2", "L3")
_TYPES = {"integer": int, "string": str, "number": (int, float), "object": dict, "boolean": bool, "array": list}


class ConfigError(Exception):
    """設定或外掛宣告錯誤：啟動時即失敗（fail-fast），避免打錯字而默默停用安全工具。"""


@dataclass
class ToolSpec:
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
