import time
from dataclasses import replace

from aicam.adapters.llm import AutoLLM, CloudLLM, factory
from aicam.core.executor import Call, execute
from aicam.poc import seed
from conftest import emit


def test_classification_priority_and_no_stale_samples(d, agent):
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)                  # 攝影機斷線同時 FPS=0：以斷線為準
    assert agent.classify(1) == "camera_no_signal"
    emit(d, 2, fps=0.0, conn=1.0, det=0.0)
    assert agent.classify(2) == "inference_stalled"
    emit(d, 2, det=0.5)
    assert agent.classify(2) in ("detection_drop", "inference_stalled")
    agent.last_close[1] = time.time() + 1                    # 結案後，舊樣本不可再次觸發
    assert agent.classify(1) is None


def test_needs_enough_samples(d, agent):
    emit(d, 1, fps=0.0, det=0.0, n=2)                        # 只有 2 筆 < detect_samples(3)
    assert agent.classify(1) is None


async def test_one_open_issue_per_lane(d, agent):
    emit(d, 1, fps=0.0, det=0.0)
    first = await agent.tick()
    assert len(first) == 1
    assert await agent.tick() == []                          # 同一車道處理中不重複建立
    first[0].cancel()


async def test_rate_limit_end_to_end_escalates_to_operator(d, agent):
    """restart 持續無效時：第 2 次後被 Policy 擋下（不是無限重啟），並升級給 Operator。"""
    d.edge.restart_pipeline = lambda lane: _noop(d, lane)    # 重啟成功但指標沒恢復
    emit(d, 1, fps=0.0, det=0.0)
    [t] = await agent.tick()
    for _ in range(100):
        if d.issues.esc_pending():
            break
        await _sleep()
    assert d.issues.esc_pending()[0]["to_who"] == "operator"
    assert len([a for a in d.issues.actions(d.issues.list(1)[0]["id"]) if a["tool"] == "restart_pipeline"]) == 2
    t.cancel()


async def _noop(d, lane):
    return {"ok": True, "msg": "restarted but still broken"}


async def _sleep():
    import asyncio
    await asyncio.sleep(0.05)


async def test_rollback_verify_failure_is_not_repeated(d, agent):
    await execute(d, "apply_config", {"patch": {"lanes": {"1": {"roi": [120, 200, 60, 40]}}}, "reason": "bad"},
                  Call(actor="engineer", origin="external"))

    async def still_bad(cfg):                                # rollback 後指標仍然異常
        emit(d, 1, det=0.3)
        return {"ok": True}
    d.edge.push_config = still_bad
    [t] = await agent.tick()
    for _ in range(100):
        if d.issues.esc_pending():
            break
        await _sleep()
    acts = [a for a in d.issues.actions(d.issues.list(1)[0]["id"]) if a["tool"] == "rollback_version"]
    assert len(acts) == 1 and d.issues.esc_pending()[0]["to_who"] == "operator"
    t.cancel()


def test_seed_content_and_idempotent_force(d):
    assert d.versions.head()["seq"] == 6 and len(d.issues.list(50)) == 4 and len(d.issues.msgs("default", 50)) == 4
    assert {r["kind"] for r in d.db.q("SELECT kind FROM kb")} == {"runbook", "issue"}
    n = d.obs.count_logs(1, "stream disconnected")
    d.db.wipe()
    seed.run(d, force=True)
    assert d.obs.count_logs(1, "stream disconnected") == n == 5
    seed.run(d)                                               # 已有資料時不重複 seed
    assert d.versions.head()["seq"] == 6


def test_make_llm_selection(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    assert factory.make_llm().info()["provider"] == "mock"             # 沒有 key → Mock
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(factory, "_online", lambda host, **kw: False)
    assert factory.make_llm().info()["provider"] == "mock"             # 有 key 但離線 → Mock
    monkeypatch.setattr(factory, "_online", lambda host, **kw: True)
    assert factory.make_llm().info() | {} == {"provider": "openrouter", "model": "anthropic/claude-3.5-haiku",
                                             "real": True, "fallback_active": False}
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    assert factory.make_llm().info()["provider"] == "mock"             # 明確指定 mock


async def test_autollm_cooldown_after_failure():
    calls = []

    class Broken(CloudLLM):
        name, model = "broken", "x"

        async def _complete(self, s, u):
            calls.append(1)
            raise ConnectionError("offline")
    notes = []
    llm = AutoLLM(Broken(), on_fallback=notes.append)
    for _ in range(3):
        await llm.converse("hi")
    assert len(calls) == 1 and len(notes) == 1 and llm.info()["fallback_active"]   # 30 秒內不再重試雲端


def test_settings_defaults_are_safe():
    from aicam.config import Settings
    s = Settings()
    assert s.feature("chat") and not s.feature("prompt_edit") and not s.feature("demo_controls")
    assert replace(s, raw={"features": {"prompt_edit": True}}).feature("prompt_edit")
