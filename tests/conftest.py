import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent" / "src"))
from dataclasses import replace

from aicam.adapters.llm import AutoLLM
from aicam.config import load_settings
from aicam.core.loop import Agent
from aicam.poc import seed
from aicam.runtime import build


def emit(d, lane, fps=15.0, conn=1.0, det=14.0, n=3):
    t = time.time()
    d.obs.ingest([], [{"ts": t + i * 1e-6, "lane": lane, "name": k, "value": v} for i in range(n)
                      for k, v in (("fps", fps), ("stream_connected", conn), ("detections_per_min", det))], [])


class FakeSim:
    """測試用假邊緣端：動作成功後寫入健康 metrics。camera 需 physical_fix 才恢復。"""
    def __init__(self): self.d, self.camera_down, self.calls = None, set(), []

    async def restart_pipeline(self, lane):
        self.calls.append(("restart", lane)); emit(self.d, lane); return {"ok": True, "msg": "restarted"}

    async def reconnect_stream(self, lane):
        self.calls.append(("reconnect", lane))
        if lane in self.camera_down: return {"ok": False, "msg": "no signal"}
        emit(self.d, lane); return {"ok": True, "msg": "ok"}

    async def physical_fix(self, lane):
        self.camera_down.discard(lane); emit(self.d, lane); return {"ok": True}

    async def fault(self, name, lane=1):
        self.calls.append(("fault", name, lane)); return {"ok": True}

    async def reset(self):
        self.camera_down.clear(); return {"ok": True}

    async def push_config(self, cfg):
        for ln, c in cfg["lanes"].items():
            emit(self.d, int(ln), det=0.3 if c["roi"][2] * c["roi"][3] < 10000 else 14.0)
        return {"ok": True}


@pytest.fixture
def d():
    cfg = Path(__file__).resolve().parent.parent / "config" / "agent.toml"      # 與 demo 相同的真實設定
    dd = build(replace(load_settings(str(cfg), env={"DB_PATH": ":memory:"}), verify_wait=0.05, operator_timeout=1.0))
    dd.edge = FakeSim()
    dd.attach_llm(AutoLLM(None))
    dd.edge.d = dd
    seed.run(dd)
    dd.agent = Agent(dd)
    return dd


@pytest.fixture
def client(d):
    """HTTP 層測試：不啟動背景 loop，直接用 TestClient 呼叫 API。"""
    from fastapi.testclient import TestClient

    from aicam.api.app import create_app
    from aicam.core.loop import Agent
    return TestClient(create_app(rt=d, agent=Agent(d), background=False))


@pytest.fixture
def agent(d):
    from aicam.core.loop import Agent
    return Agent(d)
