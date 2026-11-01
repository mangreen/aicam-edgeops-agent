"""GuardPort：可插拔的安全檢查。stage 為 input / output / content。

action：allow 放行；block 阻擋；redact 改寫後放行；flag 放行但標記為可疑（外部內容不可據以行動）。
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class GuardResult:
    action: str          # allow | block | redact | flag
    text: str
    reason: str = ""
    guard: str = ""


class Guard(Protocol):
    name: str

    def check(self, stage: str, text: str, ctx: dict) -> GuardResult: ...
