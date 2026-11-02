import sys
import textwrap
from dataclasses import replace

import pytest

from aicam.core.executor import Call, execute
from aicam.plugins import loader
from aicam.plugins.registry import ConfigError, ToolSpec
from aicam.runtime import build


def with_raw(d, **raw):
    d.s = replace(d.s, raw=raw)
    d.rebuild_plugins()
    return d


async def test_disabled_tool_is_hidden_and_not_executable(d):
    assert "query_logs" in d.tools.names()
    with_raw(d, tools={"query_logs": False})
    assert "query_logs" not in d.tools.names() and all(t["name"] != "query_logs" for t in d.tools.mcp_tools())
    r = await execute(d, "query_logs", {"lane": 1})
    assert r["blocked"] == "disabled"
    assert "query_logs" not in d.tools.names(chat=True)          # 對話也看不到


def test_unknown_tool_in_config_fails_fast(d):
    with pytest.raises(ConfigError):
        with_raw(d, tools={"query_logz": False})


def test_default_enabled_false_disables_builtin_unless_listed(d):
    with_raw(d, tools={"default_enabled": False, "get_status": True})
    assert d.tools.names() == ["get_status"]


async def test_invalid_args(d):
    for args in ({}, {"lane": "x"}, {"lane": 1, "x": 1}, {"lane": True}, {"lane": [1]}):
        r = await execute(d, "restart_pipeline", args)
        assert r["blocked"] == "invalid_args", args
    assert d.edge.calls == []                                                  # 沒有任何動作被執行


async def test_lane_string_is_coerced_not_rejected(d):
    r = await execute(d, "restart_pipeline", {"lane": "1"})                    # LLM 常把數字寫成字串
    assert r["ok"] and d.edge.calls == [("restart", 1)]


def test_spec_without_valid_level_cannot_register():
    with pytest.raises(ConfigError):
        ToolSpec("x", "d", {}, (), "L9", None)


async def test_python_plugin_must_be_explicitly_enabled(d, tmp_path, monkeypatch):
    (tmp_path / "acme_plugin.py").write_text(textwrap.dedent('''
        from aicam.plugins.registry import Toolbox
        box = Toolbox()

        @box.tool("acme_ping", "ping", level="L0", chat=True)
        async def ping(d, c):
            return {"summary": "pong"}
        TOOLS = box.tools
    '''))
    monkeypatch.syspath_prepend(str(tmp_path))
    with_raw(d, tool_sources={"python": ["acme_plugin"]})
    assert d.tools.specs["acme_ping"].source == "python" and "acme_ping" not in d.tools.names()
    with_raw(d, tool_sources={"python": ["acme_plugin"]}, tools={"acme_ping": True})
    assert (await execute(d, "acme_ping"))["summary"] == "pong"
    sys.modules.pop("acme_plugin", None)


class FakeMcp:
    def list_tools(self):
        return [{"name": "create_ticket", "description": "t", "inputSchema": {"properties": {"title": {"type": "string"}},
                                                                             "required": ["title"]}},
                {"name": "list_tickets", "description": "t", "inputSchema": {"properties": {}}}]

    async def call_tool(self, name, arguments):
        return {"summary": f"{name}:{arguments}"}


async def test_mcp_interface_wiring_default_deny(d, monkeypatch):
    monkeypatch.setitem(loader.MCP_ADAPTERS, "fake", lambda conf: FakeMcp())
    raw = {"tool_sources": {"mcp": {"x": {"adapter": "fake", "levels": {"list_tickets": "L0"}}}},
           "tools": {"create_ticket": True, "list_tickets": True}}
    with_raw(d, **raw)
    assert d.tools.specs["create_ticket"].level == "L3"                        # 沒宣告等級 → L3
    assert (await execute(d, "list_tickets"))["summary"].startswith("list_tickets")
    r = await execute(d, "create_ticket", {"title": "t"})
    assert r["blocked"] == "escalate_engineer"                                 # L3 只能升級


def test_mcp_adapter_not_installed_fails_fast(d):
    with pytest.raises(ConfigError):
        with_raw(d, tool_sources={"mcp": {"x": {"adapter": "nope"}}})


def test_skill_inactive_when_required_tool_disabled(d, tmp_path):
    sk = tmp_path / "skills" / "s1"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: s1\ndescription: d\ntools: restart_pipeline\n---\nbody")
    d.s = replace(d.s, config_path=str(tmp_path / "agent.toml"), raw={"skills": {"enabled": ["s1"]}})
    d.rebuild_plugins()
    assert d.skills[0].active
    d.s = replace(d.s, raw={"skills": {"enabled": ["s1"]}, "tools": {"restart_pipeline": False}})
    d.rebuild_plugins()
    assert not d.skills[0].active and "restart_pipeline" in d.skills[0].reason


def test_knowledge_sources_filter(d):
    assert d.kb.search("camera_no_signal", kinds=["runbook"])
    assert all(r["kind"] == "runbook" for r in d.kb.search("camera_no_signal", kinds=["runbook"]))
    assert d.kb.search("插拔", kinds=["issue"]) and not d.kb.search("插拔", kinds=["runbook"])  # 只在 issue 摘要


async def test_agent_apply_config_outside_whitelist_needs_operator(d):
    r = await execute(d, "apply_config", {"patch": {"lanes": {"1": {"roi": [1, 1, 1, 1]}}}, "reason": "x"}, Call())
    assert r["blocked"] == "needs_operator"
    n = d.versions.head()["seq"]
    r = await execute(d, "apply_config", {"patch": {"lanes": {"1": {"fps_threshold": 12}}}, "reason": "x"}, Call())
    assert r["ok"] and d.versions.head()["seq"] == n + 1


def test_build_runtime_registers_builtin_tools():
    from aicam.config import Settings
    rt = build(Settings())
    assert {"query_logs", "restart_pipeline", "rollback_version", "propose_rollback"} <= set(rt.tools.names())
