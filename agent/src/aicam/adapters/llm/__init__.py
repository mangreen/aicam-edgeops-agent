"""LLM adapters：Mock／雲端／Auto（失敗退回）。"""
from .auto import AutoLLM
from .cloud import AnthropicLLM, CloudLLM, LLMError, OpenAICompat
from .factory import make_llm
from .mock import MockLLM
