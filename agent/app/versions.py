"""版本快照：append-only；rollback = 新增一版（內容等於目標版）；雜湊相同不新增。"""
import hashlib, json, re

_CRED = re.compile(r"://[^/\s:\"]+:[^@\s\"]+@")


def canon(c):
    return json.dumps(c, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha(c):
    return hashlib.sha256(canon(c).encode()).hexdigest()


def merge(base, patch):
    out = json.loads(json.dumps(base))
    for k, v in patch.items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def flat(d, p=""):
    r = {}
    for k, v in d.items():
        path = f"{p}{k}"
        r.update(flat(v, path + ".") if isinstance(v, dict) else {path: v})
    return r


def diff(a: dict, b: dict):
    fa, fb = flat(a), flat(b)
    return [{"path": k, "old": fa.get(k), "new": fb.get(k)}
            for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)]


def fmt_diff(d):
    return "；".join(f"{x['path']}: {x['old']} → {x['new']}" for x in d) or "（無差異）"


def commit(store, content, actor, reason, issue_id=None, ts=None):
    """回傳 (version, changed)。快照只存機密引用，含明文憑證者拒收。"""
    if _CRED.search(canon(content)):
        raise ValueError("設定含明文憑證，請改用 ${SECRET:name} 引用")
    head, h = store.head(), sha(content)
    if head and head["sha256"] == h:
        return head, False
    return store.add(content, head["seq"] if head else None, actor, reason, issue_id, ts), True
