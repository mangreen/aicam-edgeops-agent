"""LLM providers。Mock 為 POC 專用（決定性規則 + 模板），不屬於正式執行路徑。"""
import json, os, re, socket, time
import httpx

KIND_ZH = {"inference_stalled": "推論 pipeline 卡死", "camera_no_signal": "攝影機無訊號", "detection_drop": "偵測數驟降"}
CAUSE = {"inference_stalled": "推論 worker 卡死（FPS 歸零但串流正常）",
         "camera_no_signal": "攝影機串流中斷，疑似電源／PoE／網路線問題",
         "detection_drop": "近期設定變更導致偵測數驟降"}
CHAT_TOOLS = ["get_status", "query_logs", "query_metrics", "query_traces", "search_knowledge", "search_issues",
              "search_history", "list_versions", "get_version", "diff_versions", "propose_rollback"]
PLAN_TOOLS = ["restart_pipeline", "reconnect_stream", "rollback_version", "escalate"]


class LLMError(Exception): ...


class MockLLM:
    name = "mock"

    async def plan(self, ctx):
        k, lane, h = ctx["kind"], ctx["lane"], ctx["history"]
        fails = [x for x in h if not x["ok"]]
        if k == "inference_stalled" and len(fails) < 2:
            return {"tool": "restart_pipeline", "args": {"lane": lane}, "rationale": "FPS 歸零但串流正常，依 runbook 先重啟 pipeline"}
        if k == "camera_no_signal" and len(fails) < 2:
            return {"tool": "reconnect_stream", "args": {"lane": lane}, "rationale": "串流中斷，依 runbook 先嘗試重連"}
        if k == "detection_drop" and ctx.get("suspect") and not h:
            s = ctx["suspect"]
            return {"tool": "rollback_version", "args": {"to_seq": s["parent_seq"], "evidence": s["evidence"]},
                    "rationale": f"v{s['seq']}（{s['actor']}）變更後偵測數驟降，建議回到 v{s['parent_seq']}"}
        return {"tool": "escalate", "args": {}, "rationale": "自動修復已無可行或安全的動作，升級處理"}

    async def report(self, ctx):
        i, acts = ctx["issue"], ctx["actions"]
        steps = "、".join(f"{a['tool']}({a['status']})" for a in acts) or "無"
        sus = ctx.get("suspect")
        extra = f"\n變更證據：v{sus['seq']} {sus['diff']}；{sus['evidence']}" if sus else ""
        return (f"【事件報告 #{i['id']}】Lane {i['lane']} {KIND_ZH.get(i['kind'], i['kind'])}\n"
                f"根因：{CAUSE.get(i['kind'], '未知')}\n處置：{steps}\n結果：{ctx['outcome']}{extra}")

    async def chat_plan(self, text, history):
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
        if re.search(r"聊過|之前問|歷史對話|上次問", t):
            return [{"tool": "search_history", "args": {"query": f"Lane {lane}" if lane else text[:10]}}]
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
        if re.search(r"trace|追蹤|span", t):
            return [{"tool": "query_traces", "args": {"lane": lane, "status": "error", "since_hours": hours or 1}}]
        if re.search(r"fps|metric|指標|偵測數", t):
            name = "detections_per_min" if re.search(r"偵測", t) else "fps"
            return [{"tool": "query_metrics", "args": {"lane": lane or 1, "name": name, "since_hours": hours or 1}}]
        if re.search(r"狀態|status|現在", t):
            return [{"tool": "get_status", "args": {}}]
        return [{"tool": "search_knowledge", "args": {"query": text}}]

    async def chat_answer(self, text, results):
        return "\n".join(f"• {r.get('summary', '')}" for r in results) or "找不到相關資料。"


class CloudLLM(MockLLM):
    """雲端 LLM：決策與文字由模型產生；失敗時 raise，由 AutoLLM 退回 Mock。"""
    async def _complete(self, system: str, user: str) -> str: raise NotImplementedError

    @staticmethod
    def _json(txt):
        m = re.search(r"[\[{].*[\]}]", txt, re.S)
        if not m: raise LLMError("no json")
        return json.loads(m.group(0))

    async def plan(self, ctx):
        sys_ = ("你是門市攝影機系統的維運 Agent。只能從 " + ",".join(PLAN_TOOLS) + " 選一個動作；"
                "無安全可行動作時選 escalate。僅回 JSON：{\"tool\":..,\"args\":{..},\"rationale\":\"繁中一句\"}")
        out = self._json(await self._complete(sys_, json.dumps(ctx, ensure_ascii=False, default=str)))
        if out.get("tool") not in PLAN_TOOLS: raise LLMError("bad tool")
        return out

    async def report(self, ctx):
        return await self._complete("用繁體中文寫 5 行內事件報告：根因、處置、結果、（如有）變更證據。不要捏造資料中沒有的事實。",
                                    json.dumps(ctx, ensure_ascii=False, default=str))

    async def chat_plan(self, text, history):
        sys_ = ("你是維運助理。從工具清單選要呼叫的工具，僅回 JSON 陣列 [{\"tool\":..,\"args\":{..}}]，最多 3 個。"
                "工具：" + ",".join(CHAT_TOOLS) + "。rollback 請求用 diff_versions 加 propose_rollback。")
        calls = self._json(await self._complete(sys_, text))
        if not isinstance(calls, list) or any(c.get("tool") not in CHAT_TOOLS for c in calls): raise LLMError("bad calls")
        return calls

    async def chat_answer(self, text, results):
        return await self._complete("依據工具結果用繁體中文簡短回答，不要捏造。",
                                    f"問題：{text}\n結果：{json.dumps(results, ensure_ascii=False, default=str)[:4000]}")


class OpenAICompat(CloudLLM):
    def __init__(self, name, base, key, model, extra_headers=None):
        self.name, self.base, self.key, self.model, self.eh = name, base.rstrip("/"), key, model, extra_headers or {}

    async def _complete(self, system, user):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{self.base}/chat/completions", headers={"Authorization": f"Bearer {self.key}", **self.eh},
                             json={"model": self.model, "messages": [{"role": "system", "content": system},
                                                                     {"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


class AnthropicLLM(CloudLLM):
    name = "anthropic"

    def __init__(self, key, model): self.key, self.model = key, model

    async def _complete(self, system, user):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://api.anthropic.com/v1/messages",
                             headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                             json={"model": self.model, "max_tokens": 800, "system": system,
                                   "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return r.json()["content"][0]["text"]


class AutoLLM:
    """雲端優先、失敗（斷網／逾時／格式錯誤）自動退回 Mock，並在 30 秒內不再重試雲端。"""
    def __init__(self, cloud=None, mock=None, on_fallback=None):
        self.cloud, self.mock, self.on_fallback = cloud, mock or MockLLM(), on_fallback
        self.name, self._down_until = (cloud.name if cloud else "mock"), 0

    async def _run(self, fn, *a):
        if self.cloud and time.time() >= self._down_until:
            try:
                out = await getattr(self.cloud, fn)(*a)
                self.name = self.cloud.name
                return out
            except Exception as e:
                self._down_until = time.time() + 30
                if self.on_fallback: self.on_fallback(f"雲端 LLM 不可用（{type(e).__name__}），退回 Mock")
        self.name = "mock"
        return await getattr(self.mock, fn)(*a)

    async def plan(self, ctx): return await self._run("plan", ctx)
    async def report(self, ctx): return await self._run("report", ctx)
    async def chat_plan(self, t, h): return await self._run("chat_plan", t, h)
    async def chat_answer(self, t, r): return await self._run("chat_answer", t, r)


def _online(host, port=443, timeout=1.5):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def make_llm(on_fallback=None):
    mode, e = os.getenv("LLM_PROVIDER", "auto").lower(), os.environ.get
    cands = []
    if e("ANTHROPIC_API_KEY"): cands.append(("anthropic", "api.anthropic.com", lambda: AnthropicLLM(e("ANTHROPIC_API_KEY"), e("ANTHROPIC_MODEL", "claude-haiku-5-5"))))
    if e("OPENAI_API_KEY"): cands.append(("openai", "api.openai.com", lambda: OpenAICompat("openai", e("OPENAI_BASE_URL", "https://api.openai.com/v1"), e("OPENAI_API_KEY"), e("OPENAI_MODEL", "gpt-4o-mini"))))
    if e("OPENROUTER_API_KEY"): cands.append(("openrouter", "openrouter.ai", lambda: OpenAICompat("openrouter", "https://openrouter.ai/api/v1", e("OPENROUTER_API_KEY"), e("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku"))))
    if mode == "mock": return AutoLLM(None, on_fallback=on_fallback)
    for name, host, mk in cands:
        if mode in ("auto", name) and (mode != "auto" or _online(host)):
            return AutoLLM(mk(), on_fallback=on_fallback)
    return AutoLLM(None, on_fallback=on_fallback)
