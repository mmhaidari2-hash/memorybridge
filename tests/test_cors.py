import importlib
import os

import pytest
from fastapi.testclient import TestClient


def load_main(monkeypatch, origins: str | None):
    if origins is None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)

    import main

    return importlib.reload(main)


def test_no_cors_header_when_origins_are_not_configured(monkeypatch):
    module = load_main(monkeypatch, None)
    client = TestClient(module.app)
    response = client.get("/health", headers={"Origin": "https://app.example.com"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_configured_origin_is_allowed(monkeypatch):
    module = load_main(monkeypatch, "https://app.example.com")
    client = TestClient(module.app)
    response = client.options(
        "/v1/account/status",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-MemoryBridge-Key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"


def test_unconfigured_origin_is_not_allowed(monkeypatch):
    module = load_main(monkeypatch, "https://app.example.com")
    client = TestClient(module.app)
    response = client.options(
        "/v1/account/status",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-MemoryBridge-Key",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_wildcard_origin_fails_closed(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    import main

    with pytest.raises(RuntimeError, match="wildcard is not allowed"):
        importlib.reload(main)
