"""雲端優先，失敗自動退回 Mock。

兩種失敗要分開處理：
- 連線類（逾時、HTTP 錯誤、DNS…）：雲端暫時不可用 → 30 秒內直接用 Mock，不再重試；
- 格式類（非 JSON、不在允許清單的工具、回應欄位缺漏）：只代表「這一次」模型答得不好 →
  這一次改用 Mock，下一次照常呼叫雲端（不鎖 30 秒）。
Reset（或 `POST /api/llm/reset`）會依 .env 重新建立 provider，立即解除任何退回狀態。
"""
import time

from .cloud import LLMError
from .mock import MockLLM

FORMAT_ERRORS = (LLMError, ValueError, KeyError, IndexError, TypeError)
COOLDOWN_S = 30


class AutoLLM:
    """雲端優先、失敗自動退回 Mock；`info()` 會如實回報目前是真模型還是退回的 Mock 以及原因。"""
    def __init__(self, cloud=None, mock=None, on_fallback=None):
        self.cloud, self.mock, self.on_fallback = cloud, mock or MockLLM(), on_fallback
        self.name, self._down_until, self.last_error = (cloud.name if cloud else "mock"), 0, ""
        self.format_errors = 0                       # 累計「回應格式不符」次數（已含一次自動重問）

    async def _run(self, fn, *a, **kw):
        if self.cloud and time.time() >= self._down_until:
            try:
                out = await getattr(self.cloud, fn)(*a, **kw)
                self.name, self.last_error = self.cloud.name, ""
                return out
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {str(e)[:100]}"
                if isinstance(e, FORMAT_ERRORS):
                    self.format_errors += 1
                    msg = f"雲端 LLM 回應格式不符（已自動重問一次仍失敗：{self.last_error}），本次改用 Mock"
                else:
                    self._down_until = time.time() + COOLDOWN_S
                    msg = f"雲端 LLM 不可用（{self.last_error}），{COOLDOWN_S} 秒內退回 Mock；Reset 可立即重試"
                if self.on_fallback:
                    self.on_fallback(msg)
        self.name = "mock"
        return await getattr(self.mock, fn)(*a, **kw)

    def set_prompt_source(self, fn):
        self.mock.set_prompt_source(fn)
        if self.cloud:
            self.cloud.set_prompt_source(fn)

    def info(self):
        """最近一次實際回應者；尚未呼叫前以設定的 provider 為準。"""
        base = self.cloud.info() if self.cloud and self.name != "mock" else self.mock.info()
        return base | {"fallback_active": bool(self.cloud) and self.name == "mock", "last_error": self.last_error,
                       "configured": self.cloud.name if self.cloud else "mock", "format_errors": self.format_errors}

    async def converse(self, text): return await self._run("converse", text)
    async def plan(self, ctx): return await self._run("plan", ctx)
    async def report(self, ctx): return await self._run("report", ctx)
    async def chat_answer(self, t, r): return await self._run("chat_answer", t, r)

    async def chat_plan(self, t, h, tools=None, feedback=None):
        return await self._run("chat_plan", t, h, tools, feedback=feedback)
