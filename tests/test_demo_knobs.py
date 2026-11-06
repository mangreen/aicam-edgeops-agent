"""可調校的 demo 速度旋鈕：max_attempts、只由 TOML 決定的時間設定、sim 重試次數、重啟摘要事件。"""
import asyncio
import importlib.util
from dataclasses import replace
from pathlib import Path

from aicam.adapters.llm import AutoLLM, MockLLM
from aicam.config import load_settings
from aicam.core.executor import Call, execute
from aicam.core.loop import Agent
from conftest import emit


async def until(cond, timeout=6):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


def operator_pending(d):
    return [e for e in d.issues.esc_pending() if e["to_who"] == "operator"]


async def run_camera_down(d, agent):
    d.edge.camera_down.add(1)
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)
    [t] = await agent.tick()
    await until(lambda: operator_pending(d))
    t.cancel()
    return [c for c in d.edge.calls if c[0] == "reconnect"]


async def test_max_attempts_1_escalates_after_one_try(d, agent):
    d.s = replace(d.s, max_attempts=1)
    assert len(await run_camera_down(d, agent)) == 1


async def test_default_is_two_attempts(d, agent):
    assert d.s.max_attempts == 2
    assert len(await run_camera_down(d, agent)) == 2


async def test_max_attempts_3_when_rate_limit_allows(d, agent):
    await execute(d, "apply_config", {"patch": {"policy": {"l1_max_per_10min": 3}}, "reason": "demo"},
                  Call(actor="engineer", origin="external"))              # 頻率限制也要放寬，否則 Policy 會先擋下第 3 次
    d.s = replace(d.s, max_attempts=3)
    assert len(await run_camera_down(d, agent)) == 3


class AlwaysRestart(MockLLM):
    """模擬一個永遠建議重啟的 LLM：上限必須由 loop 強制，而不是靠模型自己停。"""
    async def plan(self, ctx):
        return {"tool": "restart_pipeline", "args": {"lane": ctx["lane"]}, "rationale": "再試一次"}


async def test_cap_is_enforced_by_loop_not_by_llm(d, agent):
    d.attach_llm(AutoLLM(None, mock=AlwaysRestart()))
    async def noop(lane):
        return {"ok": True, "msg": "restarted but unchanged"}
    d.edge.restart_pipeline = noop
    await execute(d, "apply_config", {"patch": {"policy": {"l1_max_per_10min": 9}}, "reason": "x"}, Call(actor="engineer", origin="external"))
    d.s = replace(d.s, max_attempts=1)
    emit(d, 1, fps=0.0, det=0.0)
    [t] = await agent.tick()
    await until(lambda: operator_pending(d))
    iid = d.issues.list(1)[0]["id"]
    assert len([a for a in d.issues.actions(iid) if a["tool"] == "restart_pipeline"]) == 1
    assert any("已達自動修復嘗試上限" in e["text"] for e in d.issues.events(issue_id=iid))
    t.cancel()


def test_timing_keys_come_from_toml_only(tmp_path):
    f = tmp_path / "agent.toml"
    f.write_text("[runtime]\nverify_wait = 3\noperator_timeout = 11\nmax_attempts = 1\ndetect_samples = 2\n")
    s = load_settings(str(f), env={"VERIFY_WAIT": "99", "OPERATOR_TIMEOUT": "99", "DB_PATH": ":memory:"})
    assert (s.verify_wait, s.operator_timeout, s.max_attempts, s.detect_samples) == (3, 11, 1, 2)   # 殘留的環境變數不再蓋掉 TOML
    assert s.db_path == ":memory:"                                                                    # DB_PATH／SIM_URL 仍可由環境變數覆寫


def test_max_attempts_has_a_floor_of_one(tmp_path):
    f = tmp_path / "agent.toml"
    f.write_text("[runtime]\nmax_attempts = 0\n")
    assert load_settings(str(f), env={}).max_attempts == 1


def test_reload_applies_new_timing(d, tmp_path):
    f = tmp_path / "agent.toml"
    f.write_text("[runtime]\nverify_wait = 4.5\nmax_attempts = 1\n")
    d.s = replace(d.s, config_path=str(f))
    d.reload()
    assert d.s.verify_wait == 4.5 and d.s.max_attempts == 1


def test_sim_reconnect_retry_count_is_configurable(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SIM_RECONNECT_RETRIES", "5")
    spec = importlib.util.spec_from_file_location("sim_app5", Path(__file__).resolve().parent.parent / "sim" / "app.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    c = TestClient(m.app)
    c.post("/fault/camera_no_signal?lane=1")
    assert c.post("/control/reconnect_stream?lane=1").json()["msg"] == "no signal after 5 retries"


# ---------- 重啟 recover：使用者要看得到發生了什麼 ----------
async def test_recover_writes_summary_event_and_issue_stays_queryable(d):
    iid = d.issues.create(1, "inference_stalled")
    d.issues.update(iid, status="acting")
    Agent(d).recover()
    summary = [e for e in d.issues.events_latest(10) if e["type"] == "system"]
    assert summary and "中斷並結案處理到一半的 issue 1 個" in summary[-1]["text"] and summary[-1]["issue_id"] is None
    assert any("重啟" in e["text"] for e in d.issues.events(issue_id=iid))                 # 該 issue 自己的時間軸也有紀錄
    r = await execute(d, "search_issues", {"kind": "inference_stalled"}, Call())            # 對話查得到
    assert "重啟時處理中斷" in r["summary"]
    assert d.issues.get(iid)["status"] == "interrupted"


async def test_recover_is_silent_when_nothing_to_recover(d):
    Agent(d).recover()
    assert not [e for e in d.issues.events_latest(10) if e["type"] == "system"]
