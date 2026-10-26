"""可选 API Key 的验证规则。"""
from app.core.security import is_valid_api_key
from fastapi.testclient import TestClient

from app.main import app, settings
from app.services import session_service


def test_api_key_rules():
    assert is_valid_api_key("", "")
    assert not is_valid_api_key("", "secret")
    assert not is_valid_api_key("wrong", "secret")
    assert is_valid_api_key("secret", "secret")


def test_api_key_middleware(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "test-key")
    monkeypatch.setattr(session_service, "list_sessions", lambda: [])
    client = TestClient(app)
    assert client.get("/api/v1/sessions").status_code == 401
    response = client.get("/api/v1/sessions", headers={"X-API-Key": "test-key"})
    assert response.status_code == 200
    assert response.json() == {"sessions": []}
    assert client.get("/health").status_code == 200


def test_query_validation(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "")
    client = TestClient(app)
    assert client.get("/api/v1/search/attractions", params={"query": "景点", "top_k": 0}).status_code == 422
    assert client.post("/api/v1/chat", json={"query": ""}).status_code == 422
    assert client.post("/api/v1/import", files={"file": ("note.txt", b"text")}).status_code == 400
