"""內建規則式 guard（可離線、決定性）。需要 LLM 判官時，另寫 adapter 並在 [guards] 設定掛上。"""
import re

from aicam.ports.guard import GuardResult

_F = re.I | re.S

INJECTION = [
    r"ignore (all |any )?(the )?(previous|above|prior|earlier) (instructions|rules|prompts?)",
    r"disregard .{0,30}(instructions|rules)",
    r"(reveal|show|print|repeat|leak).{0,30}(system|hidden|initial) (prompt|instructions)",
    r"developer mode|jailbreak|\bDAN\b|act as (an? )?(unrestricted|jailbroken)",
    r"忽略(以上|上面|前面|先前|之前|所有).{0,8}(指令|規則|提示|限制)",
    r"(顯示|輸出|告訴我|洩漏|印出|重複).{0,10}(系統提示|system prompt|提示詞)",
    r"(你現在是|從現在起你是).{0,20}(不受限|沒有限制|駭客|管理員)",
    r"(無視|繞過|關閉|停用).{0,6}(policy|策略|安全|防護|guard|檢查)",
]
ROLE_DENY = [
    r"(刪除|清空|drop|truncate|delete).{0,12}(資料|logs?|table|database|版本|history|紀錄)",
    r"(關閉|停用|禁用|disable|turn off).{0,12}(policy|策略|guard|安全|檢查|防護)",
    r"\b(ssh|sudo|rm\s+-rf|chmod)\b",
    r"(api[ _-]?key|token|密碼|金鑰|secret|private key)",
    r"(修改|更改|編輯|change|edit).{0,10}(prompt|提示詞|system prompt|設定檔|config)",
]
CONTENT_EXTRA = [
    r"(execute|run|call|invoke|執行|呼叫).{0,25}(reboot_device|firmware_update|ssh_exec|rollback|apply_config|restart|disable|policy)",
    r"\bsystem\s*:|<\s*/?\s*(system|instructions?)\s*>",
    r"(do not|don't|不要|別).{0,10}(tell|inform|告訴|通知).{0,10}(operator|user|使用者)",
]
SECRETS = [
    r"sk-[A-Za-z0-9_\-]{16,}", r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}", r"(?i)(api[_-]?key|token|password|passwd|secret)\s*[:=]\s*\S{6,}",
    r"rtsp://[^/\s:]+:[^@\s]+@",
]
UNSAFE_CMD = [r"rm\s+-rf\s+\S+", r"curl[^|\n]*\|\s*(sh|bash)", r"chmod\s+777", r"(?i)drop\s+table", r"mkfs\.\w+"]


def _first(patterns, text):
    for p in patterns:
        if (m := re.search(p, text, _F)):
            return m.group(0)[:60]
    return None


class Length:
    name = "length"

    def __init__(self, conf): self.max = int(conf.get("max_chars", 1000))

    def check(self, stage, text, ctx):
        if len(text) > self.max:
            return GuardResult("block", text, f"輸入過長（{len(text)} > {self.max}）", self.name)
        return GuardResult("allow", text, guard=self.name)


class Injection:
    name = "injection"

    def __init__(self, conf): self.patterns = INJECTION + list(conf.get("extra", []))

    def check(self, stage, text, ctx):
        if (hit := _first(self.patterns, text)):
            return GuardResult("block", text, f"疑似 prompt injection：「{hit}」", self.name)
        return GuardResult("allow", text, guard=self.name)


class RoleScope:
    """Operator 可用範圍：越權意圖（刪資料、關安全機制、索取機密、改 prompt/設定、ssh）一律阻擋。"""
    name = "role_scope"

    def __init__(self, conf): self.patterns = list(conf.get("deny", ROLE_DENY))

    def check(self, stage, text, ctx):
        if (hit := _first(self.patterns, text)):
            return GuardResult("block", text, f"超出 Operator 可用範圍：「{hit}」", self.name)
        return GuardResult("allow", text, guard=self.name)


class SecretRedact:
    name = "secret_redact"

    def __init__(self, conf): ...

    def check(self, stage, text, ctx):
        out = text
        for p in SECRETS:
            out = re.sub(p, "[已遮罩機密]", out)
        return GuardResult("redact" if out != text else "allow", out, "輸出含疑似機密，已遮罩" if out != text else "", self.name)


class PromptLeak:
    """輸出含 canary 或與 system prompt 逐行雷同（≥24 字）→ 阻擋。"""
    name = "prompt_leak"

    def __init__(self, conf): ...

    def check(self, stage, text, ctx):
        sp = ctx.get("system_prompt", "")
        canary = ctx.get("canary")
        if canary and canary in text:
            return GuardResult("block", text, "輸出含 system prompt canary", self.name)
        for line in sp.splitlines():
            line = line.strip()
            if len(line) >= 24 and line in text:
                return GuardResult("block", text, "輸出疑似洩漏 system prompt", self.name)
        return GuardResult("allow", text, guard=self.name)


class UnsafeCommand:
    name = "unsafe_command"

    def __init__(self, conf): ...

    def check(self, stage, text, ctx):
        out = text
        for p in UNSAFE_CMD:
            out = re.sub(p, "[已移除危險指令]", out)
        return GuardResult("redact" if out != text else "allow", out, "輸出含危險指令，已移除" if out != text else "", self.name)


class ContentInjection:
    """外部內容（log、第三方輸出）含指令式文字 → flag：內容只當證據，Agent 不得據以行動。"""
    name = "content_injection"

    def __init__(self, conf): self.patterns = INJECTION + CONTENT_EXTRA + list(conf.get("extra", []))

    def check(self, stage, text, ctx):
        if (hit := _first(self.patterns, text)):
            return GuardResult("flag", text, f"外部內容含指令式文字：「{hit}」", self.name)
        return GuardResult("allow", text, guard=self.name)


BUILTIN = {c.name: c for c in (Length, Injection, RoleScope, SecretRedact, PromptLeak, UnsafeCommand, ContentInjection)}
