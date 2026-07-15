"""Unit tests — no GGUF model required."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("LAZY_LOAD_MODEL", "true")
    monkeypatch.setenv("APP_ENV", "test")

    from app.config import get_settings

    get_settings.cache_clear()

    with patch("app.main.init_langfuse", return_value=None):
        with patch("app.main.setup_otel"):
            from app.main import app, llm_service

            llm_service._llm = object()  # mark model as loaded
            llm_service.chat = MagicMock(  # type: ignore[method-assign]
                return_value={
                    "response": "Paris",
                    "model": "mock.gguf",
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 2,
                        "total_tokens": 7,
                    },
                }
            )
            llm_service.load = MagicMock()  # type: ignore[method-assign]

            with TestClient(app) as c:
                yield c

    get_settings.cache_clear()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat(client):
    r = client.post("/chat", json={"message": "Capital of France?"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "Paris"
    assert "latency_ms" in body
    assert body["usage"]["total_tokens"] == 7


def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests" in r.text or "llm_chat" in r.text or "#" in r.text
