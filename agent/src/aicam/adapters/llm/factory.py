"""依環境變數建立 LLM provider。"""
import os
import socket

from .auto import AutoLLM
from .cloud import AnthropicLLM, OpenAICompat


def _online(host, port=443, timeout=1.5):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def make_llm(on_fallback=None, env=None):
    """env 預設為 os.environ；Reset 時會傳入「環境變數 + .env 檔」的合併結果。"""
    env = os.environ if env is None else env
    mode, e = env.get("LLM_PROVIDER", "auto").lower(), env.get
    cands = []
    if e("ANTHROPIC_API_KEY"): cands.append(("anthropic", "api.anthropic.com", lambda: AnthropicLLM(e("ANTHROPIC_API_KEY"), e("ANTHROPIC_MODEL", "claude-haiku-5-5"))))
    if e("OPENAI_API_KEY"): cands.append(("openai", "api.openai.com", lambda: OpenAICompat("openai", e("OPENAI_BASE_URL", "https://api.openai.com/v1"), e("OPENAI_API_KEY"), e("OPENAI_MODEL", "gpt-4o-mini"))))
    if e("OPENROUTER_API_KEY"): cands.append(("openrouter", "openrouter.ai", lambda: OpenAICompat("openrouter", "https://openrouter.ai/api/v1", e("OPENROUTER_API_KEY"), e("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku"))))
    if mode == "mock": return AutoLLM(None, on_fallback=on_fallback)
    for name, host, mk in cands:
        if mode in ("auto", name) and (mode != "auto" or _online(host)):
            return AutoLLM(mk(), on_fallback=on_fallback)
    llm = AutoLLM(None, on_fallback=on_fallback)
    # 使用 Mock 的原因要看得見，否則使用者只會看到 MOCK 卻不知道為什麼
    llm.last_error = ("auto：找不到金鑰或目前離線，使用 Mock" if mode == "auto"
                      else f"LLM_PROVIDER={mode} 但缺少對應的金鑰，使用 Mock")
    return llm
