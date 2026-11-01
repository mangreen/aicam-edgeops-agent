"""依環境變數建立 LLM provider。"""
import os, socket
from .auto import AutoLLM
from .cloud import AnthropicLLM, OpenAICompat


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
