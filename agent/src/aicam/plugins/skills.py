"""Skill：config/skills/<name>/SKILL.md（frontmatter: name / description / tools + 內文）。

啟用清單在 [skills] enabled。若 skill 需要的 tool 被停用，該 skill 自動標為 inactive，
不會注入 prompt，避免 prompt 描述了 Agent 實際沒有的能力。
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """一份 skill（SKILL.md）；需要的工具被停用時 active=False，不會注入 prompt。"""
    name: str
    description: str
    tools: tuple
    body: str
    enabled: bool = False
    active: bool = False
    reason: str = ""


def parse_frontmatter(text: str) -> tuple[dict, str]:
    meta, body = {}, text
    if text.startswith("---"):
        _, head, body = text.split("---", 2)
        for line in head.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta, body.strip()


def load_skills(settings, registry) -> list[Skill]:
    conf = settings.section("skills")
    root = Path(conf.get("dir") or (Path(settings.config_path).parent / "skills" if settings.config_path else ""))
    enabled = set(conf.get("enabled", []))
    out = []
    if not root or not root.is_dir():
        return out
    for p in sorted(root.glob("*/SKILL.md")):
        meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        name = meta.get("name", p.parent.name)
        tools = tuple(t.strip() for t in meta.get("tools", "").split(",") if t.strip())
        sk = Skill(name, meta.get("description", ""), tools, body, enabled=name in enabled)
        missing = [t for t in tools if registry.get(t) is None]
        sk.active = sk.enabled and not missing
        sk.reason = ("未在 [skills] enabled" if not sk.enabled else f"缺少工具 {missing}" if missing else "啟用中")
        out.append(sk)
    return out
