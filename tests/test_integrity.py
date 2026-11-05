"""A1：重啟 recover、rollback 證據由程式碼驗證、來源旗標檢查、config 推送失敗的如實回報。"""
import asyncio
import time

from aicam.core.executor import Call, execute
from aicam.core.loop import Agent
from conftest import emit


async def until(cond, timeout=6):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


def pending(d, to):
    return [e for e in d.issues.esc_pending() if e["to_who"] == to]


# ---------- #1 孤兒 issue ----------
async def test_orphan_in_progress_issue_is_closed_and_redetected(d):
    iid = d.issues.create(1, "inference_stalled")
    d.issues.update(iid, status="acting")                     # 重啟前處理到一半，handler task 已消失
    eid = d.issues.esc_create(iid, "operator", "assist", "stale", {})
    fresh = Agent(d)                                          # 模擬重啟：新的 Agent、空的 tasks
    emit(d, 1, fps=0.0, det=0.0)
    assert await fresh.tick() == []                           # 修復前：該車道被孤兒 issue 擋住，永遠不再偵測
    fresh.recover()
    row = d.issues.get(iid)
    assert row["status"] == "interrupted" and row["closed"] and row["resolved_by"] == "restart"
    assert d.issues.esc_get(eid)["status"] == "expired"        # 殘留的待處理單一併失效
    [t] = await fresh.tick()                                   # 問題仍在 → 重新偵測並處理
    await t
    assert d.issues.list(1)[0]["status"] == "resolved" and d.issues.list(1)[0]["id"] != iid


async def test_waiting_issue_resumes_waiting_after_restart(d, agent):
    d.edge.camera_down.add(1)
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)
    d.s = type(d.s)(**{**d.s.__dict__, "operator_timeout": 30.0})
    [t] = await agent.tick()
    await until(lambda: pending(d, "operator"))
    op = pending(d, "operator")[0]
    t.cancel()                                                # 模擬重啟：舊 task 消失，升級單還在
    fresh = Agent(d)
    [r] = fresh.recover()
    assert d.issues.get(op["issue_id"])["closed"] is None     # 沒有被誤結案
    d.issues.esc_respond(op["id"], "cannot")                  # Operator 在重啟後才回覆
    await until(lambda: pending(d, "engineer"))               # 接續流程：升級遠端工程師
    d.issues.esc_respond(pending(d, "engineer")[0]["id"], "fixed")
    await asyncio.wait_for(r, 10)
    assert d.issues.get(op["issue_id"])["resolved_by"] == "engineer"


async def test_double_failure_in_handler_closes_issue_as_failed(d, agent):
    async def boom(*a, **k):
        raise RuntimeError("x")
    iid = d.issues.create(2, "inference_stalled")
    agent._handle = agent._engineer = boom
    await agent.handle(iid)                                    # 不可向外拋出
    row = d.issues.get(iid)
    assert row["status"] == "failed" and row["closed"] and agent.last_close[2] > 0


async def test_finished_tasks_are_removed(d, agent):
    emit(d, 1, fps=0.0, det=0.0)
    [t] = await agent.tick()
    assert agent.tasks
    await t
    await asyncio.sleep(0)
    assert agent.tasks == {}


# ---------- #2 rollback 證據由程式碼驗證 ----------
async def bad_change(d):
    await execute(d, "apply_config", {"patch": {"lanes": {"1": {"roi": [120, 200, 60, 40]}}}, "reason": "x"},
                  Call(actor="engineer", origin="external"))
    return d.versions.head()


async def test_llm_cannot_self_certify_rollback_evidence(d):
    head = await bad_change(d)
    # 修復前：LLM 在參數裡填 evidence="x" 就會被自動 rollback
    r = await execute(d, "rollback_version", {"to_seq": head["parent_seq"], "evidence": "x"}, Call(origin="agent"))
    assert r["blocked"] == "invalid_args"                      # evidence 已不是參數
    r = await execute(d, "rollback_version", {"to_seq": head["parent_seq"]}, Call(origin="agent"))
    assert r["blocked"] == "needs_operator" and d.versions.head()["seq"] == head["seq"]


async def test_code_computed_evidence_allows_rollback_only_for_matching_versions(d):
    head = await bad_change(d)
    ok_ev = {"seq": head["seq"], "parent_seq": head["parent_seq"]}
    r = await execute(d, "rollback_version", {"to_seq": head["parent_seq"] - 1}, Call(origin="agent", evidence=ok_ev))
    assert r["blocked"] == "needs_operator"                    # 證據對應的不是這個目標版本
    r = await execute(d, "rollback_version", {"to_seq": head["parent_seq"]},
                      Call(origin="agent", evidence={**ok_ev, "seq": head["seq"] - 1}))
    assert r["blocked"] == "needs_operator"                    # 證據是針對別的 head
    r = await execute(d, "rollback_version", {"to_seq": head["parent_seq"]}, Call(origin="agent", evidence=ok_ev))
    assert r["ok"] and d.versions.head()["seq"] == head["seq"] + 1


# ---------- #5 來源旗標 ----------
async def test_origin_flags_are_enforced(d):
    assert (await execute(d, "propose_rollback", {}, Call(origin="agent")))["blocked"] == "origin_not_allowed"
    assert (await execute(d, "restart_pipeline", {"lane": 1}, Call(origin="chat", actor="operator")))["blocked"] == "origin_not_allowed"
    assert d.edge.calls == []
    assert (await execute(d, "restart_pipeline", {"lane": 1}, Call(origin="agent")))["ok"]        # plannable
    assert (await execute(d, "query_logs", {"lane": 1}, Call(origin="chat", actor="operator")))["ok"]   # chat
    assert (await execute(d, "get_status", {}, Call()))["ok"]                                     # system（預設）不受限
    assert (await execute(d, "propose_rollback", {}, Call(origin="ui", actor="operator")))["ok"]   # UI 可用


# ---------- #6 config 推送失敗 ----------
async def test_push_failure_is_reported_and_retried(d, agent):
    async def fail(cfg):
        return {"ok": False, "msg": "sim unreachable"}
    ok_push = d.edge.push_config
    d.edge.push_config = fail
    n = d.versions.head()["seq"]
    r = await execute(d, "apply_config", {"patch": {"lanes": {"1": {"fps_threshold": 11}}}, "reason": "x"}, Call(actor="operator"))
    assert r["ok"] is False and "尚未生效" in r["summary"]
    assert d.versions.head()["seq"] == n + 1 and d.config_synced is False       # 版本保留（append-only），並標記未同步
    await agent.sync_config()
    assert d.config_synced is False                                              # edge 仍失敗 → 繼續重試
    d.edge.push_config = ok_push
    await agent.sync_config()
    assert d.config_synced is True


async def test_rollback_with_push_failure_escalates_instead_of_claiming_success(d, agent):
    await bad_change(d)
    async def fail(cfg):
        emit(d, 1, det=0.3)
        return {"ok": False, "msg": "sim unreachable"}
    d.edge.push_config = fail
    [t] = await agent.tick()
    await until(lambda: pending(d, "operator"))
    i = d.issues.list(1)[0]
    assert i["status"] == "waiting_operator" and i["resolved_by"] is None
    t.cancel()
    assert time.time() > 0
