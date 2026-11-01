"""POC 專用：預先 seed 7 天歷史資料（版本史 v1~v6、metrics、incident logs、issues、對話）。"""
import json, math, time
from pathlib import Path
from . import versions as V

DAY, H = 86400, 3600
BASE = {"model": "vehicle-det-1.1.0", "policy": {"l1_max_per_10min": 2},
        "lanes": {str(i): {"roi": [100, 180, 600, 280], "fps_threshold": 8, "rtsp": "${SECRET:cam%d}" % i} for i in (1, 2)}}
VERS = [  # (距今天數, actor, reason, patch)
    (7.0, "engineer", "初始部署", {}),
    (6.5, "engineer", "Lane 1 ROI 校正", {"lanes": {"1": {"roi": [120, 200, 640, 300]}}}),
    (5.0, "operator", "Lane 2 fps 門檻調整", {"lanes": {"2": {"fps_threshold": 10}}}),
    (4.0, "agent", "inference_stalled 後調整 Lane 1 fps 門檻", {"lanes": {"1": {"fps_threshold": 10}}}),
    (2.0, "engineer", "模型升級 1.1.0 → 1.2.0", {"model": "vehicle-det-1.2.0"}),
    (1.0, "operator", "Lane 2 ROI 校正", {"lanes": {"2": {"roi": [120, 200, 640, 300]}}}),
]
# (距今天數, lane, kind, 持續分鐘, 處置者, 摘要)
ISSUES = [
    (5.2, 1, "camera_no_signal", 40, "operator", "Operator 重新插拔 PoE 線後恢復"),
    (4.1, 2, "inference_stalled", 6, "agent", "Agent 自動修復：restart_pipeline 後指標恢復"),
    (3.0, 1, "inference_stalled", 5, "agent", "Agent 自動修復：restart_pipeline 後指標恢復"),
    (1.5, 1, "camera_no_signal", 180, "engineer", "遠端工程師更換 PoE switch 埠後恢復"),
]
BLIPS = [6.1, 2.6, 0.7]   # Lane 1 短暫斷線（自行恢復）
MSGS = [(2.2, "user", "Lane 2 昨天 FPS 為什麼掉了一下？"),
        (2.2, "assistant", "Lane 2 在 4 天前發生 inference_stalled，Agent 重啟 pipeline 後 6 分鐘內恢復（issue #2）。"),
        (1.1, "user", "Lane 1 的 PoE 問題後來怎麼處理？"),
        (1.1, "assistant", "Lane 1 camera_no_signal（issue #4）由遠端工程師更換 PoE switch 埠後恢復；建議定期檢查該 switch。")]


def run(d, force=False):
    if d.versions.head() and not force:
        return
    now = time.time()
    cfg = BASE
    for ago, actor, reason, patch in VERS:
        cfg = V.merge(cfg, patch)
        V.commit(d.versions, cfg, actor, reason, None, now - ago * DAY)
    down = [(now - a * DAY, now - a * DAY + m * 60, ln, k) for a, ln, k, m, *_ in ISSUES]
    logs, metrics, spans = [], [], []
    for ts in range(int(now - 7 * DAY), int(now - 300), 300):
        f = max(0.35, math.sin(math.pi * ((ts % DAY) / H - 6) / 12 + 0.01))
        for ln in (1, 2):
            cam = all(not (s <= ts <= e and l == ln and k == "camera_no_signal") for s, e, l, k in down)
            stall = any(s <= ts <= e and l == ln and k == "inference_stalled" for s, e, l, k in down)
            ok = cam and not stall
            metrics += [{"ts": ts, "lane": ln, "name": "fps", "value": 15.0 if ok else 0.0},
                        {"ts": ts, "lane": ln, "name": "stream_connected", "value": 1.0 if cam else 0.0},
                        {"ts": ts, "lane": ln, "name": "detections_per_min", "value": round(14 * f, 1) if ok else 0.0}]
    for (s, e, ln, k), (_, _, _, _, by, summ) in zip(down, ISSUES):
        msg = "stream disconnected: no signal from camera (rtsp timeout)" if k == "camera_no_signal" else \
              "inference worker stalled: queue depth growing, 0 frames processed"
        logs += [{"ts": s, "lane": ln, "level": "ERROR", "msg": msg},
                 {"ts": e, "lane": ln, "level": "INFO", "msg": "camera link restored" if k == "camera_no_signal" else "inference pipeline restarted"}]
        spans.append({"trace_id": f"seed{int(s)}", "span_id": f"s{int(s)}", "parent_id": None, "name": "capture" if k == "camera_no_signal" else "infer",
                      "lane": ln, "ts": s, "dur_ms": 5000, "status": "error"})
        iid = d.issues.create(ln, k)
        d.issues.update(iid, status="resolved", created=s, closed=e, resolved_by=by, summary=summ)
        d.kb.index(f"Issue #{iid} Lane {ln} {k}", f"{summ}（持續 {int((e - s) / 60)} 分鐘）", "issue")
    for a in BLIPS:
        t = now - a * DAY
        logs += [{"ts": t, "lane": 1, "level": "WARN", "msg": "stream disconnected: brief packet loss"},
                 {"ts": t + 20, "lane": 1, "level": "INFO", "msg": "stream reconnected"}]
    d.obs.ingest(logs, metrics, spans)
    for ago, role, text in MSGS:
        d.issues.msg_add(role, text, "default", now - ago * DAY)
    for p in sorted(Path(__file__).resolve().parent.parent.joinpath("runbooks").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        d.kb.index(t.splitlines()[0].lstrip("# "), t, "runbook")
