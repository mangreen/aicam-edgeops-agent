"""工具執行入口：所有 tool 呼叫都必須經過這裡（registry → 參數驗證 → Policy gate → 執行 → 紀錄）。"""
import json
import time
import uuid
from dataclasses import dataclass

from aicam.core import policy
from aicam.core import versions as V
from aicam.plugins.registry import normalize_args


@dataclass
class Call:
    """一次工具呼叫的情境：誰（actor）、從哪裡來（origin）、屬於哪個 issue、是否已獲 Operator 核准。"""
    issue_id: int | None = None
    actor: str = "agent"       # agent | operator | engineer
    origin: str = "system"     # system（程式自身，如 triage）| agent（LLM 規劃的動作）| chat | ui | external
    approved: bool = False
    evidence: dict | None = None   # 由 loop 的 find_suspect 以程式碼算出的相關性證據（不是 LLM 填的）


# 依呼叫來源限制可用工具：LLM 規劃的動作只能用 plannable 工具，對話只能用 chat 工具
ORIGIN_FLAG = {"agent": "plannable", "chat": "chat"}


def _evidence_verified(c, head, args) -> bool:
    """rollback 的「相關性證據」必須來自 loop 的程式碼計算，且對應目前 head 與要回復的版本。"""
    e = c.evidence
    return bool(e and head and e.get("seq") == head["seq"] and e.get("parent_seq") == args.get("to_seq"))


def _pctx(d, c, args, spec):
    head = d.versions.head()
    pc = d.s.policy
    return {"now": time.time(), "origin": c.origin, "approved": c.approved, "issue_id": c.issue_id,
            "actor": c.actor, "head": head, "level": spec.level, "evidence_verified": _evidence_verified(c, head, args), "rate_window": pc.rate_window_sec,
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
    args, notes = normalize_args(spec, args)          # LLM 常猜錯參數名稱／型別：先做安全的校正
    if notes:
        d.issues.event(c.issue_id, "tool", f"{name} 參數已校正：{'；'.join(notes)}")
    flag = ORIGIN_FLAG.get(c.origin)
    if flag and not getattr(spec, flag):
        msg = f"工具 {name} 不允許由 {c.origin} 來源呼叫（manifest 的 {flag} 為 false）"
        d.issues.event(c.issue_id, "policy", msg)
        return {"ok": False, "blocked": "origin_not_allowed", "summary": msg}
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
