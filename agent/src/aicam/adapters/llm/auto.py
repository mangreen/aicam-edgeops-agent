"""雲端優先，失敗自動退回 Mock。"""
import time
from .mock import MockLLM


class AutoLLM:
    """雲端優先、失敗（斷網／逾時／格式錯誤）自動退回 Mock，並在 30 秒內不再重試雲端。"""
    def __init__(self, cloud=None, mock=None, on_fallback=None):
        self.cloud, self.mock, self.on_fallback = cloud, mock or MockLLM(), on_fallback
        self.name, self._down_until = (cloud.name if cloud else "mock"), 0

    async def _run(self, fn, *a):
        if self.cloud and time.time() >= self._down_until:
            try:
                out = await getattr(self.cloud, fn)(*a)
                self.name = self.cloud.name
                return out
            except Exception as e:
                self._down_until = time.time() + 30
                if self.on_fallback: self.on_fallback(f"雲端 LLM 不可用（{type(e).__name__}），退回 Mock")
        self.name = "mock"
        return await getattr(self.mock, fn)(*a)

    async def plan(self, ctx): return await self._run("plan", ctx)
    async def report(self, ctx): return await self._run("report", ctx)
    async def chat_plan(self, t, h): return await self._run("chat_plan", t, h)
    async def chat_answer(self, t, r): return await self._run("chat_answer", t, r)
