import pytest

from aicam.core import versions as V
from aicam.plugins.tools import Call, execute


async def test_apply_config_snapshots_and_pushes(d):
    n = d.versions.head()["seq"]
    r = await execute(d, "apply_config", {"patch": {"lanes": {"1": {"fps_threshold": 12}}}, "reason": "t"}, Call(actor="operator", origin="external"))
    h = d.versions.head()
    assert r["changed"] and h["seq"] == n + 1 and h["actor"] == "operator" and h["parent_seq"] == n
    assert h["content"]["lanes"]["1"]["fps_threshold"] == 12


async def test_same_hash_no_new_version(d):
    n = d.versions.head()["seq"]
    r = await execute(d, "apply_config", {"patch": {"lanes": {"1": {"fps_threshold": 10}}}, "reason": "noop"}, Call(actor="operator", origin="external"))
    assert r["changed"] is False and d.versions.head()["seq"] == n


async def test_rollback_appends_version(d):
    await execute(d, "apply_config", {"patch": {"model": "x"}, "reason": "t"}, Call(actor="engineer", origin="external"))
    h = d.versions.head(); n = h["seq"]
    r = await execute(d, "rollback_version", {"to_seq": n - 1}, Call(origin="ui", actor="operator", approved=True))
    assert r["ok"] and d.versions.head()["seq"] == n + 1                      # 新增一版，不刪歷史
    assert d.versions.head()["content"] == d.versions.get(n - 1)["content"]
    assert d.versions.get(n) is not None


async def test_rollback_blocked_without_approval(d):
    n = d.versions.head()["seq"]
    r = await execute(d, "rollback_version", {"to_seq": n - 1}, Call(origin="chat", actor="operator"))
    assert r["blocked"] == "needs_operator" and d.versions.head()["seq"] == n


def test_plaintext_credential_rejected(d):
    with pytest.raises(ValueError):
        V.commit(d.versions, {"lanes": {"1": {"rtsp": "rtsp://admin:pw123@10.0.0.5/s"}}}, "operator", "bad")


def test_seed_has_three_actors(d):
    assert {v["actor"] for v in d.versions.list(10)} == {"engineer", "operator", "agent"} and d.versions.head()["seq"] == 6
