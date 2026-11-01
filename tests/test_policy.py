import time
from app import policy

NOW = time.time()
HEAD = {"seq": 7, "parent_seq": 6, "actor": "engineer", "issue_id": None}


def ctx(**k): return {"now": NOW, "recent": [], "head": HEAD, "origin": "agent", "issue_id": 1, **k}


def test_l0_allow():
    assert policy.evaluate("query_logs", {}, ctx()).verdict == "allow"


def test_l1_rate_limit():
    rec = [{"tool": "restart_pipeline", "lane": 1, "ts": NOW - 30}] * 2
    assert policy.evaluate("restart_pipeline", {"lane": 1}, ctx(recent=rec[:1])).verdict == "allow"
    assert policy.evaluate("restart_pipeline", {"lane": 1}, ctx(recent=rec)).verdict == "deny"
    assert policy.evaluate("restart_pipeline", {"lane": 2}, ctx(recent=rec)).verdict == "allow"   # 不同車道
    old = [{"tool": "restart_pipeline", "lane": 1, "ts": NOW - 700}] * 2
    assert policy.evaluate("restart_pipeline", {"lane": 1}, ctx(recent=old)).verdict == "allow"   # 窗口外


def test_l3_escalates():
    assert policy.evaluate("firmware_update", {}, ctx()).verdict == "escalate_engineer"


def test_l2_needs_operator_unless_approved():
    assert policy.evaluate("reboot_device", {}, ctx()).verdict == "needs_operator"
    assert policy.evaluate("reboot_device", {}, ctx(approved=True)).verdict == "allow"


def test_rollback_own_change_is_l1():
    h = {**HEAD, "actor": "agent", "issue_id": 1}
    assert policy.evaluate("rollback_version", {"to_seq": 6}, ctx(head=h)).verdict == "allow"


def test_rollback_others_change_needs_evidence():
    assert policy.evaluate("rollback_version", {"to_seq": 6}, ctx()).verdict == "needs_operator"
    assert policy.evaluate("rollback_version", {"to_seq": 6, "evidence": "偵測數 14→0"}, ctx()).verdict == "allow"


def test_rollback_older_or_user_request_needs_operator():
    assert policy.evaluate("rollback_version", {"to_seq": 4, "evidence": "x"}, ctx()).verdict == "needs_operator"
    assert policy.evaluate("rollback_version", {"to_seq": 6, "evidence": "x"}, ctx(origin="chat")).verdict == "needs_operator"
    assert policy.evaluate("rollback_version", {"to_seq": 4}, ctx(origin="chat", approved=True)).verdict == "allow"
