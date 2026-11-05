"""FastAPI app factory 與 composition root。"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from aicam.adapters.edge import SimClient
from aicam.adapters.llm import make_llm
from aicam.config import load_settings
from aicam.core.loop import Agent
from aicam.poc import seed
from aicam.runtime import build

from .routes import router

UI_DIR = Path(__file__).resolve().parents[3] / "ui"


async def _push_config_retry(rt):
    """sim 可能比 agent 晚啟動：重試推送目前設定版本。"""
    for _ in range(60):
        if (await rt.edge.push_config(rt.versions.head()["content"])).get("ok"):
            return
        await asyncio.sleep(2)


def create_app(rt=None, agent=None, background: bool = True) -> FastAPI:
    """測試可注入 rt／agent 並關閉背景工作；正式啟動由 lifespan 組裝。"""
    @asynccontextmanager
    async def lifespan(app):
        if app.state.rt is None:
            s = load_settings()
            app.state.rt = build(s, edge=SimClient(s.sim_url))
            app.state.rt.attach_llm(make_llm(lambda m: app.state.rt.issues.event(None, "llm", m)))
            seed.run(app.state.rt)
            app.state.agent = Agent(app.state.rt)
        if app.state.agent is not None and background:
            app.state.agent.recover()           # 重啟後接回／結案處理到一半的 issue
        tasks = []
        if background:
            tasks = [asyncio.create_task(app.state.agent.run_forever()),
                     asyncio.create_task(_push_config_retry(app.state.rt))]
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="aicam-edgeops-agent", lifespan=lifespan)
    app.state.rt, app.state.agent, app.state.ui_dir = rt, agent, UI_DIR
    app.include_router(router)
    return app


app = create_app()
