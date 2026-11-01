"""HTTP 路由。依賴由 app factory 放進 app.state（rt、agent），不使用全域變數。"""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from aicam.core import chat
from aicam.core.executor import Call, execute
from aicam.plugins.registry import ConfigError

from .schemas import ChatBody, IngestBody, RespondBody, RollbackBody, ToggleBody

router = APIRouter()


def rt(request: Request):
    return request.app.state.rt


def feature(name: str):
    """功能開關依賴：設定檔 [features] 關閉時回 403（取代 RBAC；POC 使用者固定為 Operator）。"""
    def dep(request: Request):
        if not rt(request).s.feature(name):
            raise HTTPException(403, f"feature disabled: {name}")
    return Depends(dep)


@router.get("/")
def index(request: Request):
    return FileResponse(request.app.state.ui_dir / "index.html")


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/ingest")
def ingest(body: IngestBody, request: Request):
    rt(request).obs.ingest([x.model_dump() for x in body.logs], [x.model_dump() for x in body.metrics],
                           [x.model_dump() for x in body.spans])
    return {"ok": True}


@router.get("/api/status")
async def status(request: Request):
    d = rt(request)
    r = await execute(d, "get_status")
    return {"lanes": r["lanes"], "head": d.versions.head()["seq"], "llm": d.llm.name,
            "open_issues": d.issues.list(5, open_only=True), "tools": len(d.tools)}


@router.get("/api/tools")
def tool_list(request: Request):
    return rt(request).tools.mcp_tools()


@router.get("/api/events")
def events(request: Request, after: int = 0, limit: int = 100):
    rows = rt(request).issues.events(after, 100000)
    return rows[-limit:] if not after else rows[:limit]


@router.get("/api/stream")
async def stream(request: Request, after: int = 0):
    d = rt(request)

    async def gen():
        last = after
        while True:
            for e in d.issues.events(last, 100):
                last = e["id"]
                yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
            yield ": ping\n\n"
            await asyncio.sleep(0.6)
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/api/issues")
def issues(request: Request):
    return rt(request).issues.list(30)


@router.get("/api/issues/{iid}")
def issue(iid: int, request: Request):
    d = rt(request)
    i = d.issues.get(iid)
    if not i:
        raise HTTPException(404)
    return {**i, "events": d.issues.events(issue_id=iid), "actions": d.issues.actions(iid)}


@router.get("/api/escalations")
def escalations(request: Request):
    rows = rt(request).issues.esc_pending()
    for r in rows:
        r["payload"] = json.loads(r["payload"] or "{}")
    return rows


async def _post_verify(request: Request):
    d, agent = rt(request), request.app.state.agent
    since = time.time()
    await asyncio.sleep(d.s.verify_wait)
    ok = all(agent.healthy(ln, since) for ln in d.s.lanes)
    d.issues.event(None, "verify", f"rollback 後 Verify：{'恢復正常 ✔' if ok else '仍異常 ✘，請檢視'}")


@router.post("/api/escalations/{eid}/respond")
async def respond(eid: int, body: RespondBody, request: Request):
    d = rt(request)
    e = d.issues.esc_get(eid)
    if not e or e["status"] != "pending":
        raise HTTPException(409, "not pending")
    d.issues.esc_respond(eid, body.response)
    if e["kind"] != "confirm_rollback":
        return {"ok": True}
    if body.response != "confirm":
        d.issues.event(e["issue_id"], "operator", f"Operator 取消 rollback（#{eid}）")
        return {"ok": True}
    to = json.loads(e["payload"])["to_seq"]
    d.issues.event(e["issue_id"], "operator", f"Operator 確認 rollback 到 v{to}（#{eid}）")
    r = await execute(d, "rollback_version", {"to_seq": to}, Call(origin="ui", actor="operator", approved=True))
    asyncio.create_task(_post_verify(request))
    return r


@router.get("/api/versions")
def versions(request: Request):
    return rt(request).versions.list(30)


@router.get("/api/versions/diff")
async def vdiff(request: Request, a: int | None = None, b: int | None = None):
    return await execute(rt(request), "diff_versions", {"a": a, "b": b} if a and b else {})


@router.post("/api/versions/rollback")
async def ui_rollback(body: RollbackBody, request: Request):
    return await execute(rt(request), "propose_rollback", {"to_seq": body.to_seq},
                               Call(origin="ui", actor="operator"))


@router.post("/api/chat", dependencies=[feature("chat")])
async def chat_(body: ChatBody, request: Request):
    return await chat.handle(rt(request), body.text)


@router.get("/api/chat/history")
def chat_hist(request: Request):
    return rt(request).issues.msgs("default", 30)


@router.get("/api/outbox")
def outbox(request: Request):
    return rt(request).db.q("SELECT * FROM outbox ORDER BY id DESC LIMIT 20")


@router.post("/api/demo/fault/{name}", dependencies=[feature("demo_controls")])
async def fault(name: str, request: Request, lane: int = 1):
    d = rt(request)
    if name == "bad_config":   # 情境 E：工程師誤改 ROI，仍走 apply_config（自動快照）
        return await execute(d, "apply_config", {"patch": {"lanes": {str(lane): {"roi": [120, 200, 60, 40]}}},
                                   "reason": f"調整 Lane {lane} ROI（誤設）"}, Call(actor="engineer", origin="external"))
    return await d.edge.fault(name, lane)


@router.post("/api/demo/reset", dependencies=[feature("demo_controls")])
async def reset(request: Request):
    from aicam.poc import seed
    d, agent = rt(request), request.app.state.agent
    agent.cancel_all()
    d.db.wipe()
    seed.run(d, force=True)
    await d.edge.reset()
    await d.edge.push_config(d.versions.head()["content"])
    return {"ok": True}


@router.get("/api/features")
def features(request: Request):
    from aicam.config import FEATURE_DEFAULTS
    return {k: rt(request).s.feature(k) for k in FEATURE_DEFAULTS}


@router.get("/api/capabilities")
def capabilities(request: Request):
    d = rt(request)
    return {"tools": d.tools.describe(), "config_path": d.s.config_path,
            "skills": [{"name": k.name, "description": k.description, "tools": list(k.tools), "enabled": k.enabled,
                        "active": k.active, "reason": k.reason} for k in d.skills],
            "knowledge_sources": d.s.section("knowledge").get("sources", "all")}


@router.post("/api/admin/reload", dependencies=[feature("admin_reload")])
def reload_config(request: Request):
    d = rt(request)
    try:
        d.reload()
    except (ConfigError, OSError, ValueError) as e:
        raise HTTPException(400, f"設定載入失敗，維持原設定：{e}") from e
    d.issues.event(None, "config", "已重新載入設定檔（runtime override 已清除）")
    return {"ok": True, "tools": len(d.tools)}


@router.put("/api/admin/tools/{name}", dependencies=[feature("tool_toggle")])
def toggle_tool(name: str, body: ToggleBody, request: Request):
    d = rt(request)
    if name not in d.tools.specs:
        raise HTTPException(404, "unknown tool")
    d.overrides[name] = body.enabled
    d.rebuild_plugins()
    d.issues.event(None, "config", f"工具 {name} 於執行期{'啟用' if body.enabled else '停用'}（runtime override）")
    return {"ok": True}
