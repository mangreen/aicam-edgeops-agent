import pytest


def test_ingest_validates_and_stores(client, d):
    ok = {"logs": [{"ts": 1.0, "lane": 1, "level": "INFO", "msg": "hi"}],
          "metrics": [{"ts": 1.0, "lane": 1, "name": "fps", "value": 15}], "spans": []}
    assert client.post("/ingest", json=ok).status_code == 200
    assert d.obs.count_logs(1, "hi") == 1


@pytest.mark.parametrize("body", [
    {"logs": [{"ts": 1, "lane": 1, "level": "TRACE", "msg": "x"}]},                       # 非法 level
    {"logs": [{"ts": 1, "lane": 1, "level": "INFO", "msg": "x" * 2001}]},                  # 訊息過長
    {"metrics": [{"ts": 1, "lane": 999, "name": "fps", "value": 1}]},                      # lane 超出範圍
    {"logs": [{"ts": 1, "lane": 1, "level": "INFO", "msg": "x"}] * 5001},                  # 批次過大
])
def test_ingest_rejects_invalid(client, body):
    assert client.post("/ingest", json=body).status_code == 422


def test_chat_input_limits(client):
    assert client.post("/api/chat", json={"text": ""}).status_code == 422
    assert client.post("/api/chat", json={"text": "x" * 1001}).status_code == 422
    assert client.post("/api/chat", json={"text": "狀態"}).status_code == 200


def test_respond_validates_enum_and_state(client, d):
    assert client.post("/api/escalations/1/respond", json={"response": "drop table"}).status_code == 422
    assert client.post("/api/escalations/999/respond", json={"response": "fixed"}).status_code == 409


def test_status_versions_and_tools(client):
    s = client.get("/api/status").json()
    assert s["head"] == 6 and "1" in s["lanes"]
    assert [v["seq"] for v in client.get("/api/versions").json()][:2] == [6, 5]
    assert any(t["name"] == "query_logs" for t in client.get("/api/tools").json())


def test_reset_is_idempotent(client, d):
    for _ in range(2):
        assert client.post("/api/demo/reset").status_code == 200
        assert d.versions.head()["seq"] == 6 and len(d.issues.list(50)) == 4
