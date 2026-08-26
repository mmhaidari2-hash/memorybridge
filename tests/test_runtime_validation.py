import base64
import importlib
import os

import pytest

from app.runtime_validation import validate_runtime_config


VALID_KEY = base64.b64encode(b"x" * 32).decode()


def set_valid_production(monkeypatch, mode="test"):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://memorybridge:secret@db.internal:5432/memorybridge")
    monkeypatch.setenv("ENCRYPTION_KEY", VALID_KEY)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.memorybridge.test")
    monkeypatch.setenv("BILLING_SUCCESS_URL", "https://app.memorybridge.test/billing/success")
    monkeypatch.setenv("BILLING_CANCEL_URL", "https://app.memorybridge.test/billing/cancel")
    monkeypatch.setenv("BILLING_MODE", mode)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_valid" if mode == "test" else "sk_live_valid")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_valid")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_team")


def test_non_production_is_permissive(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    validate_runtime_config()


def test_valid_test_mode_production_config_passes(monkeypatch):
    set_valid_production(monkeypatch, "test")
    validate_runtime_config()


def test_valid_live_mode_production_config_passes(monkeypatch):
    set_valid_production(monkeypatch, "live")
    validate_runtime_config()


@pytest.mark.parametrize(
    "name,value",
    [
        ("DATABASE_URL", "postgresql://memorybridge:change-me@localhost/memorybridge"),
        ("CORS_ALLOWED_ORIGINS", "http://app.memorybridge.test"),
        ("BILLING_SUCCESS_URL", "http://app.memorybridge.test/success"),
        ("BILLING_CANCEL_URL", "https://example.com/cancel"),
        ("STRIPE_WEBHOOK_SECRET", "not-a-webhook-secret"),
        ("STRIPE_PRICE_PRO", "not-a-price"),
    ],
)
def test_unsafe_production_values_fail(monkeypatch, name, value):
    set_valid_production(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        validate_runtime_config()


def test_wildcard_cors_fails(monkeypatch):
    set_valid_production(monkeypatch)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        validate_runtime_config()


def test_stripe_mode_and_secret_namespace_must_match(monkeypatch):
    set_valid_production(monkeypatch, "live")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_wrong_namespace")
    with pytest.raises(RuntimeError):
        validate_runtime_config()


def test_paid_plan_prices_must_be_distinct(monkeypatch):
    set_valid_production(monkeypatch)
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_pro")
    with pytest.raises(RuntimeError):
        validate_runtime_config()
