"""Policy gate：純程式碼規則，不交給 LLM。"""
from dataclasses import dataclass

L0 = {"get_status", "query_logs", "query_metrics", "query_traces", "search_knowledge", "search_issues",
      "search_history", "list_versions", "get_version", "diff_versions", "propose_rollback"}
L1 = {"restart_pipeline", "reconnect_stream", "apply_config"}
L2 = {"reboot_device", "rollback_version"}      # rollback 依情境於下方動態判定
L3 = {"firmware_update", "ssh_exec", "replace_model"}
RATE_WINDOW = 600


@dataclass
class Decision:
    level: str      # L0..L3
    verdict: str    # allow | needs_operator | escalate_engineer | deny
    reason: str


def evaluate(tool: str, args: dict, ctx: dict) -> Decision:
    if tool in L0:
        return Decision("L0", "allow", "唯讀")
    if tool in L3:
        return Decision("L3", "escalate_engineer", "不可逆或未知風險，僅產 incident bundle")
    if tool == "rollback_version":
        return _rollback(args, ctx)
    if tool in L2:
        ok = ctx.get("approved")
        return Decision("L2", "allow" if ok else "needs_operator", "Operator 已核准" if ok else "影響營運，需 Operator 核准")
    if tool in L1:
        if tool == "apply_config" and ctx.get("actor") in ("operator", "engineer"):
            return Decision("L1", "allow", f"{ctx['actor']} 變更，僅記錄來源並自動快照")
        lane = args.get("lane")
        n = sum(1 for a in ctx.get("recent", [])
                if a["tool"] == tool and a.get("lane") == lane and ctx["now"] - a["ts"] < RATE_WINDOW)
        mx = ctx.get("l1_max", 2)
        if n >= mx:
            return Decision("L1", "deny", f"超過 L1 頻率限制（{mx} 次/10 分鐘），防止重啟風暴")
        return Decision("L1", "allow", f"可逆低風險（本窗口已 {n}/{mx} 次）")
    return Decision("L3", "deny", f"未知工具 {tool}")


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
    if args.get("evidence"):
        return Decision("L1", "allow", "近期他人變更與指標惡化相關（附證據），回到上一版")
    return Decision("L2", "needs_operator", "缺少相關性證據，需 Operator 確認")
