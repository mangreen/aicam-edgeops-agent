"""雲端 LLM adapters：OpenAI-compatible（含 OpenRouter）與 Anthropic。

雲端模型的輸出不可靠（猜錯參數名稱、把答案寫成工具呼叫 JSON、包 code fence…），所以：
1. prompt 帶完整工具 schema（名稱、參數、型別、必填），不只給名稱；
2. 解析端容忍常見變體（`arguments`／`parameters`、單一物件、code fence）；
3. 參數名稱與型別的細部校正由 executor 統一處理（plugins/registry.normalize_args）；
4. 「格式不對」只丟 LLMError，由 AutoLLM 本次改用 Mock，不會把雲端判為故障。
"""
import json
import re

import httpx

from .mock import MockLLM


class LLMError(Exception):
    """LLM 回應不符預期格式（例如非法 JSON 或不在允許清單的工具）。這是格式問題，不是連線問題。"""


def tools_block(tools: list[dict]) -> str:
    """把 MCP 格式的工具定義轉成給 LLM 看的簡短 schema 清單。"""
    lines = []
    for t in tools or []:
        sch = t.get("inputSchema", {})
        req = set(sch.get("required", []))
        params = ", ".join(f"{k}: {v.get('type', 'any')}{'（必填）' if k in req else ''}"
                           + (f"〔{v['description']}〕" if v.get("description") else "")
                           for k, v in sch.get("properties", {}).items()) or "無參數"
        lines.append(f"- {t['name']}({params})：{t.get('description', '')}")
    return "\n".join(lines)


def norm_call(c) -> dict:
    """把常見的工具呼叫變體整理成 {"tool","args",...}。"""
    if not isinstance(c, dict):
        raise LLMError("tool call is not an object")
    args = next((c[k] for k in ("args", "arguments", "parameters", "params", "input") if k in c), {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError as e:
            raise LLMError("tool args is not valid JSON") from e
    tool = c.get("tool") or c.get("name") or c.get("function")
    if not tool or not isinstance(args, dict):
        raise LLMError("malformed tool call")
    return {**{k: v for k, v in c.items() if k not in ("args", "arguments", "parameters", "params", "input", "name", "function")},
            "tool": tool, "args": args}


def looks_like_tool_call(text: str) -> bool:
    """答案本該是自然語言，卻輸出了工具呼叫 JSON。"""
    t = re.sub(r"^```\w*|```$", "", text.strip(), flags=re.M).strip()
    if not t or t[0] not in "{[":
        return False
    try:
        o = json.loads(t)
    except ValueError:
        return False
    items = o if isinstance(o, list) else [o]
    return any(isinstance(i, dict) and ({"tool", "name", "function"} & set(i)) for i in items)


class CloudLLM(MockLLM):
    """雲端 LLM 共用邏輯：把 plan／report／chat 轉成 prompt 並解析 JSON；格式錯誤時 raise LLMError。"""
    real = True

    def info(self): return {"provider": self.name, "model": getattr(self, "model", "?"), "real": True}

    def _sys(self, scope, task):
        base = self.prompt_source(scope) if self.prompt_source else ""
        return (base + "\n\n" if base else "") + task

    async def _complete(self, system: str, user: str) -> str: raise NotImplementedError

    async def converse(self, text):
        return await self._complete(self._sys("chat", "請簡短回答。"), text)

    @staticmethod
    def _json(txt):
        m = re.search(r"[\[{].*[\]}]", txt, re.S)
        if not m:
            raise LLMError("no json")
        try:
            return json.loads(m.group(0))
        except ValueError as e:
            raise LLMError("invalid json") from e

    async def plan(self, ctx):
        names = list(ctx.get("available_tools", [])) + ["escalate"]
        sys_ = ("你是門市攝影機系統的維運 Agent。只能從下列工具選一個動作，參數名稱與型別必須完全照 schema；"
                "無安全可行動作時 tool 填 escalate。僅回 JSON：{\"tool\":..,\"args\":{..},\"rationale\":\"繁中一句\"}。\n"
                "可用工具：\n" + tools_block(ctx.get("tool_schemas", [])))
        slim = {k: v for k, v in ctx.items() if k != "tool_schemas"}
        out = norm_call(self._json(await self._complete(self._sys("agent", sys_), json.dumps(slim, ensure_ascii=False, default=str))))
        if out["tool"] not in names:
            raise LLMError("bad tool")
        return out

    async def report(self, ctx):
        out = await self._complete(self._sys("agent", "用繁體中文寫 5 行內事件報告：根因、處置、結果、（如有）變更證據。"
                                                       "不要捏造資料中沒有的事實；只輸出報告文字，不要輸出 JSON 或工具呼叫。"),
                                   json.dumps(ctx, ensure_ascii=False, default=str))
        return await MockLLM.report(self, ctx) if looks_like_tool_call(out) else out

    async def chat_plan(self, text, history, tools=None, feedback=None):
        tools = tools or []
        names = [t["name"] for t in tools]
        sys_ = ("你是維運助理。依問題選要呼叫的工具，參數名稱與型別必須完全照 schema（例如查 2 天內的 metrics："
                "{\"tool\":\"query_metrics\",\"args\":{\"lane\":1,\"since_hours\":48}}）。"
                "僅回 JSON 陣列 [{\"tool\":..,\"args\":{..}}]，最多 3 個。rollback 請求用 diff_versions 加 propose_rollback。\n"
                "可用工具：\n" + tools_block(tools))
        user = text + (f"\n\n[上一次的工具呼叫有誤，請依 schema 修正：{feedback}]" if feedback else "")
        raw = self._json(await self._complete(self._sys("chat", sys_), user))
        calls = [norm_call(c) for c in (raw if isinstance(raw, list) else [raw])]
        if any(c["tool"] not in names for c in calls):
            raise LLMError("bad calls")
        return calls

    async def chat_answer(self, text, results):
        out = await self._complete(
            self._sys("chat", "依據工具結果用繁體中文簡短回答，不要捏造。只輸出自然語言，不要輸出 JSON、程式碼區塊或工具呼叫；"
                              "若工具失敗，說明失敗原因與可行的下一步，不要重試。"),
            f"問題：{text}\n結果：{json.dumps(results, ensure_ascii=False, default=str)[:4000]}")
        return await MockLLM.chat_answer(self, text, results) if looks_like_tool_call(out) else out


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
