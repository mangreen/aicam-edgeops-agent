"""POC 模擬器（sim/app.py）的行為測試：故障注入、控制 API、設定對指標的影響。"""
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SIM = Path(__file__).resolve().parent.parent / "sim" / "app.py"


@pytest.fixture
def sim():
    spec = importlib.util.spec_from_file_location("sim_app", SIM)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, TestClient(m.app)          # 不進入 lifespan：不啟動背景 loop


def last(m, lane, name):
    return [x["value"] for x in m.S["buf"]["metrics"] if x["lane"] == lane and x["name"] == name][-1]


def test_healthy_baseline(sim):
    m, _ = sim
    m.tick_once()
    assert last(m, 1, "fps") > 14 and last(m, 1, "stream_connected") == 1 and last(m, 1, "detections_per_min") >= 10


def test_inference_stalled_and_restart(sim):
    m, c = sim
    assert c.post("/fault/inference_stalled?lane=1").json()["ok"]
    m.tick_once()
    assert last(m, 1, "fps") == 0 and last(m, 1, "stream_connected") == 1 and last(m, 2, "fps") > 0   # 只影響該車道
    assert c.post("/control/restart_pipeline?lane=1").json()["ok"]
    m.tick_once()
    assert last(m, 1, "fps") > 0


def test_camera_down_reconnect_fails_until_physical_fix(sim):
    m, c = sim
    c.post("/fault/camera_no_signal?lane=1")
    m.tick_once()
    assert last(m, 1, "stream_connected") == 0
    assert c.post("/control/reconnect_stream?lane=1").json()["ok"] is False
    assert c.post("/control/restart_pipeline?lane=1").json()["ok"]        # 重啟 pipeline 修不好實體問題
    m.tick_once()
    assert last(m, 1, "stream_connected") == 0
    c.post("/control/physical_fix?lane=1")
    m.tick_once()
    assert last(m, 1, "stream_connected") == 1 and last(m, 1, "fps") > 0


def test_bad_roi_config_drops_detections(sim):
    m, c = sim
    cfg = {**m.DEFAULT_CFG, "lanes": {**m.DEFAULT_CFG["lanes"], "1": {**m.DEFAULT_CFG["lanes"]["1"], "roi": [120, 200, 60, 40]}}}
    assert c.put("/control/config", json=cfg).json()["ok"]
    m.tick_once()
    assert last(m, 1, "detections_per_min") < 4 and last(m, 1, "fps") > 0 and last(m, 2, "detections_per_min") > 10


def test_error_cases_and_reset(sim):
    m, c = sim
    assert c.post("/fault/nope").status_code == 400
    assert c.post("/fault/inference_stalled?lane=9").status_code == 404
    c.post("/fault/camera_no_signal?lane=2")
    c.post("/control/reset")
    assert all(st["camera"] and st["pipeline"] for st in m.S["lanes"].values())


def test_spans_mark_the_failing_stage(sim):
    m, c = sim
    c.post("/fault/camera_no_signal?lane=1")
    m.tick_once()
    errs = [x for x in m.S["buf"]["spans"] if x["lane"] == 1 and x["status"] == "error"]
    assert errs and errs[0]["name"] == "capture"


def test_reconnect_message_reports_actual_attempt_count(sim):
    m, c = sim
    c.post("/fault/camera_no_signal?lane=1")
    msgs = [c.post("/control/reconnect_stream?lane=1").json()["msg"] for _ in range(3)]
    assert msgs == ["no signal after 1 reconnect attempt", "no signal after 2 reconnect attempts",
                    "no signal after 3 reconnect attempts"]                                        # 實際次數，含單複數
    assert any("after 2 reconnect attempts" in x["msg"] for x in m.S["buf"]["logs"])


def test_attempt_count_resets_on_new_fault_physical_fix_and_reset(sim):
    m, c = sim
    c.post("/fault/camera_no_signal?lane=1")
    c.post("/control/reconnect_stream?lane=1")
    c.post("/fault/camera_no_signal?lane=1")                                                       # 重新注入故障 → 重新計數
    assert c.post("/control/reconnect_stream?lane=1").json()["msg"] == "no signal after 1 reconnect attempt"
    c.post("/control/physical_fix?lane=1")
    assert m.S["lanes"][1]["reconnects"] == 0
    c.post("/fault/camera_no_signal?lane=1")
    c.post("/control/reconnect_stream?lane=1")
    c.post("/control/reset")
    assert all(st["reconnects"] == 0 for st in m.S["lanes"].values())


def test_only_failed_reconnects_on_the_faulty_lane_are_counted(sim):
    m, c = sim
    c.post("/fault/camera_no_signal?lane=1")
    assert c.post("/control/reconnect_stream?lane=2").json()["ok"] is True                        # 健康車道：成功，不計數
    c.post("/control/restart_pipeline?lane=1")                                                      # 重啟 pipeline 不是 reconnect
    assert m.S["lanes"][1]["reconnects"] == 0 and m.S["lanes"][2]["reconnects"] == 0


async def test_agent_attempts_match_what_the_sim_reports(d, agent):
    """端到端：timeline 上每次 reconnect 失敗的訊息次數，等於 Agent 實際嘗試的次數（max_attempts）。"""
    import asyncio
    from dataclasses import replace

    from conftest import emit
    d.s = replace(d.s, max_attempts=2)
    counts = {"n": 0}

    async def reconnect(lane):
        counts["n"] += 1
        n = counts["n"]
        return {"ok": False, "msg": f"no signal after {n} reconnect attempt{'' if n == 1 else 's'}"}
    d.edge.reconnect_stream = reconnect
    emit(d, 1, fps=0.0, conn=0.0, det=0.0)
    [t] = await agent.tick()
    for _ in range(100):
        if d.issues.esc_pending():
            break
        await asyncio.sleep(0.05)
    iid = d.issues.list(1)[0]["id"]
    texts = [e["text"] for e in d.issues.events(issue_id=iid) if "reconnect_stream" in e["text"] and "FAIL" in e["text"]]
    assert len(texts) == 2 and "after 1 reconnect attempt" in texts[0] and "after 2 reconnect attempts" in texts[1]
    t.cancel()
