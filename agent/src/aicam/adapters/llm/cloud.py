"""雲端 LLM adapters：OpenAI-compatible（含 OpenRouter）與 Anthropic。"""
import json
import re

import httpx

from aicam.core.constants import CHAT_TOOLS, PLAN_TOOLS

from .mock import MockLLM


class LLMError(Exception):
    ...


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
