import json
from aicam.core.constants import CHAT_TOOLS
from aicam.plugins.tools import Call, execute


async def handle(d, text, session="default"):
    hist = d.issues.msgs(session, 10)
    try:
        calls = await d.llm.chat_plan(text, hist)
    except Exception:
        calls = await d.llm.mock.chat_plan(text, hist)
    results, used = [], []
    for c in calls[:3]:
        if c["tool"] not in CHAT_TOOLS:
            continue
        r = await execute(d, c["tool"], c.get("args") or {}, Call(origin="chat", actor="operator"))
        results.append({"tool": c["tool"], **{k: v for k, v in r.items() if k in ("summary", "ok")}})
        used.append(f"{c['tool']}({json.dumps(c.get('args') or {}, ensure_ascii=False)})")
    try:
        ans = await d.llm.chat_answer(text, results)
    except Exception:
        ans = await d.llm.mock.chat_answer(text, results)
    d.issues.msg_add("user", text, session)       # 查詢完才寫入，避免搜到自己
    d.issues.msg_add("assistant", ans, session)
    return {"answer": ans, "tools": used, "llm": d.llm.name}
