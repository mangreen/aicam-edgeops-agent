import time

from aicam.core import policy

NOW = time.time()
HEAD = {"seq": 7, "parent_seq": 6, "actor": "engineer", "issue_id": None}
LV = {"query_logs": "L0", "restart_pipeline": "L1", "apply_config": "L1", "rollback_version": "L1",
      "reboot_device": "L2", "firmware_update": "L3"}


def ev(tool, args, **k):
    """模擬 executor：等級取自 manifest（LV），其餘為 ctx。"""
    ctx = {"now": NOW, "recent": [], "head": HEAD, "origin": "agent", "issue_id": 1, "level": LV.get(tool),
           "agent_writable": ("lanes.*.decoder_profile",), "patch_keys": [], **k}
    return policy.evaluate(tool, args, ctx).verdict


def test_l0_allow():
    assert ev("query_logs", {}) == "allow"


def test_undeclared_level_is_denied():
    assert ev("mystery_tool", {}) == "deny"


def test_l1_rate_limit():
    rec = [{"tool": "restart_pipeline", "lane": 1, "ts": NOW - 30}] * 2
    assert ev("restart_pipeline", {"lane": 1}, recent=rec[:1]) == "allow"
    assert ev("restart_pipeline", {"lane": 1}, recent=rec) == "deny"
    assert ev("restart_pipeline", {"lane": 2}, recent=rec) == "allow"       # 不同車道
    old = [{"tool": "restart_pipeline", "lane": 1, "ts": NOW - 700}] * 2
    assert ev("restart_pipeline", {"lane": 1}, recent=old) == "allow"       # 窗口外


def test_l3_escalates():
    assert ev("firmware_update", {}) == "escalate_engineer"


def test_l2_needs_operator_unless_approved():
    assert ev("reboot_device", {}) == "needs_operator"
    assert ev("reboot_device", {}, approved=True) == "allow"


def test_rollback_own_change_is_l1():
    assert ev("rollback_version", {"to_seq": 6}, head={**HEAD, "actor": "agent", "issue_id": 1}) == "allow"


def test_rollback_others_change_needs_evidence():
    assert ev("rollback_version", {"to_seq": 6}) == "needs_operator"
    assert ev("rollback_version", {"to_seq": 6}, evidence_verified=True) == "allow"       # 證據由程式碼驗證，不看 LLM 參數
    assert ev("rollback_version", {"to_seq": 6, "evidence": "偵測數 14→0"}) == "needs_operator"   # LLM 自填的字串無效


def test_rollback_older_or_user_request_needs_operator():
    assert ev("rollback_version", {"to_seq": 4}, evidence_verified=True) == "needs_operator"
    assert ev("rollback_version", {"to_seq": 6}, evidence_verified=True, origin="chat") == "needs_operator"
    assert ev("rollback_version", {"to_seq": 4}, origin="chat", approved=True) == "allow"


def test_agent_apply_config_whitelist():
    ok = ["lanes.1.decoder_profile"]
    assert ev("apply_config", {}, actor="agent", patch_keys=ok) == "allow"
    assert ev("apply_config", {}, actor="agent", patch_keys=ok + ["lanes.1.roi"]) == "needs_operator"
    assert ev("apply_config", {}, actor="agent", patch_keys=["model"], approved=True) == "allow"
    assert ev("apply_config", {}, actor="engineer", patch_keys=["model"]) == "allow"    # 他人變更只記錄來源
