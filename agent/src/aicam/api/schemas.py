"""API 輸入 schema：在信任邊界驗證型別、列舉與大小上限。"""
from typing import Literal

from pydantic import BaseModel, Field


class LogRow(BaseModel):
    ts: float
    lane: int = Field(ge=0, le=64)
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    msg: str = Field(max_length=2000)


class MetricRow(BaseModel):
    ts: float
    lane: int = Field(ge=0, le=64)
    name: str = Field(max_length=64)
    value: float


class SpanRow(BaseModel):
    trace_id: str = Field(max_length=64)
    span_id: str = Field(max_length=64)
    parent_id: str | None = Field(default=None, max_length=64)
    name: str = Field(max_length=64)
    lane: int = Field(ge=0, le=64)
    ts: float
    dur_ms: float
    status: Literal["ok", "error"]


class IngestBody(BaseModel):
    logs: list[LogRow] = Field(default_factory=list, max_length=5000)
    metrics: list[MetricRow] = Field(default_factory=list, max_length=5000)
    spans: list[SpanRow] = Field(default_factory=list, max_length=5000)


class ChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class RespondBody(BaseModel):
    response: Literal["fixed", "cannot", "confirm", "reject"]


class ToggleBody(BaseModel):
    enabled: bool


class RollbackBody(BaseModel):
    to_seq: int | None = Field(default=None, ge=1)


class PromptBody(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    scope: Literal["agent", "chat", "all"] = "all"
    priority: int = Field(default=50, ge=0, le=1000)
    enabled: bool = True


class ProbeBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)
