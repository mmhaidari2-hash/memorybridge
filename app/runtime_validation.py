import os
from urllib.parse import urlparse

from app.security import get_aes_key


PLACEHOLDER_MARKERS = ("REPLACE", "change-me", "example.com", "YOUR-STAGING-HOST", "YOUR-PRODUCTION-API")


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _require(name: str) -> str:
    value = _value(name)
    if not value:
        raise RuntimeError(f"{name} is required in production")
    if any(marker.lower() in value.lower() for marker in PLACEHOLDER_MARKERS):
        raise RuntimeError(f"{name} still contains a placeholder value")
    return value


def _require_https(name: str) -> str:
    value = _require(name)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError(f"{name} must be an absolute HTTPS URL in production")
    return value.rstrip("/")


def validate_runtime_config() -> None:
    """Fail closed on unsafe production configuration.

    Development/test remain intentionally permissive so local tooling and CI can
    supply only the values needed by each test. Set APP_ENV=production on every
    customer-facing deployment.
    """
    if _value("APP_ENV").lower() != "production":
        return

    database_url = _require("DATABASE_URL")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise RuntimeError("DATABASE_URL must use PostgreSQL in production")

    # Reuse the cryptographic validator so malformed or non-256-bit keys fail.
    get_aes_key()

    raw_origins = _require("CORS_ALLOWED_ORIGINS")
    origins = [origin.strip().rstrip("/") for origin in raw_origins.split(",") if origin.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must contain explicit HTTPS origins")
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
            raise RuntimeError("CORS_ALLOWED_ORIGINS entries must be HTTPS origins without paths")

    _require_https("BILLING_SUCCESS_URL")
    _require_https("BILLING_CANCEL_URL")

    billing_mode = _require("BILLING_MODE").lower()
    if billing_mode not in {"test", "live"}:
        raise RuntimeError("BILLING_MODE must be 'test' or 'live'")

    secret_key = _require("STRIPE_SECRET_KEY")
    webhook = _require("STRIPE_WEBHOOK_SECRET")
    pro_price = _require("STRIPE_PRICE_PRO")
    team_price = _require("STRIPE_PRICE_TEAM")

    expected_key_prefix = "sk_test_" if billing_mode == "test" else "sk_live_"
    if not secret_key.startswith(expected_key_prefix):
        raise RuntimeError(f"STRIPE_SECRET_KEY does not match BILLING_MODE={billing_mode}")
    if not webhook.startswith("whsec_"):
        raise RuntimeError("STRIPE_WEBHOOK_SECRET must be a Stripe webhook signing secret")
    if not pro_price.startswith("price_") or not team_price.startswith("price_"):
        raise RuntimeError("Stripe paid plan identifiers must be price_ IDs")
    if pro_price == team_price:
        raise RuntimeError("STRIPE_PRICE_PRO and STRIPE_PRICE_TEAM must be different")
