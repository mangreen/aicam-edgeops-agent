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


_TOOLKEYS = ("tool", "name", "function")


def _snippet(txt: str, n: int = 80) -> str:
    return re.sub(r"\s+", " ", txt.strip())[:n]


def parse_json(txt: str, convert=lambda o: o):
    """從模型輸出中找出第一個「合法且符合預期」的 JSON 值。

    逐個 `[`／`{` 位置嘗試 raw_decode，而不是貪婪地取第一個括號到最後一個括號：
    因此前後夾雜說明文字、markdown code fence、`[1]` 之類的括號都不會讓解析失敗。
    convert 回傳 None 表示這個候選不符合預期（例如散文中的 `[搜尋歷史]`），繼續找下一個。
    """
    dec = json.JSONDecoder()
    for i, ch in enumerate(txt):
        if ch in "[{":
            try:
                obj, _ = dec.raw_decode(txt[i:])
            except ValueError:
                continue
            out = convert(obj)
            if out is not None:
                return out
    raise LLMError(f"回應不是預期的 JSON：{_snippet(txt)}")


def as_plan(o):
    return o if isinstance(o, dict) and any(k in o for k in _TOOLKEYS) else None


def as_calls(o):
    """接受 {"calls":[…]}、[…]、單一呼叫物件；空陣列代表「不需要工具」。"""
    if isinstance(o, dict):
        for k in ("calls", "tool_calls", "tools"):
            if k in o:
                o = o[k]
                break
        else:
            return [o] if any(k in o for k in _TOOLKEYS) else None
    if isinstance(o, list) and all(isinstance(c, dict) and any(k in c for k in _TOOLKEYS) for c in o):
        return o
    return None


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


JSON_ONLY = "\n\n（只輸出 JSON，不要其他文字）"
# few-shot：只放「所需工具都已啟用」的範例，避免教模型呼叫被停用的工具
EXAMPLES = [
    ("查 Lane 1 過去 2 天的 metrics", ("query_metrics",), '{"calls":[{"tool":"query_metrics","args":{"lane":1,"since_hours":48}}]}'),
    ("我們之前聊過什麼", ("search_history",), '{"calls":[{"tool":"search_history","args":{}}]}'),
    ("Lane 1 最近改了什麼", ("list_versions",), '{"calls":[{"tool":"list_versions","args":{"limit":5}}]}'),
    ("回到上一版", ("diff_versions", "propose_rollback"), '{"calls":[{"tool":"diff_versions","args":{}},{"tool":"propose_rollback","args":{}}]}'),
    ("你好", (), '{"calls":[]}'),
]


class CloudLLM(MockLLM):
    """雲端 LLM 共用邏輯：把 plan／report／chat 轉成 prompt 並解析 JSON；格式錯誤時 raise LLMError。"""
    real = True

    def info(self): return {"provider": self.name, "model": getattr(self, "model", "?"), "real": True}

    def _sys(self, scope, task):
        base = self.prompt_source(scope) if self.prompt_source else ""
        return (base + "\n\n" if base else "") + task

    async def _complete(self, system: str, user: str, json_mode: bool = False) -> str: raise NotImplementedError

    async def converse(self, text):
        return await self._complete(self._sys("chat", "請簡短回答。"), text)

    async def _ask_json(self, system, user, convert):
        """要求 JSON 輸出；第一次解析失敗時，附上原因再問一次（只一次），仍失敗才 raise LLMError。"""
        err = None
        for attempt in range(2):
            u = user if attempt == 0 else (f"{user}\n\n[上一次回覆無法解析（{err}）。請只輸出 JSON，"
                                         "不要說明文字、不要 markdown。]")
            txt = await self._complete(system, u, json_mode=True)
            try:
                return parse_json(txt, convert)
            except LLMError as e:
                err = str(e)
        raise LLMError(err)

    async def plan(self, ctx):
        names = list(ctx.get("available_tools", [])) + ["escalate"]
        sys_ = ("你是門市攝影機系統的維運 Agent。只能從下列工具選一個動作，參數名稱與型別必須完全照 schema；"
                "無安全可行動作時 tool 填 escalate。僅回 JSON：{\"tool\":..,\"args\":{..},\"rationale\":\"繁中一句\"}。\n"
                "可用工具：\n" + tools_block(ctx.get("tool_schemas", [])))
        slim = {k: v for k, v in ctx.items() if k != "tool_schemas"}
        out = norm_call(await self._ask_json(self._sys("agent", sys_), json.dumps(slim, ensure_ascii=False, default=str) + JSON_ONLY, as_plan))
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
        shots = "\n".join(f"問：{q} → {out}" for q, need, out in EXAMPLES if all(n in names for n in need))
        sys_ = ("你是維運助理。依問題選要呼叫的工具，參數名稱與型別必須完全照 schema。\n"
                "輸出格式：只輸出一個 JSON 物件 {\"calls\":[{\"tool\":\"工具名\",\"args\":{...}}]}，最多 3 個呼叫；"
                "不需要工具時輸出 {\"calls\":[]}。不要輸出任何其他文字。\n"
                + (f"範例：\n{shots}\n" if shots else "") + "可用工具：\n" + tools_block(tools))
        user = text + (f"\n\n[上一次的工具呼叫有誤，請依 schema 修正：{feedback}]" if feedback else "") + JSON_ONLY
        calls = [norm_call(c) for c in await self._ask_json(self._sys("chat", sys_), user, as_calls)]
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
    """OpenAI-compatible chat/completions（OpenAI 與 OpenRouter 共用）。

    JSON 任務使用 temperature=0 與 response_format=json_object；若該模型／供應商不支援（HTTP 400/404/422），
    自動改用不帶 response_format 重送，並記住，之後不再嘗試。
    """
    def __init__(self, name, base, key, model, extra_headers=None):
        self.name, self.base, self.key, self.model, self.eh = name, base.rstrip("/"), key, model, extra_headers or {}
        self._json_mode_ok = True

    async def _complete(self, system, user, json_mode=False):
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode:
            body["temperature"] = 0
            if self._json_mode_ok:
                body["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=20) as c:
            url, hdr = f"{self.base}/chat/completions", {"Authorization": f"Bearer {self.key}", **self.eh}
            r = await c.post(url, headers=hdr, json=body)
            if r.status_code in (400, 404, 422) and "response_format" in body:
                self._json_mode_ok = False
                body.pop("response_format")
                r = await c.post(url, headers=hdr, json=body)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


class AnthropicLLM(CloudLLM):
    """Anthropic Messages API。"""
    name = "anthropic"

    def __init__(self, key, model): self.key, self.model = key, model

    async def _complete(self, system, user, json_mode=False):
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://api.anthropic.com/v1/messages",
                             headers={"x-api-key": self.key, "anthropic-version": "2023-06-01"},
                             json={"model": self.model, "max_tokens": 800, "system": system,
                                   "messages": [{"role": "user", "content": user}],
                                   **({"temperature": 0} if json_mode else {})})
            r.raise_for_status()
            return r.json()["content"][0]["text"]
