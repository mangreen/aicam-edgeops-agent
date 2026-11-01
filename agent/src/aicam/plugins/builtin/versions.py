"""內建工具：設定版本查詢、diff、apply_config、rollback。"""

from aicam.core import versions as V
from aicam.core.executor import Call  # noqa: F401
from aicam.plugins.registry import Toolbox

from ._util import _ago, _int, _str

box = Toolbox()


@box.tool("list_versions", "列出設定版本", {"limit": _int("筆數")}, level="L0", chat=True)
async def list_versions(d, c, limit=5):
    rows = d.versions.list(limit)
    return {"rows": rows, "summary": "；".join(f"v{r['seq']} {_ago(r['ts'])} {r['actor']}：{r['reason']}" for r in rows)}


@box.tool("get_version", "取得單一版本內容", {"seq": _int("版本號")}, ("seq",), level="L0", chat=True)
async def get_version(d, c, seq):
    v = d.versions.get(seq)
    return {"version": v, "summary": f"v{seq}：{V.canon(v['content'])}" if v else f"無 v{seq}"}


@box.tool("diff_versions", "比對兩版差異（預設：上一版 vs 目前）", {"a": _int("舊版"), "b": _int("新版")}, level="L0", chat=True)
async def diff_versions(d, c, a=None, b=None):
    h = d.versions.head()
    b = b or h["seq"]
    a = a or d.versions.get(b)["parent_seq"]
    va, vb = d.versions.get(a), d.versions.get(b)
    if not va or not vb:
        return {"summary": "版本不存在"}
    df = V.diff(va["content"], vb["content"])
    return {"a": a, "b": b, "diff": df, "summary": f"v{a} → v{b}（{vb['actor']}：{vb['reason']}）：{V.fmt_diff(df)}"}


@box.tool("propose_rollback", "提出 rollback 請求：顯示 diff，等待 Operator 確認（預設回到上一版）", {"to_seq": _int("目標版本")}, level="L0", chat=True)
async def propose_rollback(d, c, to_seq=None):
    h = d.versions.head()
    to = to_seq or h["parent_seq"]
    df = V.diff(h["content"], d.versions.get(to)["content"])
    eid = d.issues.esc_create(c.issue_id, "operator", "confirm_rollback",
                              f"確認 rollback 到 v{to}？變更：{V.fmt_diff(df)}", {"to_seq": to, "diff": df})
    d.issues.event(c.issue_id, "escalate", f"Operator 確認請求 #{eid}：rollback 到 v{to}")
    return {"escalation": eid, "summary": f"將從 v{h['seq']} 回到 v{to}，變更：{V.fmt_diff(df)}。已送出 Operator 確認請求 #{eid}，尚未執行"}


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


@box.tool("apply_config", "變更設定（自動快照）", {"patch": {"type": "object"}, "reason": _str("原因")}, ("patch", "reason"), level="L1", plannable=True)
async def apply_config(d, c, patch, reason):
    return await _commit_push(d, c, V.merge(d.versions.head()["content"], patch), reason)


@box.tool("rollback_version", "rollback 到指定版本（新增一版，內容等於目標版）", {"to_seq": _int("目標版本"), "evidence": _str("相關性證據")}, ("to_seq",), level="L1", plannable=True)
async def rollback_version(d, c, to_seq, evidence=None):
    t = d.versions.get(to_seq)
    if not t:
        return {"ok": False, "summary": f"無 v{to_seq}"}
    r = await _commit_push(d, c, t["content"], f"rollback 到 v{to_seq}")
    r["summary"] = f"rollback 到 v{to_seq}：" + r["summary"]
    return r


TOOLS = box.tools
