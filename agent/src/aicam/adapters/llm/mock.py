"""POC 專用：決定性規則 + 模板的 Mock LLM。不屬於正式執行路徑。"""
import re

from aicam.core.constants import CAUSE, KIND_ZH


class MockLLM:
    """決定性規則 + 模板的離線 LLM（POC 專用）。規劃依事件類型走固定規則；不解讀 prompt。"""
    name = "mock"

    async def plan(self, ctx):
        k, lane, h = ctx["kind"], ctx["lane"], ctx["history"]
        fails = [x for x in h if not x["ok"]]
        avail = ctx.get("available_tools")

        def act(tool, args, why):
            if avail is not None and tool not in avail:      # 設定檔已停用該工具 → 不提案，直接升級
                return {"tool": "escalate", "args": {}, "rationale": f"工具 {tool} 已停用（設定檔），無法自動處理"}
            return {"tool": tool, "args": args, "rationale": why}
        if k == "inference_stalled" and len(fails) < 2:
            return act("restart_pipeline", {"lane": lane}, "FPS 歸零但串流正常，依 runbook 先重啟 pipeline")
        if k == "camera_no_signal" and len(fails) < 2:
            return act("reconnect_stream", {"lane": lane}, "串流中斷，依 runbook 先嘗試重連")
        if k == "detection_drop" and ctx.get("suspect") and not h:
            s = ctx["suspect"]
            return act("rollback_version", {"to_seq": s["parent_seq"]},
                       f"v{s['seq']}（{s['actor']}）變更後偵測數驟降，建議回到 v{s['parent_seq']}")
        return {"tool": "escalate", "args": {}, "rationale": "自動修復已無可行或安全的動作，升級處理"}

    async def report(self, ctx):
        i, acts = ctx["issue"], ctx["actions"]
        steps = "、".join(f"{a['tool']}({a['status']})" for a in acts) or "無"
        sus = ctx.get("suspect")
        extra = f"\n變更證據：v{sus['seq']} {sus['diff']}；{sus['evidence']}" if sus else ""
        return (f"【事件報告 #{i['id']}】Lane {i['lane']} {KIND_ZH.get(i['kind'], i['kind'])}\n"
                f"根因：{CAUSE.get(i['kind'], '未知')}\n處置：{steps}\n結果：{ctx['outcome']}{extra}")

    async def chat_plan(self, text, history, tools=None, feedback=None):
        t, calls = text.lower(), []
        m = re.search(r"lane\s*(\d)", t)
        lane = int(m.group(1)) if m else None
        d, hr = re.search(r"(\d+)\s*天", t), re.search(r"(\d+)\s*小時", t)
        hours = int(d.group(1)) * 24 if d else int(hr.group(1)) if hr else None
        vm = re.search(r"v(\d+).*?v(\d+)", t)
        if re.search(r"回到上一版|rollback|回滾|還原", t):
            return [{"tool": "diff_versions", "args": {}}, {"tool": "propose_rollback", "args": {}}]
        if vm:
            return [{"tool": "diff_versions", "args": {"a": int(vm.group(1)), "b": int(vm.group(2))}}]
        if re.search(r"聊(過|果|了|到)|聊天|之前(聊|問|說|談|討論)|歷史對話|對話紀錄|上次問|剛(剛|才)(問|聊)|前面(問|聊)", t):
            return [{"tool": "search_history", "args": {"query": f"Lane {lane}" if lane else ""}}]
        if re.search(r"類似|上次|怎麼解|歷史|issue", t):
            kind = ("camera_no_signal" if re.search(r"斷線|無訊號|攝影機|camera", t) else
                    "detection_drop" if re.search(r"偵測|roi", t) else
                    "inference_stalled" if re.search(r"卡|stall|fps|推論", t) else None)
            calls = [{"tool": "search_issues", "args": {"kind": kind, "lane": lane}}]
            return calls + [{"tool": "search_knowledge", "args": {"query": kind or text}}]
        if re.search(r"斷線|disconnect|無訊號", t):
            return [{"tool": "query_logs", "args": {"lane": lane, "contains": "stream disconnected", "since_hours": hours or 168}}]
        if re.search(r"改了什麼|誰改|版本|version", t):
            return [{"tool": "list_versions", "args": {"limit": 5}}]
        if re.search(r"\blogs?\b|日誌", t):
            return [{"tool": "query_logs", "args": {"lane": lane, "since_hours": hours or 1, "limit": 5}}]
        if re.search(r"trace|追蹤|span", t):
            return [{"tool": "query_traces", "args": {"lane": lane, "status": "error", "since_hours": hours or 1}}]
        if re.search(r"fps|metric|指標|偵測數", t):
            name = "detections_per_min" if re.search(r"偵測", t) else "fps"
            return [{"tool": "query_metrics", "args": {"lane": lane or 1, "name": name, "since_hours": hours or 1}}]
        if re.search(r"狀態|status|現在", t):
            return [{"tool": "get_status", "args": {}}]
        return [{"tool": "search_knowledge", "args": {"query": text}}]

    prompt_source = None
    model = "rule-based"

    def set_prompt_source(self, fn): self.prompt_source = fn

    def info(self): return {"provider": "mock", "model": self.model, "real": False}

    async def converse(self, text):
        return ("[MOCK] 這是離線 Mock（決定性規則 + 模板），不是真實大模型，也不會解讀 prompt；"
                "安全底線由程式碼 guard 與 Policy Gate 強制。")

    async def chat_answer(self, text, results):
        return "\n".join(f"• {r.get('summary', '')}" for r in results) or "找不到相關資料。"
