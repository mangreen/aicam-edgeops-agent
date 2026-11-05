"""Policy gate：純程式碼規則，不交給 LLM。"""
from dataclasses import dataclass
from fnmatch import fnmatch

RATE_WINDOW = 600  # 預設值；實際由 ctx["rate_window"] 提供（設定檔）


@dataclass
class Decision:
    """Policy 判定結果：level（L0–L3）、verdict（allow／needs_operator／escalate_engineer／deny）與原因。"""
    level: str      # L0..L3
    verdict: str    # allow | needs_operator | escalate_engineer | deny
    reason: str


def evaluate(tool: str, args: dict, ctx: dict) -> Decision:
    """風險等級來自 tool manifest（ctx["level"]）；沒有合法等級一律拒絕。"""
    level = ctx.get("level")
    if level not in ("L0", "L1", "L2", "L3"):
        return Decision("L3", "deny", "未宣告風險等級，預設拒絕")
    if tool == "rollback_version":
        return _rollback(args, ctx)
    if tool == "apply_config":
        d = _apply_config(ctx)
        if d:
            return d
    if level == "L0":
        return Decision("L0", "allow", "唯讀")
    if level == "L3":
        return Decision("L3", "escalate_engineer", "不可逆或未知風險，僅產 incident bundle")
    if level == "L2":
        ok = ctx.get("approved")
        return Decision("L2", "allow" if ok else "needs_operator", "Operator 已核准" if ok else "影響營運，需 Operator 核准")
    lane = args.get("lane")
    n = sum(1 for a in ctx.get("recent", [])
            if a["tool"] == tool and a.get("lane") == lane and ctx["now"] - a["ts"] < ctx.get("rate_window", RATE_WINDOW))
    mx = ctx.get("l1_max", 2)
    if n >= mx:
        return Decision("L1", "deny", f"超過 L1 頻率限制（{mx} 次/10 分鐘），防止重啟風暴")
    return Decision("L1", "allow", f"可逆低風險（本窗口已 {n}/{mx} 次）")


def _apply_config(ctx):
    """Operator／工程師的變更只記錄來源；Agent 只能改白名單路徑。"""
    if ctx.get("actor") in ("operator", "engineer"):
        return Decision("L1", "allow", f"{ctx['actor']} 變更，僅記錄來源並自動快照")
    if ctx.get("approved"):
        return Decision("L1", "allow", "Operator 已核准")
    bad = [k for k in ctx.get("patch_keys", []) if not any(fnmatch(k, p) for p in ctx.get("agent_writable", ()))]
    if bad:
        return Decision("L2", "needs_operator", f"Agent 不可自行修改 {bad[:3]}（不在白名單），需 Operator 確認")
    return None


def _rollback(args, ctx):
    head, to = ctx.get("head"), args.get("to_seq")
    if ctx.get("approved"):
        return Decision("L2", "allow", "Operator 已確認")
    if not head or to is None:
        return Decision("L2", "deny", "缺少目標版本")
    if ctx.get("origin") in ("chat", "ui"):
        return Decision("L2", "needs_operator", "使用者要求 rollback，需先顯示 diff 並由 Operator 確認")
    if to != head.get("parent_seq"):
        return Decision("L2", "needs_operator", "回到比上一版更早的版本，需 Operator 確認")
    if head.get("actor") == "agent" and head.get("issue_id") == ctx.get("issue_id"):
        return Decision("L1", "allow", "回復 Agent 本次事件自己做的變更")
    if ctx.get("evidence_verified"):
        return Decision("L1", "allow", "近期他人變更與指標惡化相關（附證據），回到上一版")
    return Decision("L2", "needs_operator", "缺少相關性證據，需 Operator 確認")
