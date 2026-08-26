from pathlib import Path


DASHBOARD = (Path(__file__).resolve().parents[1] / "web" / "dashboard.html").read_text(encoding="utf-8")


def test_dashboard_handles_success_and_cancel_returns():
    assert "billing=success" in DASHBOARD or "get('billing')" in DASHBOARD
    assert "result==='success'" in DASHBOARD
    assert "result==='cancel'" in DASHBOARD
    assert "Checkout was canceled. No plan change was made." in DASHBOARD


def test_success_return_waits_for_verified_entitlement():
    assert "paid_entitlement_active" in DASHBOARD
    assert "pollEntitlement" in DASHBOARD
    assert "setInterval(tick,2000)" in DASHBOARD
    assert "Payment verified." in DASHBOARD
    assert "Payment returned, but entitlement is still pending." in DASHBOARD


def test_dashboard_never_treats_redirect_as_entitlement():
    success_block = DASHBOARD.split("async function handleBillingReturn", 1)[1]
    assert "paid_entitlement_active=true" not in success_block
    assert "state.account.plan='pro'" not in DASHBOARD
    assert "state.account.plan='team'" not in DASHBOARD


def test_billing_query_parameter_is_removed_after_handling():
    assert "history.replaceState" in DASHBOARD
    assert "searchParams.delete('billing')" in DASHBOARD
