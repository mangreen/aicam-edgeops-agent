"""內建工具：runbook、歷史 issue、歷史對話檢索（L0 唯讀）。"""

from aicam.core.executor import Call  # noqa: F401
from aicam.plugins.registry import Toolbox

from ._util import _ago, _int, _str

box = Toolbox()


@box.tool("search_knowledge", "搜尋 runbook / 知識庫", {"query": _str("關鍵字")}, ("query",), level="L0", chat=True)
async def search_knowledge(d, c, query):
    rows = d.kb.search(query, kinds=d.s.section("knowledge").get("sources"))
    return {"rows": rows, "summary": "；".join(f"《{r['title']}》{r['sn']}" for r in rows) or "知識庫無相關內容"}


@box.tool("search_issues", "搜尋歷史 issue", {"kind": _str("inference_stalled|camera_no_signal|detection_drop"), "lane": _int("車道")}, level="L0", chat=True)
async def search_issues(d, c, kind=None, lane=None):
    rows = [r for r in d.issues.list(5, kind, lane) if r["closed"]]
    return {"rows": rows, "summary": "；".join(
        f"#{r['id']} {_ago(r['created'])} Lane {r['lane']} {r['kind']} → {r['summary']}" for r in rows) or "無歷史 issue"}


@box.tool("search_history", "搜尋歷史對話（query 可省略：列出最近的對話；搜不到時也會列出最近的對話）", {"query": _str("關鍵字，可省略")}, (), level="L0", chat=True)
async def search_history(d, c, query=None):
    q = (query or "").strip()
    rows, note = (d.issues.msg_search(q) if q else []), ""
    if not rows:
        rows = d.issues.msg_recent()
        note = f"沒有符合「{q}」的對話，以下是最近的對話：" if q else "最近的對話："
    return {"rows": rows, "summary": (note + "；".join(f"[{_ago(r['ts'])}] 問：{r['q'][:40]} 答：{(r['a'] or '')[:70]}" for r in rows))
            if rows else "目前沒有歷史對話"}


TOOLS = box.tools
