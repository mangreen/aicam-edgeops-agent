from dataclasses import replace

from aicam.plugins.skills import load_skills


def test_compose_layers_skills_and_fixed_footer(d):
    t = d.prompts.compose("chat")
    assert "aicam-edgeops-agent" in t and "先給結論" in t                 # system(all) + chat-style(chat)
    assert "[Skills]" in t and "camera-troubleshoot" in t               # 啟用的 skill
    assert "<untrusted>" in t and d.prompts.canary in t                  # 固定安全規則
    assert "先給結論" not in d.prompts.compose("agent")                  # scope 隔離


def test_ui_layer_added_live_and_disabled(d):
    d.prompts.upsert("operator-scope", "Operator 只能執行：已處理、無法處理、確認 rollback。", scope="chat", priority=5)
    assert "Operator 只能執行" in d.prompts.compose("chat")
    assert "Operator 只能執行" not in d.prompts.compose("agent")
    d.prompts.upsert("operator-scope", "x", scope="chat", enabled=False)
    assert "Operator 只能" not in d.prompts.compose("chat")


def test_ui_layer_overrides_file_layer_and_delete_restores(d):
    d.prompts.upsert("system", "OVERRIDDEN", scope="all", priority=0)
    assert "OVERRIDDEN" in d.prompts.compose("agent") and "你是 aicam-edgeops-agent" not in d.prompts.compose("agent")
    d.prompts.delete("system")
    assert "你是 aicam-edgeops-agent" in d.prompts.compose("agent")


def test_history_and_revert(d):
    d.prompts.upsert("r", "v1")
    d.prompts.upsert("r", "v2")
    h = d.prompts.history("r")
    assert [x["content"] for x in h][:2] == ["v2", "v1"]
    d.prompts.revert("r", h[1]["id"])
    assert next(x for x in d.prompts.layers() if x["name"] == "r")["content"] == "v1"
    assert d.prompts.revert("r", 99999) is None


def test_inactive_skill_not_in_prompt(d):
    d.s = replace(d.s, raw={**d.s.raw, "tools": {"restart_pipeline": False}})
    d.rebuild_plugins()
    d.skills = load_skills(d.s, d.tools)
    assert "camera-troubleshoot" not in d.prompts.compose("chat")


async def test_cloud_llm_receives_composed_prompt(d):
    from aicam.adapters.llm import AutoLLM, CloudLLM

    seen = {}

    class Cloud(CloudLLM):
        name, model = "fake-cloud", "m1"

        async def _complete(self, system, user, json_mode=False):
            seen["system"] = system
            return "我是 fake-cloud"
    d.prompts.upsert("operator-scope", "只允許 Operator 查詢。", scope="chat")
    d.attach_llm(AutoLLM(Cloud()))
    ans = await d.llm.converse("你是誰")
    assert ans == "我是 fake-cloud" and "只允許 Operator 查詢" in seen["system"] and "aicam-edgeops-agent" in seen["system"]
    info = d.llm.info()
    assert (info["provider"], info["model"], info["real"], info["fallback_active"]) == ("fake-cloud", "m1", True, False)


def test_delete_ui_layer_only(d):
    d.prompts.upsert("tmp-layer", "x", scope="chat")
    assert d.prompts.delete("tmp-layer") is True
    assert all(x["name"] != "tmp-layer" for x in d.prompts.layers())
    assert d.prompts.delete("tmp-layer") is False             # 已不存在
    assert d.prompts.delete("chat-style") is False            # 只存在於檔案層：不可由 UI 刪除
    assert any(x["name"] == "chat-style" and x["source"] == "file" for x in d.prompts.layers())
