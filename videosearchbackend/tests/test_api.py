import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_root_returns_service_info(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "VideoSearch API"
    assert body["health"] == "/api/v1/health"


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["environment"] == "test"  # pinned in tests/conftest.py


def test_search_returns_demo_videos(client: TestClient) -> None:
    response = client.get("/api/v1/search")
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == ""
    assert body["count"] == len(body["items"])
    assert body["count"] >= 1


def test_search_filters_by_query(client: TestClient) -> None:
    response = client.get("/api/v1/search", params={"q": "typescript"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "typescript"
    assert body["count"] >= 1
    assert all("typescript" in item["title"].lower() for item in body["items"])


def test_search_honors_limit(client: TestClient) -> None:
    response = client.get("/api/v1/search", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1  # count reflects full match set
    assert len(body["items"]) == 2


def test_search_validates_limit_range(client: TestClient) -> None:
    response = client.get("/api/v1/search", params={"limit": 0})
    assert response.status_code == 422
