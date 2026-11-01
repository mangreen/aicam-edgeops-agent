"""雲端 LLM adapters：OpenAI-compatible（含 OpenRouter）與 Anthropic。"""
import json
import re

import httpx

from .mock import MockLLM


class LLMError(Exception):
    """LLM 回應不符預期格式（例如非法 JSON 或不在允許清單的工具）。"""
    ...


class CloudLLM(MockLLM):
    """雲端 LLM 共用邏輯：把 plan／report／chat 轉成 prompt 並解析 JSON；失敗時 raise，由 AutoLLM 退回 Mock。"""
    real = True

    def info(self): return {"provider": self.name, "model": getattr(self, "model", "?"), "real": True}

    def _sys(self, scope, task):
        base = self.prompt_source(scope) if self.prompt_source else ""
        return (base + "\n\n" if base else "") + task

    async def converse(self, text):
        return await self._complete(self._sys("chat", "請簡短回答。"), text)

    """雲端 LLM：決策與文字由模型產生；失敗時 raise，由 AutoLLM 退回 Mock。"""
    async def _complete(self, system: str, user: str) -> str: raise NotImplementedError

    @staticmethod
    def _json(txt):
        m = re.search(r"[\[{].*[\]}]", txt, re.S)
        if not m: raise LLMError("no json")
        return json.loads(m.group(0))

    async def plan(self, ctx):
        plan_tools = list(ctx.get("available_tools", [])) + ["escalate"]
        sys_ = ("你是門市攝影機系統的維運 Agent。只能從 " + ",".join(plan_tools) + " 選一個動作；"
                "無安全可行動作時選 escalate。僅回 JSON：{\"tool\":..,\"args\":{..},\"rationale\":\"繁中一句\"}")
        out = self._json(await self._complete(self._sys("agent", sys_), json.dumps(ctx, ensure_ascii=False, default=str)))
        if out.get("tool") not in plan_tools: raise LLMError("bad tool")
        return out

    async def report(self, ctx):
        return await self._complete(self._sys("agent", "用繁體中文寫 5 行內事件報告：根因、處置、結果、（如有）變更證據。不要捏造資料中沒有的事實。"),
                                    json.dumps(ctx, ensure_ascii=False, default=str))

    async def chat_plan(self, text, history, allowed=None):
        allowed = list(allowed or [])
        sys_ = ("你是維運助理。從工具清單選要呼叫的工具，僅回 JSON 陣列 [{\"tool\":..,\"args\":{..}}]，最多 3 個。"
                "工具：" + ",".join(allowed) + "。rollback 請求用 diff_versions 加 propose_rollback。")
        calls = self._json(await self._complete(self._sys("chat", sys_), text))
        if not isinstance(calls, list) or any(c.get("tool") not in allowed for c in calls): raise LLMError("bad calls")
        return calls

    async def chat_answer(self, text, results):
        return await self._complete(self._sys("chat", "依據工具結果用繁體中文簡短回答，不要捏造。"),
                                    f"問題：{text}\n結果：{json.dumps(results, ensure_ascii=False, default=str)[:4000]}")


class OpenAICompat(CloudLLM):
    """OpenAI-compatible chat/completions（OpenAI 與 OpenRouter 共用）。"""
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
    """Anthropic Messages API。"""
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
