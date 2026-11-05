"""A2：/ingest 的輸入邊界、NULL 防護、交易失敗後可恢復、events 上限。"""
import sqlite3
import time

import pytest

from aicam.core.loop import Agent
from conftest import emit

H = {"content-type": "application/json"}


def body(metric=None, log=None, span=None):
    now = time.time()
    return {"metrics": [{"ts": now, "lane": 1, "name": "fps", "value": 15, **(metric or {})}] if metric is not None else [],
            "logs": [{"ts": now, "lane": 1, "level": "INFO", "msg": "x", **(log or {})}] if log is not None else [],
            "spans": [{"trace_id": "t", "span_id": "s", "parent_id": None, "name": "infer", "lane": 1, "ts": now,
                       "dur_ms": 5, "status": "ok", **(span or {})}] if span is not None else []}


@pytest.mark.parametrize("raw", [
    '{"metrics":[{"ts":%(now)s,"lane":1,"name":"fps","value":NaN}]}',
    '{"metrics":[{"ts":%(now)s,"lane":1,"name":"fps","value":Infinity}]}',
    '{"metrics":[{"ts":NaN,"lane":1,"name":"fps","value":1}]}',
    '{"logs":[{"ts":-Infinity,"lane":1,"level":"INFO","msg":"x"}]}',
    '{"spans":[{"trace_id":"t","span_id":"s","name":"n","lane":1,"ts":%(now)s,"dur_ms":NaN,"status":"ok"}]}',
])
def test_non_finite_numbers_are_rejected(client, d, raw):
    r = client.post("/ingest", content=raw % {"now": time.time()}, headers=H)
    assert r.status_code == 422
    assert d.db.q("SELECT COUNT(*) n FROM metrics WHERE value IS NULL")[0]["n"] == 0


def test_negative_span_duration_rejected(client):
    assert client.post("/ingest", json=body(span={"dur_ms": -1})).status_code == 422


@pytest.mark.parametrize("offset", [30 * 365 * 86400, -(31 * 86400), 3600])
def test_timestamp_out_of_range_rejected(client, d, offset):
    r = client.post("/ingest", json=body(metric={"ts": time.time() + offset}))
    assert r.status_code == 422 and "ts 超出允許範圍" in r.json()["detail"]
    assert d.db.q("SELECT COUNT(*) n FROM metrics WHERE ts>?", (time.time() + 100,))[0]["n"] == 0


def test_timestamp_range_applies_to_every_table_and_whole_batch(client, d):
    far = time.time() + 10 * 365 * 86400
    b = body(metric={}, log={"ts": far}, span={})
    assert client.post("/ingest", json=b).status_code == 422
    assert d.obs.count_logs(1, "x") == 0 and d.db.q("SELECT COUNT(*) n FROM metrics WHERE ts>?", (time.time() - 5,))[0]["n"] == 0   # 整批拒絕


def test_valid_batch_with_slight_clock_skew_accepted(client):
    assert client.post("/ingest", json=body(metric={"ts": time.time() + 60}, log={}, span={})).status_code == 200


def test_failed_batch_rolls_back_and_connection_stays_usable(d):
    """修復前：欄位數錯誤的批次讓連線卡在交易中，之後所有寫入都報 cannot start a transaction。"""
    with pytest.raises(sqlite3.Error):
        d.db.many("INSERT INTO metrics VALUES(?,?,?,?)", [(1, 2)])
    d.db.many("INSERT INTO metrics VALUES(?,?,?,?)", [(time.time(), 1, "fps", 1.0)])                # 之後仍可寫入
    assert d.db.q("SELECT COUNT(*) n FROM metrics WHERE name='fps' AND lane=1 AND value=1.0 AND ts>?", (time.time() - 5,))[0]["n"] == 1


def test_ingest_is_atomic_across_tables(d):
    now = time.time()
    good_log = {"ts": now, "lane": 1, "level": "INFO", "msg": "atomic-marker"}
    bad_metric = {"ts": now, "lane": 1, "name": None, "value": 1}                                   # name=None 違反 NOT NULL? 以欄位數錯誤確保失敗
    del bad_metric["value"]
    with pytest.raises((sqlite3.Error, KeyError)):
        d.obs.ingest([good_log], [bad_metric], [])
    assert d.obs.count_logs(1, "atomic-marker") == 0                                                # logs 也一併 rollback
    d.obs.ingest([good_log], [], [])                                                                # 連線仍正常
    assert d.obs.count_logs(1, "atomic-marker") == 1


def test_null_metric_values_do_not_break_detection(d, agent):
    emit(d, 1, n=3)
    d.db.x("UPDATE metrics SET value=NULL WHERE lane=1 AND ts>?", (time.time() - 5,))               # 舊資料或外部寫入留下的 NULL
    assert agent.classify(1) is None                                                                # 不再丟 TypeError
    assert isinstance(agent, Agent)


def test_events_limit_is_capped_and_returns_latest(client, d):
    for i in range(30):
        d.issues.event(None, "tool", f"e{i}")
    assert client.get("/api/events?limit=501").status_code == 422
    assert client.get("/api/events?limit=0").status_code == 422
    rows = client.get("/api/events?limit=5").json()
    assert [r["text"] for r in rows] == ["e25", "e26", "e27", "e28", "e29"]                          # 最近 5 筆，由舊到新
    after = rows[0]["id"]
    assert [r["text"] for r in client.get(f"/api/events?after={after}&limit=2").json()] == ["e26", "e27"]
