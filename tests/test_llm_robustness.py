"""雲端 LLM 容錯：參數校正、回應格式、答案不可是工具呼叫、退回策略、附錯誤重新規劃。"""
import json

import pytest

from aicam.adapters.llm import AutoLLM, CloudLLM, LLMError
from aicam.core import chat
from aicam.core.executor import execute
from aicam.plugins.registry import normalize_args, parse_hours


def spec(d, name):
    return d.tools.specs[name]


@pytest.mark.parametrize("v,h", [("2d", 48), ("48h", 48), ("30m", 0.5), ("2 days", 48), ("1w", 168), (6, 6), ("3 hours", 3),
                                 ("過去2天", 48), ("90min", 1.5)])
def test_parse_hours(v, h):
    assert parse_hours(v) == pytest.approx(h)


def test_parse_hours_rejects_garbage():
    assert parse_hours("soon") is None and parse_hours(True) is None


def test_normalize_user_reported_case(d):
    """實際案例：{"lane_id": "1", "duration": "2d"} → lane=1, since_hours=48"""
    args, notes = normalize_args(spec(d, "query_metrics"), {"lane_id": "1", "duration": "2d"})
    assert args == {"lane": 1, "since_hours": 48.0} and any("lane_id→lane" in n for n in notes)


def test_normalize_second_variant(d):
    args, _ = normalize_args(spec(d, "query_metrics"), {"lane": "1", "hours": 48})
    assert args == {"lane": 1, "since_hours": 48.0}


def test_normalize_does_not_override_real_param(d):
    args, _ = normalize_args(spec(d, "query_metrics"), {"lane": 1, "since_hours": 3, "hours": 99})
    assert args["since_hours"] == 3                                   # 已有正確參數時不被別名覆蓋


def test_unknown_args_dropped_for_readonly_but_kept_for_actions(d):
    args, notes = normalize_args(spec(d, "query_logs"), {"lane": 1, "foo": 1})
    assert "foo" not in args and any("丟棄" in n for n in notes)
    args, _ = normalize_args(spec(d, "restart_pipeline"), {"lane": 1, "foo": 1})
    assert "foo" in args                                              # L1 保留，交給驗證拒絕


async def test_execute_normalizes_then_runs_and_logs_note(d):
    r = await execute(d, "query_metrics", {"lane_id": "1", "duration": "2d"})
    assert r["ok"] and "近 48 小時" in r["summary"]
    assert d.db.q("SELECT 1 FROM events WHERE text LIKE '%參數已校正%'")


async def test_normalization_does_not_bypass_policy(d):
    r = await execute(d, "restart_pipeline", {"lane_id": "1", "bogus": 1})   # L1 工具的未知參數仍被拒絕
    assert r["blocked"] == "invalid_args" and d.edge.calls == []


class Scripted(CloudLLM):
    """依序回傳預先寫好的文字，並記錄收到的 system prompt。"""
    name, model = "scripted", "m"

    def __init__(self, replies):
        self.replies, self.systems = list(replies), []

    async def _complete(self, system, user, json_mode=False):
        self.systems.append((system, user))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tools_for(d, *names):
    return [t for t in d.tools.mcp_tools() if t["name"] in names]


async def test_chat_plan_prompt_contains_full_schemas(d):
    llm = Scripted(['[{"tool":"query_metrics","args":{"lane":1}}]'])
    await llm.chat_plan("x", [], tools_for(d, "query_metrics"))
    system = llm.systems[0][0]
    assert "since_hours: number" in system and "lane: integer（必填）" in system     # 不只給名稱，還有參數與型別


@pytest.mark.parametrize("reply", [
    '{"tool": "query_metrics", "arguments": {"lane": "1", "hours": 48}}',                   # 單一物件 + arguments
    '```json\n[{"name": "query_metrics", "parameters": {"lane": "1", "hours": 48}}]\n```',  # code fence + name/parameters
    '好的：[{"tool":"query_metrics","args":"{\\"lane\\": \\"1\\"}"}]',                      # args 是 JSON 字串
])
async def test_chat_plan_tolerates_common_variants(d, reply):
    calls = await Scripted([reply]).chat_plan("x", [], tools_for(d, "query_metrics"))
    assert calls[0]["tool"] == "query_metrics" and isinstance(calls[0]["args"], dict) and calls[0]["args"]["lane"] == "1"


async def test_chat_plan_rejects_tool_not_allowed(d):
    with pytest.raises(LLMError):
        await Scripted(['[{"tool":"rollback_version","args":{"to_seq":1}}]']).chat_plan("x", [], tools_for(d, "query_metrics"))


async def test_answer_that_is_a_tool_call_falls_back_to_summaries_without_failing_cloud(d):
    llm = Scripted(['{"tool": "query_metrics", "arguments": {"lane": "1", "hours": 48}}'])
    auto = AutoLLM(llm)
    ans = await auto.chat_answer("查詢 lane 1 metrics", [{"tool": "query_metrics", "summary": "Lane 1 fps 平均 15"}])
    assert "Lane 1 fps 平均 15" in ans and "tool" not in ans
    assert auto.info()["fallback_active"] is False                      # 雲端仍視為可用


async def test_report_that_is_a_tool_call_falls_back(d):
    ctx = {"issue": {"id": 1, "lane": 1, "kind": "inference_stalled"}, "actions": [], "outcome": "ok", "suspect": None}
    out = await Scripted(['{"tool":"x","args":{}}']).report(ctx)
    assert "事件報告" in out


async def test_format_error_falls_back_once_and_does_not_lock_cloud(d):
    llm = Scripted(["not json at all", "still not json", '[{"tool":"query_metrics","args":{"lane":1}}]'])   # 第一次：原回覆 + 重問皆失敗
    notes = []
    auto = AutoLLM(llm, on_fallback=notes.append)
    first = await auto.chat_plan("查 metrics", [], tools_for(d, "query_metrics"))
    assert auto.name == "mock" and notes and "格式不符" in notes[0] and "重問" in notes[0] and first   # 這次用 Mock
    second = await auto.chat_plan("查 metrics", [], tools_for(d, "query_metrics"))
    assert auto.name == "scripted" and second[0]["tool"] == "query_metrics"                   # 下一次回到雲端


async def test_connection_error_locks_cloud_for_cooldown(d):
    llm = Scripted([ConnectionError("offline"), '[{"tool":"x"}]'])
    auto = AutoLLM(llm)
    await auto.converse("hi")
    await auto.converse("hi")
    assert len(llm.systems) == 1 and auto.info()["fallback_active"] and "ConnectionError" in auto.info()["last_error"]


async def test_chat_repairs_bad_args_once_with_feedback(d):
    llm = Scripted(['[{"tool":"query_metrics","args":{"foo":1}}]',                       # 缺 lane：校正無法救
                    '[{"tool":"query_metrics","args":{"lane":1,"since_hours":48}}]',    # 附錯誤訊息重新規劃後正確
                    "Lane 1 近 48 小時 fps 平均約 15。"])
    d.attach_llm(AutoLLM(llm))
    r = await chat.handle(d, "查詢 lane 1 過去 2 天的 metrics")
    assert "fps 平均" in r["answer"] and len(llm.systems) == 3
    assert "缺少必要參數" in llm.systems[1][1]                                            # 錯誤訊息確實回饋給模型
    assert r["tools"][-1].startswith("query_metrics(") and "48" in r["tools"][-1]


async def test_chat_does_not_loop_when_repair_also_fails(d):
    bad = '[{"tool":"query_metrics","args":{"foo":1}}]'
    llm = Scripted([bad, bad, "抱歉，工具參數有誤，無法查詢。"])
    d.attach_llm(AutoLLM(llm))
    r = await chat.handle(d, "查 metrics")
    assert len(llm.systems) == 3 and "無法查詢" in r["answer"]


async def test_end_to_end_user_reported_scenario(d):
    """原始回報：LLM 規劃出 lane_id/duration，回答階段又輸出工具呼叫 JSON。現在應得到正確結果與自然語言答案。"""
    llm = Scripted(['[{"tool":"query_metrics","args":{"lane_id":"1","duration":"2d"}}]',
                    json.dumps({"tool": "query_metrics", "arguments": {"lane": "1", "hours": 48}})])
    d.attach_llm(AutoLLM(llm))
    r = await chat.handle(d, "查詢 lane 1 過去 2 天的 metrics")
    assert "近 48 小時" in r["answer"] and "{" not in r["answer"]
    assert len(llm.systems) == 2                                                    # 沒有多餘的重試
