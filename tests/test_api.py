from fastapi.testclient import TestClient

from app.main import app


def login_ready(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "password", "new_password": "NewPassword_2026"},
    )
    assert response.status_code == 200
    response = client.post("/api/auth/login", json={"username": "admin", "password": "NewPassword_2026"})
    assert response.status_code == 200


def test_login_password_change_and_filter_api():
    with TestClient(app) as client:
        login_ready(client)
        payload = {"entries": [{"bangumi_id": 681, "title": "哆啦A梦"}, {"bangumi_id": 3920, "title": "摩绪"}]}
        response = client.put("/api/discovery/mikan/filters/4?year=2026&season=summer", json=payload)
        assert response.status_code == 200
        assert response.json()["count"] == 2

        response = client.get("/api/discovery/mikan/filters?year=2026&season=summer&weekday=4")
        assert response.status_code == 200
        assert {entry["bangumi_id"] for entry in response.json()["entries"]} == {681, 3920}

        response = client.delete("/api/discovery/mikan/filters/4?year=2026&season=summer")
        assert response.status_code == 200
        response = client.get("/api/discovery/mikan/filters?year=2026&season=summer&weekday=4")
        assert response.json()["count"] == 0
