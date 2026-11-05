"""A3：工具逾時、L1 嚴格轉型、限頻訊息、背景 task 參考。"""
import asyncio
from dataclasses import replace

import pytest

from aicam.core import policy
from aicam.core.executor import Call, execute
from aicam.plugins.registry import ToolSpec, normalize_args


async def test_hanging_tool_times_out_instead_of_blocking(d):
    async def hang(dd, c):
        await asyncio.sleep(60)
    d.tools.specs["hang"] = ToolSpec("hang", "x", {}, (), "L0", hang)
    d.tools.enabled["hang"] = True
    d.s = replace(d.s, tool_timeout=0.1)
    iid = d.issues.create(1, "inference_stalled")
    t0 = asyncio.get_running_loop().time()
    r = await execute(d, "hang", {}, Call(issue_id=iid))
    assert r["ok"] is False and "逾時" in r["summary"] and asyncio.get_running_loop().time() - t0 < 2
    assert d.db.q("SELECT 1 FROM events WHERE issue_id=? AND text LIKE '%hang%逾時%'", (iid,))     # 事件時間軸可見


async def test_timed_out_action_is_recorded_as_failed(d):
    async def hang(dd, c, lane):
        await asyncio.sleep(60)
    d.tools.specs["slow_fix"] = ToolSpec("slow_fix", "x", {"lane": {"type": "integer"}}, ("lane",), "L1", hang, plannable=True)
    d.tools.enabled["slow_fix"] = True
    d.s = replace(d.s, tool_timeout=0.1)
    r = await execute(d, "slow_fix", {"lane": 1}, Call(origin="agent"))
    assert r["ok"] is False
    assert d.issues.actions()[-1]["status"] == "failed"


def test_default_tool_timeout_is_configured(d):
    assert d.s.tool_timeout == 30


@pytest.mark.parametrize("lane", ["Lane 1 and 2", "lane 1", "1,2", "第 1 車道", "1 and 2"])
async def test_action_tools_do_not_extract_numbers_from_text(d, lane):
    r = await execute(d, "restart_pipeline", {"lane": lane}, Call(origin="agent"))
    assert r["blocked"] == "invalid_args" and d.edge.calls == []


@pytest.mark.parametrize("lane,expected", [("1", 1), (" 2 ", 2), (1.0, 1)])
async def test_action_tools_still_accept_plain_numbers(d, lane, expected):
    r = await execute(d, "restart_pipeline", {"lane": lane}, Call(origin="agent"))
    assert r["ok"] and d.edge.calls == [("restart", expected)]


def test_readonly_tools_keep_lenient_extraction(d):
    args, _ = normalize_args(d.tools.specs["query_metrics"], {"lane": "Lane 1"})
    assert args["lane"] == 1


def test_rate_limit_message_follows_configured_window():
    ctx = {"level": "L1", "now": 1000, "rate_window": 120, "l1_max": 1, "recent": [{"tool": "restart_pipeline", "lane": 1, "ts": 990}]}
    assert "1 次/2 分鐘" in policy.evaluate("restart_pipeline", {"lane": 1}, ctx).reason
    assert "10 分鐘" in policy.evaluate("restart_pipeline", {"lane": 1}, {**ctx, "rate_window": 600}).reason


async def test_post_rollback_verify_task_is_kept_until_done(d):
    from fastapi.testclient import TestClient

    from aicam.api.app import create_app
    from aicam.core.loop import Agent
    d.s = replace(d.s, verify_wait=0.3)
    await execute(d, "apply_config", {"patch": {"model": "m2"}, "reason": "x"}, Call(actor="engineer", origin="external"))
    eid = d.issues.esc_create(None, "operator", "confirm_rollback", "t", {"to_seq": d.versions.head()["parent_seq"]})
    with TestClient(create_app(rt=d, agent=Agent(d), background=False)) as client:   # 讓 event loop 在請求之間持續存在
        assert client.post(f"/api/escalations/{eid}/respond", json={"response": "confirm"}).status_code == 200
        bg = client.app.state.bg
        assert len(bg) == 1                  # 回應當下 task 仍在執行，並被強參考持有
        await asyncio.sleep(0)               # 讓出控制權（task 跑在 TestClient 自己的 loop 執行緒）
        for _ in range(40):
            if not bg:
                break
            await asyncio.sleep(0.05)
        assert len(bg) == 0                  # 完成後自動移除
    assert d.db.q("SELECT 1 FROM events WHERE text LIKE 'rollback 後 Verify%'")
