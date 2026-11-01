"""Notifier 的 outbox 實作（POC）。正式版可換 PagerDuty / LINE / Slack。"""
import json, time


class OutboxNotifier:
    """POC：寫入 outbox（UI 的遠端工程師面板讀取）。正式版換 PagerDuty / LINE / Slack。"""
    def __init__(self, db): self.db = db

    def notify(self, target, payload):
        self.db.x("INSERT INTO outbox(ts,target,payload) VALUES(?,?,?)",
                  (time.time(), target, json.dumps(payload, ensure_ascii=False, default=str)))
