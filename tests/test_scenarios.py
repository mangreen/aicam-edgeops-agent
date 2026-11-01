import asyncio

from aicam.core import chat
from aicam.plugins.tools import Call, execute
from conftest import emit


async def _pending(d, to, timeout=5):
    for _ in range(int(timeout / 0.05)):
        r = [e for e in d.issues.esc_pending() if e["to_who"] == to]
        if r: return r[0]
        await asyncio.sleep(0.05)
    raise AssertionError(f"no pending escalation for {to}")


async def test_A_auto_fix(d):
    emit(d, 1, fps=0.0, det=0.0)
    [t] = await d.agent.tick()
    await t
    i = d.issues.list(1)[0]
    assert i["status"] == "resolved" and i["resolved_by"] == "agent" and i["kind"] == "inference_stalled"
    assert [a["tool"] for a in d.issues.actions(i["id"])] == ["restart_pipeline"]
    assert any(e["type"] == "report" for e in d.issues.events(issue_id=i["id"]))


async def test_B_to_C_escalation(d):
    d.edge.camera_down.add(1)
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)
    [t] = await d.agent.tick()
    op = await _pending(d, "operator")
    d.issues.esc_respond(op["id"], "cannot")                   # Operator 無法處理
    eng = await _pending(d, "engineer")
    assert d.issues.list(1)[0]["status"] == "escalated_engineer"
    iid = d.issues.list(1)[0]["id"]
    assert "timeline" in eng["payload"] and len([a for a in d.issues.actions(iid) if a["tool"] == "reconnect_stream"]) == 2
    d.issues.esc_respond(eng["id"], "fixed")
    await t
    assert d.issues.list(1)[0]["resolved_by"] == "engineer" and d.db.q("SELECT * FROM outbox")


async def test_B_operator_fixes(d):
    d.edge.camera_down.add(1)
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)
    [t] = await d.agent.tick()
    d.issues.esc_respond((await _pending(d, "operator"))["id"], "fixed")
    await t
    assert d.issues.list(1)[0]["resolved_by"] == "operator"


async def test_B_operator_timeout_calls_engineer(d):
    d.edge.camera_down.add(1)
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)
    [t] = await d.agent.tick()
    await _pending(d, "engineer", timeout=5)                   # operator_timeout=1s
    t.cancel()


async def test_E_bad_config_auto_rollback(d):
    good = d.versions.head()
    await execute(d, "apply_config", {"patch": {"lanes": {"1": {"roi": [120, 200, 60, 40]}}}, "reason": "誤設"}, Call(actor="engineer", origin="external"))
    assert d.versions.head()["seq"] == 7
    [t] = await d.agent.tick()
    await t
    i = d.issues.list(1)[0]
    assert i["kind"] == "detection_drop" and i["status"] == "resolved"
    h = d.versions.head()
    assert h["seq"] == 8 and h["content"] == good["content"] and h["actor"] == "agent" and d.versions.get(7)
    ev = " ".join(e["text"] for e in d.issues.events(issue_id=i["id"]))
    assert "L1 allow" in ev and "roi" in ev and "偵測數" in ev          # 報告附 diff 與證據


async def test_E_no_correlation_goes_to_operator(d):
    emit(d, 1, det=0.2)                                           # 偵測驟降，但近期無相關變更
    [t] = await d.agent.tick()
    await _pending(d, "operator")
    t.cancel()


async def test_chat_queries(d):
    r = await chat.handle(d, "Lane 1 過去 7 天斷線幾次？")
    assert "5 筆" in r["answer"]
    r = await chat.handle(d, "上次類似 Lane 1 斷線問題怎麼解？")
    assert "PoE" in r["answer"]
    r = await chat.handle(d, "Lane 1 最近改了什麼？誰改的？")
    assert "v6" in r["answer"] and "operator" in r["answer"]
    r = await chat.handle(d, "v5 和 v6 差在哪")
    assert "roi" in r["answer"]
    r = await chat.handle(d, "我們之前聊過 Lane 2 的什麼？")
    assert "FPS" in r["answer"]


async def test_chat_rollback_needs_confirmation(d):
    n = d.versions.head()["seq"]
    r = await chat.handle(d, "回到上一版")
    assert "尚未執行" in r["answer"] and d.versions.head()["seq"] == n
    esc = (await _pending(d, "operator"))
    assert esc["kind"] == "confirm_rollback"


async def test_llm_cloud_failure_falls_back_to_mock(d):
    from aicam.adapters.llm import AutoLLM, CloudLLM
    class Broken(CloudLLM):
        name = "broken"
        async def _complete(self, s, u): raise ConnectionError("offline")
    notes = []
    d.llm = AutoLLM(Broken(), on_fallback=notes.append)
    r = await chat.handle(d, "Lane 1 過去 7 天斷線幾次？")
    assert "5 筆" in r["answer"] and r["llm"] == "mock" and notes      # 斷網仍可答，且只提示一次
    emit(d, 1, fps=0.0, det=0.0)
    [t] = await d.agent.tick(); await t
    assert d.issues.list(1)[0]["resolved_by"] == "agent"
