"""POC 專用：模擬門市邊緣端（攝影機 + 推論 + 上傳器）。不屬於正式執行路徑。"""
import asyncio
import os
import random
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000")
TICK = float(os.getenv("SIM_TICK", "2"))
RECONNECT_RETRIES = int(os.getenv("SIM_RECONNECT_RETRIES", "3"))   # 模擬 reconnect 內部重試次數（只影響回報文字）
BASE_AREA = 640 * 300
LANES = (1, 2)
DEFAULT_CFG = {"model": "vehicle-det-1.2.0", "policy": {"l1_max_per_10min": 2},
               "lanes": {str(i): {"roi": [120, 200, 640, 300], "fps_threshold": 10,
                                  "rtsp": "${SECRET:cam%d}" % i} for i in LANES}}

@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="aicam-sim", lifespan=lifespan)
S = {"cfg": DEFAULT_CFG, "buf": {"logs": [], "metrics": [], "spans": []}, "tick": 0,
     "lanes": {i: {"camera": True, "pipeline": True, "retry": 0} for i in LANES}}


def log(lane, level, msg):
    S["buf"]["logs"].append({"ts": time.time(), "lane": lane, "level": level, "msg": msg})


def make_spans(lane, st):
    tid, now = uuid.uuid4().hex[:16], time.time()
    cap_err, inf_err = not st["camera"], st["camera"] and not st["pipeline"]
    rows = [("capture", 12 if not cap_err else 3000, "error" if cap_err else "ok"),
            ("infer", 45 if not inf_err else 5000, "error" if inf_err else "ok"),
            ("upload", 20, "ok")]
    root = uuid.uuid4().hex[:8]
    return [{"trace_id": tid, "span_id": root if i == 0 else uuid.uuid4().hex[:8],
             "parent_id": None if i == 0 else root, "name": n, "lane": lane,
             "ts": now, "dur_ms": d, "status": s} for i, (n, d, s) in enumerate(rows)]


def tick_once():
    """產生一個取樣週期的 metrics / spans / logs（寫入緩衝區，不送出）。獨立出來以便測試。"""
    S["tick"] += 1
    now = time.time()
    for lane, st in S["lanes"].items():
        cfg = S["cfg"]["lanes"][str(lane)]
        ok = st["camera"] and st["pipeline"]
        fps = round(random.uniform(14.5, 15.5), 1) if ok else 0.0
        w, h = cfg["roi"][2], cfg["roi"][3]
        det = round(max(0.0, 14 * min(1, w * h / BASE_AREA) + random.uniform(-2, 2)), 1) if ok else 0.0
        for n, v in (("fps", fps), ("stream_connected", 1.0 if st["camera"] else 0.0),
                     ("detections_per_min", det)):
            S["buf"]["metrics"].append({"ts": now, "lane": lane, "name": n, "value": v})
        S["buf"]["spans"] += make_spans(lane, st)
        if not st["camera"] and S["tick"] % 5 == 0:
            st["retry"] += 1
            log(lane, "ERROR", f"still no signal from camera (auto-retry #{st['retry']})")
        elif st["camera"] and not st["pipeline"] and S["tick"] % 5 == 0:
            log(lane, "ERROR", "inference worker stalled: queue depth growing, 0 frames processed")
        elif ok and det < 4 and S["tick"] % 5 == 0:
            log(lane, "WARN", f"vehicle detections dropped to {det}/min (roi={cfg['roi']})")
        elif ok and S["tick"] % 15 == 0:
            log(lane, "INFO", f"frame batch ok fps={fps} det={det}/min")


async def loop():
    while True:
        await asyncio.sleep(TICK)
        tick_once()
        await flush()


async def flush():
    buf, S["buf"] = S["buf"], {"logs": [], "metrics": [], "spans": []}
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.post(f"{AGENT_URL}/ingest", json=buf)
    except Exception:
        pass  # agent 尚未就緒或重啟中：丟棄本批資料（POC 可接受）


def _lane(lane: int):
    if lane not in S["lanes"]:
        raise HTTPException(404, "unknown lane")
    return S["lanes"][lane]


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/state")
def state():
    return {"lanes": S["lanes"], "cfg": S["cfg"]}


@app.post("/fault/{name}")
def fault(name: str, lane: int = 1):
    st = _lane(lane)
    if name == "inference_stalled":
        st["pipeline"] = False
        log(lane, "ERROR", "inference worker stalled: queue depth growing, 0 frames processed")
    elif name == "camera_no_signal":
        st["camera"], st["retry"] = False, 0
        log(lane, "ERROR", "stream disconnected: no signal from camera (rtsp timeout)")
    else:
        raise HTTPException(400, f"unknown fault {name}")
    return {"ok": True, "fault": name, "lane": lane}


@app.post("/control/restart_pipeline")
def restart_pipeline(lane: int):
    st = _lane(lane)
    st["pipeline"] = True
    log(lane, "INFO", "inference pipeline restarted")
    return {"ok": True, "msg": "pipeline restarted"}


@app.post("/control/reconnect_stream")
def reconnect_stream(lane: int):
    st = _lane(lane)
    if not st["camera"]:
        log(lane, "WARN", f"reconnect failed: no signal after {RECONNECT_RETRIES} retries")
        return {"ok": False, "msg": f"no signal after {RECONNECT_RETRIES} retries"}
    log(lane, "INFO", "stream reconnected")
    return {"ok": True, "msg": "stream reconnected"}


@app.post("/control/physical_fix")
def physical_fix(lane: int):
    """模擬現場人員修好電源／PoE／網路線（POC 專用）。"""
    st = _lane(lane)
    st["camera"] = st["pipeline"] = True
    log(lane, "INFO", "camera link restored (physical fix)")
    return {"ok": True}


@app.put("/control/config")
def put_config(cfg: dict):
    S["cfg"] = cfg
    log(0, "INFO", f"config applied model={cfg.get('model')}")
    return {"ok": True}


@app.post("/control/reset")
def reset():
    for st in S["lanes"].values():
        st.update(camera=True, pipeline=True, retry=0)
    S["cfg"] = DEFAULT_CFG
    return {"ok": True}
