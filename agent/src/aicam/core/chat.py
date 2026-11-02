"""對話查詢：input guard → 規劃 → 工具（經 executor / policy）→ 回答 → output guard。

雲端 LLM 偶爾會給錯工具參數：executor 會先做安全的校正（改名、轉型）；仍無法通過驗證時，
對真 LLM 做一次「附錯誤訊息的重新規劃」，仍失敗就把失敗原因如實交給回答階段，不會無限重試。
"""
import json

from aicam.core.executor import Call, execute
from aicam.core.untrusted import wrap

MAX_CALLS = 3


def _gctx(d, scope="chat"):
    return {"system_prompt": d.prompts.compose(scope), "canary": d.prompts.canary}


async def _plan(d, text, hist, specs, feedback=None):
    kw = {"feedback": feedback} if feedback else {}
    try:
        return await d.llm.chat_plan(text, hist, specs, **kw)
    except Exception:
        return await d.llm.mock.chat_plan(text, hist, specs)


async def _run_calls(d, calls, allowed):
    results, used = [], []
    for c in calls[:MAX_CALLS]:
        if c.get("tool") not in allowed:
            continue
        args = c.get("args") or {}
        r = await execute(d, c["tool"], args, Call(origin="chat", actor="operator"))
        summary = r.get("summary", "")
        g = d.guards.run("content", summary, {})            # log 等外部內容可能夾帶指令
        results.append({"tool": c["tool"], "ok": r.get("ok"), "blocked": r.get("blocked"),
                        "summary": wrap(c["tool"], g.text) if g.flagged else g.text})
        used.append(f"{c['tool']}({json.dumps(args, ensure_ascii=False)})")
    return results, used


async def handle(d, text, session="default"):
    gctx = _gctx(d)
    inp = d.guards.run("input", text, gctx)
    if inp.blocked:
        return {"answer": inp.text, "tools": [], "llm": d.llm.name, "blocked": True, "stage": "input"}
    text = inp.text
    hist = d.issues.msgs(session, 10)
    allowed = d.tools.names(chat=True)          # 只有 manifest 標示可對話呼叫且已啟用的工具
    specs = [t for t in d.tools.mcp_tools() if t["name"] in allowed]
    results, used = await _run_calls(d, await _plan(d, text, hist, specs), allowed)
    bad = [r for r in results if r["blocked"] == "invalid_args"]
    if bad and d.llm.info().get("real"):        # 真 LLM：附上錯誤再規劃一次（只一次）
        fb = "；".join(f"{r['tool']}：{r['summary']}" for r in bad)
        r2, u2 = await _run_calls(d, await _plan(d, text, hist, specs, fb), allowed)
        results = [r for r in results if r["blocked"] != "invalid_args"] + r2
        used += u2
    for r in results:
        r.pop("blocked", None)
    try:
        ans = await d.llm.chat_answer(text, results)
    except Exception:
        ans = await d.llm.mock.chat_answer(text, results)
    out = d.guards.run("output", ans, gctx)
    d.issues.msg_add("user", text, session)       # 查詢完才寫入，避免搜到自己
    d.issues.msg_add("assistant", out.text, session)
    return {"answer": out.text, "tools": used, "llm": d.llm.name, "blocked": out.blocked,
            "stage": "output" if out.action != "allow" else None, "redacted": out.action == "redact"}
