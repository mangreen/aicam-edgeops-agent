"""Agent loop：Detect → Triage → Plan → Policy Gate → Execute → Verify → Report / 升級。"""
import asyncio
import json
import time

from aicam.core import versions as V
from aicam.core.constants import HINT, KIND_ZH
from aicam.core.executor import Call, execute
from aicam.core.untrusted import wrap


class Agent:
    """Agent loop：偵測 → Triage → 規劃 → Policy Gate → 執行 → Verify → 報告／升級。

    狀態（issues.status）：detected → triaging → acting → verifying → resolved；
    失敗路徑：waiting_operator →（Operator 無法處理／逾時）→ escalated_engineer → resolved。
    設計重點：LLM 只提案，Policy Gate 決定能否執行；動作後一定 Verify；每條車道同時最多一個 open issue；
    L1 動作失敗 2 次、被 Policy 擋下、或 rollback Verify 失敗，一律升級而不是重試。"""
    def __init__(self, d):
        self.d, self.tasks, self.last_close = d, {}, {}

    def ev(self, iid, type_, text):
        self.d.issues.event(iid, type_, text)

    # ---------- Detect ----------
    def classify(self, lane):
        n, since = self.d.s.detect_samples, max(self.last_close.get(lane, 0), time.time() - self.d.s.detector.window_sec)
        g = {k: self.d.obs.metrics(lane, k, since, limit=n) for k in ("stream_connected", "fps", "detections_per_min")}
        if any(len(v) < n for v in g.values()):
            return None
        if all(x["value"] == 0 for x in g["stream_connected"]): return "camera_no_signal"
        if all(x["value"] == 0 for x in g["fps"]): return "inference_stalled"
        if all(x["value"] < self.d.s.detector.min_detections for x in g["detections_per_min"]): return "detection_drop"
        return None

    async def tick(self):
        new = []
        for lane in self.d.s.lanes:
            if self.d.issues.list(1, lane=lane, open_only=True):
                continue
            kind = self.classify(lane)
            if kind:
                iid = self.d.issues.create(lane, kind)
                self.ev(iid, "detect", f"偵測到 Lane {lane}「{KIND_ZH[kind]}」（規則：連續 {self.d.s.detect_samples} 筆樣本異常）")
                self.tasks[iid] = t = asyncio.create_task(self.handle(iid))
                new.append(t)
        return new

    async def run_forever(self):
        while True:
            try:
                await self.tick()
            except Exception as e:
                print("detector error:", e)
            await asyncio.sleep(2)

    def cancel_all(self):
        for t in self.tasks.values(): t.cancel()
        self.tasks.clear(); self.last_close.clear()

    # ---------- 主流程 ----------
    async def handle(self, iid):
        try:
            await self._handle(iid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.ev(iid, "error", f"Agent 內部錯誤：{type(e).__name__}: {e}，升級遠端工程師")
            await self._engineer(iid)

    async def _handle(self, iid):
        d, issue = self.d, self.d.issues.get(iid)
        lane, kind, call = issue["lane"], issue["kind"], Call(issue_id=iid)
        d.issues.update(iid, status="triaging")
        self.ev(iid, "triage", "Triage：查 logs / metrics / traces、相似 issue 與 runbook")
        tri_raw = [(await execute(d, "query_logs", {"lane": lane, "since_hours": 0.1, "limit": 5}, call))["summary"],
               (await execute(d, "query_metrics", {"lane": lane, "name": "fps", "since_hours": 0.1}, call))["summary"],
               (await execute(d, "query_traces", {"lane": lane, "status": "error", "since_hours": 0.1}, call))["summary"],
               (await execute(d, "search_issues", {"kind": kind, "lane": lane}, call))["summary"],
               (await execute(d, "search_knowledge", {"query": kind}, call))["summary"]]
        tri = [self._untrusted(iid, f"triage-{i}", t)[0] for i, t in enumerate(tri_raw)]
        suspect = self.find_suspect(lane, issue["created"]) if kind == "detection_drop" else None
        if suspect:
            self.ev(iid, "triage", f"關聯變更：v{suspect['seq']}（{suspect['actor']}）{suspect['diff']}；{suspect['evidence']}")
        history = []
        for _ in range(3):
            plan = await self._plan(iid, {"kind": kind, "lane": lane, "triage": tri, "suspect": suspect, "history": history,
                                          "available_tools": d.tools.names(plannable=True)})
            if plan["tool"] == "escalate":
                self.ev(iid, "plan", f"規劃：升級（{plan.get('rationale', '')}）")
                break
            self.ev(iid, "plan", f"規劃[{d.llm.name}]：{plan['tool']} {json.dumps(plan['args'], ensure_ascii=False)} — {plan.get('rationale', '')}")
            since = time.time()
            d.issues.update(iid, status="acting")
            res = await execute(d, plan["tool"], plan["args"], call)
            if res.get("blocked"):
                break
            if res.get("ok"):
                d.issues.update(iid, status="verifying")
                ok = await self.verify(iid, [lane], since)
            else:
                ok = False
                self.ev(iid, "verify", f"Verify：動作失敗（{res.get('summary')}），無需等待")
            history.append({"tool": plan["tool"], "ok": ok})
            if ok:
                return await self.resolve(iid, "agent", f"Agent 自動修復：{plan['tool']} 後指標恢復", suspect)
            if plan["tool"] == "rollback_version":
                break                                  # Verify 失敗不重複 rollback
        await self._operator(iid)

    def _untrusted(self, iid, source, text):
        """log／網頁等外部內容：先過 content guard，再包上 <untrusted> 標記才能進入 LLM。"""
        out = self.d.guards.run("content", text, {"issue_id": iid})
        return wrap(source, out.text), out.flagged

    async def _plan(self, iid, ctx):
        try:
            p = await self.d.llm.plan(ctx)
            p.setdefault("args", {})
            return p
        except Exception as e:
            self.ev(iid, "error", f"LLM plan 失敗（{type(e).__name__}），改用 Mock 規則")
            return await self.d.llm.mock.plan(ctx)

    def find_suspect(self, lane, created):
        d, dc = self.d, self.d.s.detector
        head = d.versions.head()
        if not head or head["parent_seq"] is None or head["ts"] < created - dc.suspect_window_sec:
            return None
        parent = d.versions.get(head["parent_seq"])
        rel = [x for x in V.diff(parent["content"], head["content"])
               if x["path"].startswith(f"lanes.{lane}.") or not x["path"].startswith("lanes.")]
        rows = d.obs.metrics(lane, "detections_per_min", head["ts"] - dc.suspect_window_sec)
        b = [r["value"] for r in rows if r["ts"] <= head["ts"]]
        a = [r["value"] for r in rows if r["ts"] > head["ts"]]
        if not (rel and a and b) or sum(a) / len(a) > dc.drop_ratio * sum(b) / len(b):
            return None
        return {"seq": head["seq"], "parent_seq": head["parent_seq"], "actor": head["actor"],
                "diff": V.fmt_diff(rel),
                "evidence": f"偵測數 {sum(b)/len(b):.1f} → {sum(a)/len(a):.1f}/min（v{head['seq']} 前後對照）"}

    # ---------- Verify ----------
    def healthy(self, lane, since):
        g = {k: self.d.obs.metrics(lane, k, since) for k in ("stream_connected", "fps", "detections_per_min")}
        return (all(len(v) >= self.d.s.detector.healthy_min_samples for v in g.values()) and all(x["value"] == 1 for x in g["stream_connected"])
                and all(x["value"] > 0 for x in g["fps"]) and all(x["value"] >= self.d.s.detector.min_detections for x in g["detections_per_min"]))

    async def verify(self, iid, lanes, since):
        await asyncio.sleep(self.d.s.verify_wait)
        ok = all(self.healthy(ln, since) for ln in lanes)
        self.ev(iid, "verify", f"Verify：重查指標 → {'恢復正常 ✔' if ok else '仍異常 ✘'}")
        return ok

    # ---------- 結案 / 升級 ----------
    async def resolve(self, iid, by, outcome, suspect=None):
        d, issue = self.d, self.d.issues.get(iid)
        ctx = {"issue": issue, "actions": d.issues.actions(iid), "outcome": outcome, "suspect": suspect}
        try:
            report = await d.llm.report(ctx)
        except Exception:
            report = await d.llm.mock.report(ctx)
        report = d.guards.run("output", report, {"issue_id": iid, "system_prompt": d.prompts.compose("agent"),
                                                  "canary": d.prompts.canary}).text
        d.issues.update(iid, status="resolved", closed=time.time(), resolved_by=by, summary=outcome)
        self.last_close[issue["lane"]] = time.time()
        self.ev(iid, "report", report)
        d.kb.index(f"Issue #{iid} Lane {issue['lane']} {issue['kind']}", report, "issue")

    async def _wait(self, eid, timeout):
        end = time.time() + timeout if timeout else None
        while True:
            e = self.d.issues.esc_get(eid)
            if e["status"] != "pending":
                return e["response"]
            if end and time.time() > end:
                self.d.issues.esc_respond(eid, "timeout", "expired")
                return "timeout"
            await asyncio.sleep(0.4)

    async def _operator(self, iid):
        d, issue = self.d, self.d.issues.get(iid)
        lane, kind, to = issue["lane"], issue["kind"], d.s.operator_timeout
        text = f"Lane {lane}「{KIND_ZH[kind]}」自動修復未成功。{HINT[kind]}。"
        eid = d.issues.esc_create(iid, "operator", "assist", text, {"lane": lane}, timeout=to)
        d.issues.update(iid, status="waiting_operator")
        d.notifier.notify("operator", {"issue": iid, "text": text})
        self.ev(iid, "escalate", f"升級給 Operator（#{eid}）：{text}（{to:g} 秒內未回應將呼叫遠端工程師）")
        resp = await self._wait(eid, to)
        if resp == "fixed":
            since = time.time()
            await d.edge.physical_fix(lane)      # POC：模擬現場修復
            self.ev(iid, "operator", "Operator 回報「已處理」（POC：模擬現場修復）")
            if await self.verify(iid, [lane], since):
                return await self.resolve(iid, "operator", "Operator 現場處理後恢復")
            self.ev(iid, "operator", "Operator 處理後仍異常")
        else:
            self.ev(iid, "operator", "Operator 回報「無法處理」" if resp == "cannot" else "Operator 逾時未回應")
        await self._engineer(iid)

    async def _engineer(self, iid):
        d, issue = self.d, self.d.issues.get(iid)
        lane, kind = issue["lane"], issue["kind"]
        ctx = {"issue": issue, "actions": d.issues.actions(iid), "outcome": "未能自動修復，已升級遠端工程師", "suspect": None}
        try:
            summary = await d.llm.report(ctx)
        except Exception:
            summary = await d.llm.mock.report(ctx)
        bundle = {"issue": {k: issue[k] for k in ("id", "lane", "kind", "created")}, "summary": summary,
                  "timeline": [f"{e['type']}: {e['text'][:160]}" for e in d.issues.events(issue_id=iid)],
                  "actions": [{k: a[k] for k in ("tool", "args", "status", "level")} for a in d.issues.actions(iid)],
                  "recent_logs": [f"{l['level']} {l['msg']}" for l in d.obs.logs(lane, since=time.time() - 600, limit=10)],
                  "versions": [{"seq": v["seq"], "actor": v["actor"], "reason": v["reason"]} for v in d.versions.list(3)],
                  "suggestion": HINT[kind]}
        eid = d.issues.esc_create(iid, "engineer", "bundle", f"Lane {lane}「{KIND_ZH[kind]}」需遠端介入", bundle)
        d.issues.update(iid, status="escalated_engineer")
        d.notifier.notify("engineer", {"issue": iid, "bundle_escalation": eid})
        self.ev(iid, "escalate", f"已呼叫遠端工程師（#{eid}）：incident bundle 已送出（摘要、時間軸、已嘗試動作、logs、建議下一步）")
        if await self._wait(eid, None) == "fixed":
            since = time.time()
            await d.edge.physical_fix(lane)
            self.ev(iid, "engineer", "遠端工程師回報「已修復」（POC：模擬）")
            ok = await self.verify(iid, [lane], since)
            await self.resolve(iid, "engineer", "遠端工程師處理後恢復" if ok else "遠端工程師已處理，仍需觀察")
