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
