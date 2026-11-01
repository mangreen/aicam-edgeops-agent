"""工具執行入口：所有 tool 呼叫都必須經過這裡（registry → 參數驗證 → Policy gate → 執行 → 紀錄）。"""
import json
import time
import uuid
from dataclasses import dataclass

from aicam.core import policy
from aicam.core import versions as V


@dataclass
class Call:
    """一次工具呼叫的情境：誰（actor）、從哪裡來（origin）、屬於哪個 issue、是否已獲 Operator 核准。"""
    issue_id: int | None = None
    actor: str = "agent"       # agent | operator | engineer
    origin: str = "agent"      # agent | chat | ui | external
    approved: bool = False


def _pctx(d, c, args, spec):
    head = d.versions.head()
    pc = d.s.policy
    return {"now": time.time(), "origin": c.origin, "approved": c.approved, "issue_id": c.issue_id,
            "actor": c.actor, "head": head, "level": spec.level, "rate_window": pc.rate_window_sec,
            "l1_max": ((head or {}).get("content", {}).get("policy", {}).get("l1_max_per_10min", pc.l1_max_per_10min)),
            "agent_writable": pc.agent_writable,
            "patch_keys": sorted(V.flat(args.get("patch", {}))) if isinstance(args.get("patch"), dict) else [],
            "recent": [{"tool": a["tool"], "lane": json.loads(a["args"]).get("lane"), "ts": a["ts"]}
                       for a in d.issues.actions(since=time.time() - pc.rate_window_sec)
                       if a["status"] in ("ok", "failed", "running")]}


async def execute(d, name, args=None, call: Call | None = None):
    args, c = args or {}, call or Call()
    spec = d.tools.get(name)
    if not spec:
        msg = f"工具 {name} 不存在或已停用（設定檔 [tools]）"
        d.issues.event(c.issue_id, "policy", msg)
        return {"ok": False, "blocked": "disabled", "summary": msg}
    if (err := d.tools.validate(spec, args)):
        d.issues.event(c.issue_id, "policy", f"{name} 參數驗證失敗：{err}")
        return {"ok": False, "blocked": "invalid_args", "summary": err}
    dec = policy.evaluate(name, args, _pctx(d, c, args, spec))
    if dec.level != "L0":
        d.issues.event(c.issue_id, "policy",
                       f"{name} {json.dumps(args, ensure_ascii=False)} → {dec.level} {dec.verdict}：{dec.reason}")
    if dec.verdict != "allow":
        return {"ok": False, "blocked": dec.verdict, "summary": dec.reason}
    aid = None
    if dec.level != "L0":
        aid = uuid.uuid4().hex[:10]
        d.issues.action_start(aid, c.issue_id, name, args, dec.level, c.actor)
    try:
        res = await spec.fn(d, c, **args)
    except Exception as e:                                   # 工具錯誤不可中斷 loop
        res = {"ok": False, "summary": f"{type(e).__name__}: {e}"}
    res.setdefault("ok", True)
    if aid:
        d.issues.action_finish(aid, res["ok"], {"summary": res.get("summary")})
    if c.issue_id is not None or dec.level != "L0":
        d.issues.event(c.issue_id, "tool", f"{name}({json.dumps(args, ensure_ascii=False)}) → "
                       f"{'OK' if res['ok'] else 'FAIL'}：{res.get('summary', '')[:300]}")
    return res
