from fastapi.testclient import TestClient


def test_health(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
