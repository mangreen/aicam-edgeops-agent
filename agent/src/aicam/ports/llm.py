"""LLMProvider：Agent 決策與文字生成。POC：Mock / OpenAI-compat / Anthropic；正式版：vLLM / Ollama。"""
from typing import Protocol


class LLMProvider(Protocol):
    name: str

    async def plan(self, ctx: dict) -> dict: ...
    async def report(self, ctx: dict) -> str: ...
    async def chat_plan(self, text: str, history: list, tools: list | None = None, feedback: str | None = None) -> list: ...   # tools：MCP 格式的工具定義
    async def chat_answer(self, text: str, results: list) -> str: ...
    async def converse(self, text: str) -> str: ...      # 連線測試／自由對話
    def info(self) -> dict: ...                          # provider / model / real
    def set_prompt_source(self, fn) -> None: ...         # fn(scope) -> system prompt
