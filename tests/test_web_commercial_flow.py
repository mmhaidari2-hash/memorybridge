from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_landing_routes_new_customers_through_onboarding():
    html = read("landing.html")
    assert 'href="onboarding.html"' in html
    assert "Start with workspace verification" in html


def test_onboarding_verifies_real_memory_round_trip():
    html = read("onboarding.html")
    assert "/v1/account/status" in html
    assert "/v1/auth/token" in html
    assert "/v1/memory/store" in html
    assert "/v1/memory/recall" in html
    assert "recalled.summary!==expected" in html
    assert "Memory round-trip verified" in html
    assert "sessionStorage.setItem('mb_workspace_key'" in html


def test_dashboard_uses_authoritative_account_and_server_checkout():
    html = read("dashboard.html")
    assert "api('/account/status')" in html
    assert "a.paid_entitlement_active" in html
    assert "a.can_upgrade" in html
    assert "api('/billing/checkout'" in html
    assert "result.checkout_url" in html
    assert "price_" not in html


def test_dashboard_exposes_api_key_lifecycle_without_persisting_secret_locally():
    html = read("dashboard.html")
    assert "api('/api-keys')" in html
    assert "method:'POST'" in html
    assert "method:'DELETE'" in html
    assert "shown only once" in html
    assert "localStorage" not in html
