"""EdgeControlPort 的 sim 實作：以 HTTP 呼叫模擬器控制 API（POC）。正式版換成真實邊緣控制通道。"""
import httpx


class SimClient:
    """修復動作作用於 sim 控制 API（不掛載 docker.sock）。正式版換成真實邊緣控制通道。"""
    def __init__(self, url): self.url = url.rstrip("/")

    async def _call(self, method, path, **kw):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.request(method, self.url + path, **kw)
                return r.json()
        except Exception as e:
            return {"ok": False, "msg": f"sim unreachable: {type(e).__name__}"}

    async def restart_pipeline(self, lane): return await self._call("POST", "/control/restart_pipeline", params={"lane": lane})
    async def reconnect_stream(self, lane): return await self._call("POST", "/control/reconnect_stream", params={"lane": lane})
    async def physical_fix(self, lane): return await self._call("POST", "/control/physical_fix", params={"lane": lane})
    async def push_config(self, cfg): return await self._call("PUT", "/control/config", json=cfg)
    async def fault(self, name, lane=1): return await self._call("POST", f"/fault/{name}", params={"lane": lane})
    async def reset(self): return await self._call("POST", "/control/reset")
