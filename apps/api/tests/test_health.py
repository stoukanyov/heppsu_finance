def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "AI Finance OS"


def test_health_db(client):
    r = client.get("/api/v1/health/db")
    assert r.status_code == 200
    assert r.json()["database"] == "reachable"
