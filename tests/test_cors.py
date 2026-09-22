import base64
import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz")
os.environ.setdefault("TOKEN_HASH_PEPPER", base64.b64encode(b"p" * 32).decode("ascii"))

from app.config import clear_settings_cache, get_settings


def test_cors_origins_never_star_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://memorybridge-api-production.up.railway.app")
    clear_settings_cache()
    origins = get_settings().cors_origins
    assert "*" not in origins
    assert "https://memorybridge-api-production.up.railway.app" in origins
    assert "http://localhost:5173" in origins


def test_cors_origins_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    clear_settings_cache()
    with pytest.raises(RuntimeError, match="cannot be '\\*'"):
        get_settings()


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "https://memorybridge-api-production.up.railway.app, http://localhost:5173/",
    )
    clear_settings_cache()
    assert get_settings().cors_origins == (
        "https://memorybridge-api-production.up.railway.app",
        "http://localhost:5173",
    )
