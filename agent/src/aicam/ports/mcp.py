"""McpSourcePort：外部 MCP server 的工具來源（POC 只定義介面，不含任何網路實作）。

`list_tools` 回傳 MCP `tools/list` 格式（name / description / inputSchema）；
`call_tool` 呼叫單一工具。MCP 工具沒有宣告風險等級時，一律視為 L3（只能升級給工程師）。
"""
from typing import Protocol


class McpSourcePort(Protocol):
    def list_tools(self) -> list[dict]: ...
    async def call_tool(self, name: str, arguments: dict) -> dict: ...
