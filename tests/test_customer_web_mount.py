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
