"""內建工具：邊緣端修復動作（L1，可逆、限頻、必須 Verify）。"""

from aicam.core.executor import Call  # noqa: F401
from aicam.plugins.registry import Toolbox

from ._util import _int

box = Toolbox()


@box.tool("restart_pipeline", "重啟推論 pipeline（L1）", {"lane": _int("車道")}, ("lane",), level="L1", plannable=True)
async def restart_pipeline(d, c, lane):
    r = await d.edge.restart_pipeline(lane)
    return {"ok": r.get("ok", False), "summary": r.get("msg", "")}


@box.tool("reconnect_stream", "重連攝影機串流（L1）", {"lane": _int("車道")}, ("lane",), level="L1", plannable=True)
async def reconnect_stream(d, c, lane):
    r = await d.edge.reconnect_stream(lane)
    return {"ok": r.get("ok", False), "summary": r.get("msg", "")}


TOOLS = box.tools
