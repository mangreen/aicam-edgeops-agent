"""Notifier：通知 Operator／遠端工程師。POC：outbox；正式版：PagerDuty / LINE / Slack。"""
from typing import Protocol


class Notifier(Protocol):
    def notify(self, target: str, payload: dict) -> None: ...
