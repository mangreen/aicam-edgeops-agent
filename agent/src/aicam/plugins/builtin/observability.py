"""內建工具：logs / metrics / traces / 狀態（L0 唯讀）。"""
import time

from aicam.core.executor import Call  # noqa: F401
from aicam.plugins.registry import Toolbox

from ._util import _ago, _int, _str

box = Toolbox()


@box.tool("get_status", "目前各車道狀態與設定版本", level="L0", chat=True)
async def get_status(d, c):
    out, lines = {}, []
    for ln in d.s.lanes:
        row = {}
        for n in ("fps", "stream_connected", "detections_per_min"):
            r = d.obs.metrics(ln, n, limit=1)
            row[n] = r[0]["value"] if r else None
        out[ln] = row
        lines.append(f"Lane {ln}: fps={row['fps']} 串流={'連線' if row['stream_connected'] else '中斷'} 偵測={row['detections_per_min']}/min")
    h = d.versions.head()
    return {"lanes": out, "summary": "；".join(lines) + f"；設定版本 v{h['seq'] if h else '-'}"}


@box.tool("query_logs", "查詢 logs", {"lane": _int("車道"), "contains": _str("關鍵字"), "since_hours": {"type": "number"}, "limit": _int("筆數")}, level="L0", chat=True)
async def query_logs(d, c, lane=None, contains=None, since_hours=1, limit=10):
    since = time.time() - float(since_hours) * 3600
    n = d.obs.count_logs(lane, contains, since)
    rows = d.obs.logs(lane, contains, since, limit)
    last = f"，最近一次 {_ago(rows[0]['ts'])}" if rows else ""
    where = f"Lane {lane} " if lane else ""
    return {"count": n, "rows": rows, "summary": f"{where}近 {since_hours:g} 小時符合「{contains or '全部'}」的 log 共 {n} 筆{last}"}


@box.tool("query_metrics", "查詢 metrics 統計", {"lane": _int("車道"), "name": _str("fps|stream_connected|detections_per_min"), "since_hours": {"type": "number"}}, ("lane",), level="L0", chat=True)
async def query_metrics(d, c, lane, name="fps", since_hours=1):
    rows = d.obs.metrics(lane, name, time.time() - float(since_hours) * 3600)
    if not rows:
        return {"summary": f"Lane {lane} 無 {name} 資料"}
    v = [r["value"] for r in rows]
    return {"avg": sum(v) / len(v), "min": min(v), "max": max(v), "n": len(v),
            "summary": f"Lane {lane} {name} 近 {since_hours:g} 小時：平均 {sum(v)/len(v):.1f}、最低 {min(v):.1f}、最高 {max(v):.1f}（{len(v)} 筆）"}


@box.tool("query_traces", "查詢 traces/spans", {"lane": _int("車道"), "status": _str("ok|error"), "since_hours": {"type": "number"}}, level="L0", chat=True)
async def query_traces(d, c, lane=None, status=None, since_hours=1):
    rows = d.obs.spans(lane, time.time() - float(since_hours) * 3600, status, 5)
    if not rows:
        return {"rows": [], "summary": "查無符合的 span"}
    top = "、".join(f"{r['name']}={r['dur_ms']:.0f}ms/{r['status']}" for r in rows[:3])
    return {"rows": rows, "summary": f"最近 {len(rows)} 筆 span（{status or '全部'}）：{top}"}


TOOLS = box.tools
