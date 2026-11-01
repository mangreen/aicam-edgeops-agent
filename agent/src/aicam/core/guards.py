"""Guard pipeline：依 [guards.<stage>] chain 依序執行；block 立即中止，redact 串接，flag 累積。"""
from dataclasses import dataclass, field

STAGES = ("input", "output", "content")
REFUSAL = {"input": "（已被安全檢查阻擋）{reason}", "output": "（回覆已被輸出檢查攔截）{reason}",
           "content": "（外部內容已被攔截）{reason}"}


@dataclass
class Outcome:
    action: str                       # allow | block | redact | flag
    text: str
    hits: list = field(default_factory=list)

    @property
    def blocked(self): return self.action == "block"

    @property
    def flagged(self): return any(h.action == "flag" for h in self.hits)


class GuardPipeline:
    def __init__(self, chains: dict, on_hit=None):
        self.chains, self.on_hit = chains, on_hit

    def describe(self) -> dict:
        return {st: [g.name for g in chain] for st, chain in self.chains.items()}

    def run(self, stage: str, text: str, ctx: dict | None = None) -> Outcome:
        ctx = ctx or {}
        out, action, hits = text, "allow", []
        for g in self.chains.get(stage, []):
            r = g.check(stage, out, ctx)
            if r.action == "allow":
                continue
            hits.append(r)
            if self.on_hit:
                self.on_hit(stage, r, ctx)
            if r.action == "block":
                return Outcome("block", REFUSAL[stage].format(reason=r.reason), hits)
            out = r.text
            action = "redact" if r.action == "redact" and action != "flag" else ("flag" if r.action == "flag" else action)
        return Outcome(action, out, hits)
