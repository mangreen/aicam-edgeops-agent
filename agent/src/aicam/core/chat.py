"""對話查詢：input guard → 規劃 → 工具（經 executor / policy）→ 回答 → output guard。"""
import json

from aicam.core.executor import Call, execute
from aicam.core.untrusted import wrap


def _gctx(d, scope="chat"):
    return {"system_prompt": d.prompts.compose(scope), "canary": d.prompts.canary}


async def handle(d, text, session="default"):
    gctx = _gctx(d)
    inp = d.guards.run("input", text, gctx)
    if inp.blocked:
        return {"answer": inp.text, "tools": [], "llm": d.llm.name, "blocked": True, "stage": "input"}
    text = inp.text
    hist = d.issues.msgs(session, 10)
    allowed = d.tools.names(chat=True)          # 只有 manifest 標示可對話呼叫且已啟用的工具
    try:
        calls = await d.llm.chat_plan(text, hist, allowed)
    except Exception:
        calls = await d.llm.mock.chat_plan(text, hist, allowed)
    results, used = [], []
    for c in calls[:3]:
        if c["tool"] not in allowed:
            continue
        r = await execute(d, c["tool"], c.get("args") or {}, Call(origin="chat", actor="operator"))
        summary = r.get("summary", "")
        g = d.guards.run("content", summary, {})            # log 等外部內容可能夾帶指令
        results.append({"tool": c["tool"], "ok": r.get("ok"), "summary": wrap(c["tool"], g.text) if g.flagged else g.text})
        used.append(f"{c['tool']}({json.dumps(c.get('args') or {}, ensure_ascii=False)})")
    try:
        ans = await d.llm.chat_answer(text, results)
    except Exception:
        ans = await d.llm.mock.chat_answer(text, results)
    out = d.guards.run("output", ans, gctx)
    d.issues.msg_add("user", text, session)       # 查詢完才寫入，避免搜到自己
    d.issues.msg_add("assistant", out.text, session)
    return {"answer": out.text, "tools": used, "llm": d.llm.name, "blocked": out.blocked,
            "stage": "output" if out.action != "allow" else None, "redacted": out.action == "redact"}
