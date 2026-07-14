from fastapi.testclient import TestClient

from app.main import app


def test_health_is_safe_by_default() -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "execution": "disabled"}


def test_dashboard_status_and_learning_are_read_only() -> None:
    client = TestClient(app)
    status = client.get("/api/v1/system/status")
    assert status.status_code == 200
    assert status.json()["execution_enabled"] is False
    learning = client.get("/api/v1/learning")
    assert learning.status_code == 200
    assert "insufficient_data" in learning.json()
