from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_customer_app_entrypoint_redirects_to_landing():
    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/landing.html"


def test_landing_is_served_by_api_process():
    response = client.get("/app/landing.html")
    assert response.status_code == 200
    assert "MemoryBridge" in response.text
    assert 'href="onboarding.html"' in response.text


def test_onboarding_and_dashboard_are_same_origin_assets():
    onboarding = client.get("/app/onboarding.html")
    dashboard = client.get("/app/dashboard.html")
    assert onboarding.status_code == 200
    assert dashboard.status_code == 200
    assert "/v1/account/status" in onboarding.text
    assert "api('/account/status')" in dashboard.text


def test_pwa_and_local_records_are_same_origin_assets():
    records = client.get("/app/records.html")
    manifest = client.get("/app/manifest.webmanifest")
    sw = client.get("/app/sw.js")
    store = client.get("/app/local_store.js")
    pwa = client.get("/app/pwa.js")
    assert records.status_code == 200
    assert "IndexedDB" in records.text
    assert manifest.status_code == 200
    assert "application/manifest+json" in manifest.headers["content-type"]
    assert sw.status_code == 200
    assert store.status_code == 200
    assert pwa.status_code == 200
