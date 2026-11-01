"""由設定檔組出 ToolRegistry。

[tools]            每個 tool 一行 true/false；`default_enabled` 決定內建工具預設值。
[tool_sources]     python = ["pkg.mod"]（模組需提供 TOOLS）；mcp.<name> 需有已註冊的 adapter。
python／MCP 來源的 tool 預設停用，必須在 [tools] 明確啟用。打錯工具名稱會直接報錯。
"""
import importlib

from aicam.ports.mcp import McpSourcePort  # noqa: F401  (型別參考)

from .registry import LEVELS, ConfigError, ToolRegistry, ToolSpec

BUILTIN_MODULES = ["observability", "knowledge", "versions", "remediation"]

# MCP adapter 註冊點：{"adapter 名稱": factory(conf: dict) -> McpSourcePort}。
# POC 沒有內建任何 adapter（只有介面）；設定了未註冊的 adapter 會在啟動時報錯。
MCP_ADAPTERS: dict = {}


def _builtin_specs() -> list[ToolSpec]:
    specs = []
    for m in BUILTIN_MODULES:
        specs += importlib.import_module(f"aicam.plugins.builtin.{m}").TOOLS
    return specs


def _mcp_specs(name: str, conf: dict) -> list[ToolSpec]:
    factory = MCP_ADAPTERS.get(conf.get("adapter", ""))
    if not factory:
        raise ConfigError(f"MCP 來源 {name!r} 的 adapter {conf.get('adapter')!r} 未安裝（POC 只提供介面）")
    src = factory(conf)
    levels = conf.get("levels", {})
    specs = []
    for t in src.list_tools():
        tname = t["name"]

        async def call(d, c, _t=tname, _src=src, **a):
            return await _src.call_tool(_t, a)
        lv = levels.get(tname, "L3")            # 沒宣告等級 → L3（只能升級給工程師）
        if lv not in LEVELS:
            raise ConfigError(f"MCP tool {tname!r} 等級 {lv!r} 不合法")
        schema = t.get("inputSchema", {})
        specs.append(ToolSpec(tname, t.get("description", ""), schema.get("properties", {}),
                              tuple(schema.get("required", [])), lv, call, source=f"mcp:{name}"))
    return specs


def build_registry(settings, overrides: dict | None = None) -> ToolRegistry:
    tc = dict(settings.section("tools"))
    default = tc.pop("default_enabled", True)
    sources = settings.section("tool_sources")
    specs: list[ToolSpec] = _builtin_specs()
    for mod in sources.get("python", []):
        specs += [ToolSpec(**{**s.__dict__, "source": "python"}) for s in importlib.import_module(mod).TOOLS]
    for name, conf in sources.get("mcp", {}).items():
        specs += _mcp_specs(name, conf)
    by_name = {}
    for s in specs:
        if s.name in by_name:
            raise ConfigError(f"tool 名稱重複：{s.name}")
        by_name[s.name] = s
    unknown = [k for k in list(tc) + list(overrides or {}) if k not in by_name]
    if unknown:
        raise ConfigError(f"[tools] 含未知工具：{unknown}")
    reg = ToolRegistry(specs=by_name)
    for n, s in by_name.items():
        if overrides and n in overrides:
            reg.enabled[n], reg.reasons[n] = bool(overrides[n]), "runtime override"
        elif n in tc:
            reg.enabled[n], reg.reasons[n] = bool(tc[n]), "設定檔 [tools]"
        else:
            on = default if s.source == "builtin" else False
            reg.enabled[n], reg.reasons[n] = on, "內建預設" if on else "外部來源需明確啟用"
    return reg
