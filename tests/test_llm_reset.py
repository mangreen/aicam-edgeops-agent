"""Reset 依 .env 重建 LLM：退回 Mock 後不必重啟容器；.env 改了 provider／金鑰也能即時生效。"""
from dataclasses import replace

from aicam.adapters.llm import AutoLLM, CloudLLM, factory
from aicam.config import load_dotenv


def test_load_dotenv_parsing(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# 註解\nLLM_PROVIDER=openrouter   # 行尾註解\nOPENROUTER_API_KEY="sk-or-abc"\nexport X=1\nBAD LINE\n\nEMPTY=\n')
    assert load_dotenv(str(f)) == {"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "sk-or-abc", "X": "1", "EMPTY": ""}
    assert load_dotenv(str(tmp_path / "nope")) == {} and load_dotenv("") == {}


def test_make_llm_explains_why_mock(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert "找不到金鑰" in factory.make_llm(env={"LLM_PROVIDER": "auto"}).last_error
    assert "缺少對應的金鑰" in factory.make_llm(env={"LLM_PROVIDER": "openrouter"}).last_error
    assert factory.make_llm(env={"LLM_PROVIDER": "mock"}).last_error == ""


def test_reset_llm_reads_env_file_and_clears_fallback(d, tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)

    class Broken(CloudLLM):
        name, model = "broken", "x"

        async def _complete(self, s, u, json_mode=False): raise ConnectionError("offline")
    d.attach_llm(AutoLLM(Broken()))
    import asyncio
    asyncio.run(d.llm.converse("hi"))
    assert d.llm.info()["fallback_active"] and d.llm._down_until > 0             # 已退回 Mock 且鎖定中

    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=sk-or-test\nOPENROUTER_MODEL=vendor/model-x\n")
    info = d.reset_llm(str(env))                                                  # 不需重啟，立即依 .env 重建
    assert (info["configured"], info["model"], info["real"]) == ("openrouter", "vendor/model-x", True)
    assert info["fallback_active"] is False and info["source"] == ".env" and d.llm._down_until == 0
    assert d.db.q("SELECT 1 FROM events WHERE type='llm' AND text LIKE '%已重新載入%vendor/model-x%'")

    env.write_text("LLM_PROVIDER=mock\n")                                          # 改回離線
    assert d.reset_llm(str(env))["configured"] == "mock"


def test_env_file_overrides_container_env(d, tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    env = tmp_path / ".env"
    env.write_text("LLM_PROVIDER=openai\nOPENAI_API_KEY=k\nOPENAI_MODEL=gpt-x\n")
    monkeypatch.setattr(factory, "_online", lambda host, **kw: True)
    assert d.reset_llm(str(env))["configured"] == "openai"                          # .env（較新）優先於容器建立時的環境變數


def test_api_reset_and_llm_reset(client, d, monkeypatch, tmp_path):
    monkeypatch.setenv("AICAM_ENV_FILE", str(tmp_path / "none"))
    r = client.post("/api/demo/reset").json()
    assert r["ok"] and r["llm"]["configured"] in ("mock", "anthropic", "openai", "openrouter")
    assert client.post("/api/llm/reset").status_code == 200
    d.s = replace(d.s, raw={"features": {"llm_probe": False, "demo_controls": True}})
    assert client.post("/api/llm/reset").status_code == 403
