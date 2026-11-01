"""Tool registry。schema 採 MCP 相容格式（name / description / inputSchema），日後可直接掛 MCP server。"""
import json, time, uuid
from dataclasses import dataclass
from aicam.core import policy, versions as V


@dataclass
class Call:
    issue_id: int | None = None
    actor: str = "agent"       # agent | operator | engineer
    origin: str = "agent"      # agent | chat | ui | external
    approved: bool = False


@dataclass
class Tool:
    name: str
    description: str
    props: dict
    required: tuple
    fn: object

    def mcp(self):
        return {"name": self.name, "description": self.description,
                "inputSchema": {"type": "object", "properties": self.props, "required": list(self.required)}}


REG: dict[str, Tool] = {}


def tool(name, desc, props=None, required=()):
    def deco(fn):
        REG[name] = Tool(name, desc, props or {}, tuple(required), fn)
        return fn
    return deco


def mcp_tools():
    return [t.mcp() for t in REG.values()]


def _ago(ts): return time.strftime("%m/%d %H:%M", time.localtime(ts))
def _int(v): return {"type": "integer", "description": v}
def _str(v): return {"type": "string", "description": v}


# ---------- L0 唯讀 ----------
@tool("get_status", "目前各車道狀態與設定版本")
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


@tool("query_logs", "查詢 logs", {"lane": _int("車道"), "contains": _str("關鍵字"), "since_hours": {"type": "number"}, "limit": _int("筆數")})
async def query_logs(d, c, lane=None, contains=None, since_hours=1, limit=10):
    since = time.time() - float(since_hours) * 3600
    n = d.obs.count_logs(lane, contains, since)
    rows = d.obs.logs(lane, contains, since, limit)
    last = f"，最近一次 {_ago(rows[0]['ts'])}" if rows else ""
    where = f"Lane {lane} " if lane else ""
    return {"count": n, "rows": rows, "summary": f"{where}近 {since_hours:g} 小時符合「{contains or '全部'}」的 log 共 {n} 筆{last}"}


@tool("query_metrics", "查詢 metrics 統計", {"lane": _int("車道"), "name": _str("fps|stream_connected|detections_per_min"), "since_hours": {"type": "number"}}, ("lane",))
async def query_metrics(d, c, lane, name="fps", since_hours=1):
    rows = d.obs.metrics(lane, name, time.time() - float(since_hours) * 3600)
    if not rows:
        return {"summary": f"Lane {lane} 無 {name} 資料"}
    v = [r["value"] for r in rows]
    return {"avg": sum(v) / len(v), "min": min(v), "max": max(v), "n": len(v),
            "summary": f"Lane {lane} {name} 近 {since_hours:g} 小時：平均 {sum(v)/len(v):.1f}、最低 {min(v):.1f}、最高 {max(v):.1f}（{len(v)} 筆）"}


@tool("query_traces", "查詢 traces/spans", {"lane": _int("車道"), "status": _str("ok|error"), "since_hours": {"type": "number"}})
async def query_traces(d, c, lane=None, status=None, since_hours=1):
    rows = d.obs.spans(lane, time.time() - float(since_hours) * 3600, status, 5)
    if not rows:
        return {"rows": [], "summary": "查無符合的 span"}
    top = "、".join(f"{r['name']}={r['dur_ms']:.0f}ms/{r['status']}" for r in rows[:3])
    return {"rows": rows, "summary": f"最近 {len(rows)} 筆 span（{status or '全部'}）：{top}"}


@tool("search_knowledge", "搜尋 runbook / 知識庫", {"query": _str("關鍵字")}, ("query",))
async def search_knowledge(d, c, query):
    rows = d.kb.search(query)
    return {"rows": rows, "summary": "；".join(f"《{r['title']}》{r['sn']}" for r in rows) or "知識庫無相關內容"}


@tool("search_issues", "搜尋歷史 issue", {"kind": _str("inference_stalled|camera_no_signal|detection_drop"), "lane": _int("車道")})
async def search_issues(d, c, kind=None, lane=None):
    rows = [r for r in d.issues.list(5, kind, lane) if r["closed"]]
    return {"rows": rows, "summary": "；".join(
        f"#{r['id']} {_ago(r['created'])} Lane {r['lane']} {r['kind']} → {r['summary']}" for r in rows) or "無歷史 issue"}


@tool("search_history", "搜尋歷史對話", {"query": _str("關鍵字")}, ("query",))
async def search_history(d, c, query):
    rows = d.issues.msg_search(query)
    return {"rows": rows, "summary": "；".join(f"[{_ago(r['ts'])} {r['role']}] {r['content'][:60]}" for r in rows) or "無相關歷史對話"}


@tool("list_versions", "列出設定版本", {"limit": _int("筆數")})
async def list_versions(d, c, limit=5):
    rows = d.versions.list(limit)
    return {"rows": rows, "summary": "；".join(f"v{r['seq']} {_ago(r['ts'])} {r['actor']}：{r['reason']}" for r in rows)}


@tool("get_version", "取得單一版本內容", {"seq": _int("版本號")}, ("seq",))
async def get_version(d, c, seq):
    v = d.versions.get(seq)
    return {"version": v, "summary": f"v{seq}：{V.canon(v['content'])}" if v else f"無 v{seq}"}


@tool("diff_versions", "比對兩版差異（預設：上一版 vs 目前）", {"a": _int("舊版"), "b": _int("新版")})
async def diff_versions(d, c, a=None, b=None):
    h = d.versions.head()
    b = b or h["seq"]
    a = a or d.versions.get(b)["parent_seq"]
    va, vb = d.versions.get(a), d.versions.get(b)
    if not va or not vb:
        return {"summary": "版本不存在"}
    df = V.diff(va["content"], vb["content"])
    return {"a": a, "b": b, "diff": df, "summary": f"v{a} → v{b}（{vb['actor']}：{vb['reason']}）：{V.fmt_diff(df)}"}


@tool("propose_rollback", "提出 rollback 請求：顯示 diff，等待 Operator 確認（預設回到上一版）", {"to_seq": _int("目標版本")})
async def propose_rollback(d, c, to_seq=None):
    h = d.versions.head()
    to = to_seq or h["parent_seq"]
    df = V.diff(h["content"], d.versions.get(to)["content"])
    eid = d.issues.esc_create(c.issue_id, "operator", "confirm_rollback",
                              f"確認 rollback 到 v{to}？變更：{V.fmt_diff(df)}", {"to_seq": to, "diff": df})
    d.issues.event(c.issue_id, "escalate", f"Operator 確認請求 #{eid}：rollback 到 v{to}")
    return {"escalation": eid, "summary": f"將從 v{h['seq']} 回到 v{to}，變更：{V.fmt_diff(df)}。已送出 Operator 確認請求 #{eid}，尚未執行"}


# ---------- L1/L2 會改變系統 ----------
@tool("restart_pipeline", "重啟推論 pipeline（L1）", {"lane": _int("車道")}, ("lane",))
async def restart_pipeline(d, c, lane):
    r = await d.edge.restart_pipeline(lane)
    return {"ok": r.get("ok", False), "summary": r.get("msg", "")}


@tool("reconnect_stream", "重連攝影機串流（L1）", {"lane": _int("車道")}, ("lane",))
async def reconnect_stream(d, c, lane):
    r = await d.edge.reconnect_stream(lane)
    return {"ok": r.get("ok", False), "summary": r.get("msg", "")}


async def _commit_push(d, c, content, reason):
    try:
        v, changed = V.commit(d.versions, content, c.actor, reason, c.issue_id)
    except ValueError as e:
        return {"ok": False, "summary": str(e)}
    if changed:
        await d.edge.push_config(v["content"])
        d.issues.event(c.issue_id, "version", f"新增 v{v['seq']}（{c.actor}）：{reason}")
    return {"ok": True, "changed": changed, "seq": v["seq"],
            "summary": f"v{v['seq']} {'已建立' if changed else '內容相同，未新增版本'}"}


@tool("apply_config", "變更設定（自動快照）", {"patch": {"type": "object"}, "reason": _str("原因")}, ("patch", "reason"))
async def apply_config(d, c, patch, reason):
    return await _commit_push(d, c, V.merge(d.versions.head()["content"], patch), reason)


@tool("rollback_version", "rollback 到指定版本（新增一版，內容等於目標版）", {"to_seq": _int("目標版本"), "evidence": _str("相關性證據")}, ("to_seq",))
async def rollback_version(d, c, to_seq, evidence=None):
    t = d.versions.get(to_seq)
    if not t:
        return {"ok": False, "summary": f"無 v{to_seq}"}
    r = await _commit_push(d, c, t["content"], f"rollback 到 v{to_seq}")
    r["summary"] = f"rollback 到 v{to_seq}：" + r["summary"]
    return r


# ---------- 執行入口：所有呼叫都經過 policy gate ----------
def _pctx(d, c, args):
    return {"now": time.time(), "origin": c.origin, "approved": c.approved, "issue_id": c.issue_id,
            "actor": c.actor, "head": d.versions.head(),
            "rate_window": d.s.policy.rate_window_sec,
            "l1_max": (d.versions.head() or {"content": {}})["content"].get("policy", {}).get("l1_max_per_10min", d.s.policy.l1_max_per_10min),
            "recent": [{"tool": a["tool"], "lane": json.loads(a["args"]).get("lane"), "ts": a["ts"]}
                       for a in d.issues.actions(since=time.time() - d.s.policy.rate_window_sec)
                       if a["status"] in ("ok", "failed", "running")]}


async def execute(d, name, args=None, call: Call | None = None):
    args, c = args or {}, call or Call()
    t = REG.get(name)
    if not t:
        return {"ok": False, "summary": f"unknown tool {name}"}
    dec = policy.evaluate(name, args, _pctx(d, c, args))
    if dec.level != "L0":
        d.issues.event(c.issue_id, "policy", f"{name} {json.dumps(args, ensure_ascii=False)} → {dec.level} {dec.verdict}：{dec.reason}")
    if dec.verdict != "allow":
        return {"ok": False, "blocked": dec.verdict, "summary": dec.reason}
    aid = None
    if dec.level != "L0":
        aid = uuid.uuid4().hex[:10]
        d.issues.action_start(aid, c.issue_id, name, args, dec.level, c.actor)
    try:
        res = await t.fn(d, c, **args)
    except Exception as e:                                   # 工具錯誤不可中斷 loop
        res = {"ok": False, "summary": f"{type(e).__name__}: {e}"}
    res.setdefault("ok", True)
    if aid:
        d.issues.action_finish(aid, res["ok"], {"summary": res.get("summary")})
    if c.issue_id is not None or dec.level != "L0":
        d.issues.event(c.issue_id, "tool", f"{name}({json.dumps(args, ensure_ascii=False)}) → {'OK' if res['ok'] else 'FAIL'}：{res.get('summary', '')[:300]}")
    return res
