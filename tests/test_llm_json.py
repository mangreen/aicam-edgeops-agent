"""雲端 LLM 的 JSON 輸出可靠度：解析、自動重問、JSON mode 降級、few-shot、歷史對話路由。"""
import httpx
import pytest

from aicam.adapters.llm import AutoLLM, LLMError
from aicam.adapters.llm.cloud import OpenAICompat, as_calls, as_plan, parse_json
from aicam.core import chat
from test_llm_robustness import Scripted, tools_for

CALL = '{"tool":"search_history","args":{}}'


# ---------- 解析 ----------
@pytest.mark.parametrize("txt", [
    f'[{CALL}]',
    f'好的，我會這樣做：\n```json\n[{CALL}]\n```\n希望有幫助 [1]',                 # 後面多了 [1]：舊的貪婪解析會失敗
    f'先看 [搜尋歷史] 這個工具。{{"calls":[{CALL}]}} 以上',                         # 前面散文有括號、外層是物件
    f'{{"tool_calls":[{CALL}]}}',
    CALL,                                                                          # 單一呼叫物件
    f'說明文字 {{"note":"x"}} 然後 [{CALL}]',                                       # 第一個 JSON 不是呼叫，跳過
])
def test_parse_json_tolerates_surrounding_text(txt):
    calls = parse_json(txt, as_calls)
    assert calls and calls[0]["tool"] == "search_history"


def test_parse_json_empty_calls_means_no_tool():
    assert parse_json('不需要工具：{"calls": []}', as_calls) == []


@pytest.mark.parametrize("txt", ["我們之前聊過 Lane 2 的 FPS。", "如需查詢請說 [搜尋歷史]", '{"foo": 1}', "", "[1, 2, 3]"])
def test_parse_json_rejects_non_calls(txt):
    with pytest.raises(LLMError):
        parse_json(txt, as_calls)


def test_as_plan_requires_tool_key():
    assert as_plan({"tool": "escalate"}) and as_plan({"foo": 1}) is None


# ---------- 自動重問 ----------
async def test_invalid_json_is_retried_once_with_reason(d):
    llm = Scripted(["我們之前聊過 Lane 2 的 FPS 問題。", f'{{"calls":[{CALL}]}}'])
    auto = AutoLLM(llm)
    calls = await auto.chat_plan("我們之前聊果什麼？", [], tools_for(d, "search_history"))
    assert calls[0]["tool"] == "search_history" and len(llm.systems) == 2
    assert "無法解析" in llm.systems[1][1] and "我們之前聊過" in llm.systems[1][1]        # 重問時附上上次的內容摘要
    assert auto.name == "scripted" and auto.info()["fallback_active"] is False and auto.format_errors == 0   # 沒有退回 Mock


async def test_two_invalid_replies_fall_back_once_with_snippet(d):
    llm = Scripted(["散文一", "散文二"])
    notes = []
    auto = AutoLLM(llm, on_fallback=notes.append)
    await auto.chat_plan("x", [], tools_for(d, "search_history"))
    assert len(llm.systems) == 2 and auto.name == "mock" and auto.format_errors == 1
    assert "散文二" in notes[0] and "重問" in notes[0]                              # 訊息含原始回覆片段，方便診斷
    assert auto.info()["format_errors"] == 1


async def test_json_mode_only_for_json_tasks(d):
    seen = []

    class Rec(Scripted):
        async def _complete(self, system, user, json_mode=False):
            seen.append(json_mode)
            return await super()._complete(system, user, json_mode)
    llm = Rec(['{"calls":[]}', "答案", "converse"])
    await llm.chat_plan("x", [], tools_for(d, "search_history"))
    await llm.chat_answer("x", [])
    await llm.converse("x")
    assert seen == [True, False, False]


async def test_empty_calls_flow_through_chat(d):
    d.attach_llm(AutoLLM(Scripted(['{"calls": []}', "你好，我是維運助理。"])))
    r = await chat.handle(d, "你好")
    assert r["tools"] == [] and "維運助理" in r["answer"]


# ---------- prompt：few-shot 只含已啟用工具 ----------
async def test_prompt_has_examples_for_enabled_tools_only(d):
    llm = Scripted(['{"calls":[]}'])
    await llm.chat_plan("x", [], tools_for(d, "query_metrics", "search_history"))
    system = llm.systems[0][0]
    assert '"tool":"search_history"' in system and '"since_hours":48' in system
    assert "propose_rollback" not in system and "list_versions" not in system        # 未啟用的工具不出現在範例
    assert '{"calls":[]}' in system                                                   # 「不需要工具」的範例
    assert llm.systems[0][1].endswith("（只輸出 JSON，不要其他文字）")


# ---------- OpenAI-compatible：JSON mode 與降級 ----------
def patch_client(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr("aicam.adapters.llm.cloud.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def ok(content="{}"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_openai_json_mode_and_temperature(monkeypatch):
    bodies = []

    def handler(req):
        bodies.append(__import__("json").loads(req.content))
        return ok()
    patch_client(monkeypatch, handler)
    llm = OpenAICompat("openrouter", "http://x/v1", "k", "m")
    await llm._complete("s", "u", json_mode=True)
    await llm._complete("s", "u")
    assert bodies[0]["response_format"] == {"type": "json_object"} and bodies[0]["temperature"] == 0
    assert "response_format" not in bodies[1] and "temperature" not in bodies[1]    # 一般任務不強制


async def test_openai_json_mode_unsupported_degrades_and_remembers(monkeypatch):
    sent = []

    def handler(req):
        body = __import__("json").loads(req.content)
        sent.append("response_format" in body)
        return httpx.Response(400, json={"error": "response_format unsupported"}) if "response_format" in body else ok("[]")
    patch_client(monkeypatch, handler)
    llm = OpenAICompat("openrouter", "http://x/v1", "k", "m")
    assert await llm._complete("s", "u", json_mode=True) == "[]"
    assert await llm._complete("s", "u", json_mode=True) == "[]"
    assert sent == [True, False, False] and llm._json_mode_ok is False             # 降級後不再嘗試


async def test_openai_real_http_error_still_raises(monkeypatch):
    patch_client(monkeypatch, lambda req: httpx.Response(401, json={"error": "bad key"}))
    llm = OpenAICompat("openrouter", "http://x/v1", "k", "m")
    with pytest.raises(httpx.HTTPStatusError):
        await llm._complete("s", "u", json_mode=True)


# ---------- 退回 Mock 時：使用者的句子也要路由正確 ----------
@pytest.mark.parametrize("q", ["我們之前聊果什麼？", "我們之前聊過什麼", "之前問過什麼", "剛剛問了什麼", "歷史對話", "聊天紀錄"])
async def test_mock_routes_history_questions_even_with_typos(d, q):
    r = await chat.handle(d, q)
    assert r["tools"] and r["tools"][0].startswith("search_history(")
    assert "Lane 2 昨天 FPS" in r["answer"] or "最近的對話" in r["answer"]


async def test_search_history_falls_back_to_recent_when_no_match(d):
    from aicam.core.executor import execute
    r = await execute(d, "search_history", {"query": "完全不存在的字串xyz"})
    assert "沒有符合" in r["summary"] and "最近的對話" in r["summary"] and "問：" in r["summary"]
    r = await execute(d, "search_history", {})
    assert r["ok"] and "最近的對話" in r["summary"]
