import asyncio, json, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from aicam.adapters.edge import SimClient
from aicam.adapters.llm import make_llm
from aicam.core import chat
from aicam.core.loop import Agent
from aicam.plugins import tools
from aicam.plugins.tools import Call
from aicam.poc import seed
from aicam.runtime import Settings, build

UI = Path(__file__).resolve().parents[3] / "ui"
d = Agent_ = None


async def push_config_retry():
    for _ in range(60):
        r = await d.sim.push_config(d.versions.head()["content"])
        if r.get("ok"):
            return
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app):
    global d, Agent_
    d = build(Settings())
    d.sim = SimClient(d.s.sim_url)
    d.llm = make_llm(lambda m: d.issues.event(None, "llm", m))
    seed.run(d)
    Agent_ = Agent(d)
    bg = [asyncio.create_task(Agent_.run_forever()), asyncio.create_task(push_config_retry())]
    yield
    for t in bg: t.cancel()


app = FastAPI(title="aicam-edgeopt-agent", lifespan=lifespan)


@app.get("/")
def index(): return FileResponse(UI / "index.html")


@app.get("/health")
def health(): return {"ok": True}


@app.post("/ingest")
async def ingest(req: Request):
    b = await req.json()
    d.obs.ingest(b.get("logs", []), b.get("metrics", []), b.get("spans", []))
    return {"ok": True}


@app.get("/api/status")
async def status():
    r = await tools.execute(d, "get_status")
    h = d.versions.head()
    return {"lanes": r["lanes"], "head": h["seq"], "llm": d.llm.name,
            "open_issues": d.issues.list(5, open_only=True), "tools": len(tools.REG)}


@app.get("/api/tools")
def tool_list(): return tools.mcp_tools()


@app.get("/api/events")
def events(after: int = 0, limit: int = 100):
    rows = d.issues.events(after, 100000)
    return rows[-limit:] if not after else rows[:limit]


@app.get("/api/stream")
async def stream(after: int = 0):
    async def gen():
        last = after
        while True:
            for e in d.issues.events(last, 100):
                last = e["id"]
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            yield ": ping\n\n"
            await asyncio.sleep(0.6)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/issues")
def issues(): return d.issues.list(30)


@app.get("/api/issues/{iid}")
def issue(iid: int):
    i = d.issues.get(iid)
    if not i: raise HTTPException(404)
    return {**i, "events": d.issues.events(issue_id=iid), "actions": d.issues.actions(iid)}


@app.get("/api/escalations")
def escalations():
    rows = d.issues.esc_pending()
    for r in rows: r["payload"] = json.loads(r["payload"] or "{}")
    return rows


@app.post("/api/escalations/{eid}/respond")
async def respond(eid: int, body: dict):
    e, resp = d.issues.esc_get(eid), body.get("response")
    if not e or e["status"] != "pending": raise HTTPException(409, "not pending")
    if e["kind"] == "confirm_rollback":
        d.issues.esc_respond(eid, resp)
        if resp != "confirm":
            d.issues.event(e["issue_id"], "operator", f"Operator 取消 rollback（#{eid}）")
            return {"ok": True}
        to = json.loads(e["payload"])["to_seq"]
        d.issues.event(e["issue_id"], "operator", f"Operator 確認 rollback 到 v{to}（#{eid}）")
        r = await tools.execute(d, "rollback_version", {"to_seq": to}, Call(origin="ui", actor="operator", approved=True))
        asyncio.create_task(post_verify())
        return r
    d.issues.esc_respond(eid, resp)
    return {"ok": True}


async def post_verify():
    since = time.time()
    await asyncio.sleep(d.s.verify_wait)
    ok = all(Agent_.healthy(ln, since) for ln in d.s.lanes)
    d.issues.event(None, "verify", f"rollback 後 Verify：{'恢復正常 ✔' if ok else '仍異常 ✘，請檢視'}")


@app.get("/api/versions")
def versions(): return [{k: v for k, v in x.items() if k != "content"} | {"content": x["content"]} for x in d.versions.list(30)]


@app.get("/api/versions/diff")
async def vdiff(a: int | None = None, b: int | None = None):
    return await tools.execute(d, "diff_versions", {"a": a, "b": b} if a and b else {})


@app.post("/api/versions/rollback")
async def ui_rollback(body: dict):
    return await tools.execute(d, "propose_rollback", {"to_seq": body.get("to_seq")}, Call(origin="ui", actor="operator"))


@app.post("/api/chat")
async def chat_(body: dict): return await chat.handle(d, body["text"])


@app.get("/api/chat/history")
def chat_hist(): return d.issues.msgs("default", 30)


@app.get("/api/outbox")
def outbox(): return d.db.q("SELECT * FROM outbox ORDER BY id DESC LIMIT 20")


@app.post("/api/demo/fault/{name}")
async def fault(name: str, lane: int = 1):
    if name == "bad_config":   # 情境 E：工程師誤改 ROI，仍走 apply_config（自動快照）
        return await tools.execute(d, "apply_config", {"patch": {"lanes": {str(lane): {"roi": [120, 200, 60, 40]}}},
                                   "reason": f"調整 Lane {lane} ROI（誤設）"}, Call(actor="engineer", origin="external"))
    return await d.sim.fault(name, lane)


@app.post("/api/demo/reset")
async def reset():
    Agent_.cancel_all()
    d.db.wipe()
    seed.run(d, force=True)
    await d.sim.reset()
    await d.sim.push_config(d.versions.head()["content"])
    return {"ok": True}
