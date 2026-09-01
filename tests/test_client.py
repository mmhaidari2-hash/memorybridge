from unittest.mock import Mock, patch

import pytest
import requests

from memorybridge_client import MemoryBridgeClient


@pytest.fixture
def client():
    return MemoryBridgeClient("https://api.example.test", "mbs_test_key", timeout=7)


def _response(payload=None, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    response.raise_for_status.return_value = None
    return response


def test_client_requires_service_api_key():
    with pytest.raises(ValueError):
        MemoryBridgeClient("https://api.example.test", "")


@patch("memorybridge_client.requests.request")
def test_account_status_uses_authenticated_get(mock_request, client):
    mock_request.return_value = _response({"plan": "free", "used": 10})

    result = client.account_status()

    assert result["plan"] == "free"
    mock_request.assert_called_once_with(
        "GET",
        "https://api.example.test/v1/account/status",
        headers={"X-MemoryBridge-Key": "mbs_test_key"},
        timeout=7,
    )


@patch("memorybridge_client.requests.request")
def test_create_api_key_returns_plaintext_once(mock_request, client):
    mock_request.return_value = _response({"id": "k1", "api_key": "mbs_new_secret"}, 201)

    result = client.create_api_key("Production")

    assert result["api_key"] == "mbs_new_secret"
    mock_request.assert_called_once_with(
        "POST",
        "https://api.example.test/v1/api-keys",
        json={"name": "Production"},
        headers={"X-MemoryBridge-Key": "mbs_test_key"},
        timeout=7,
    )


@patch("memorybridge_client.requests.request")
def test_list_and_revoke_api_keys(mock_request, client):
    mock_request.side_effect = [
        _response([{"id": "k1", "name": "Production"}]),
        _response({}, 204),
    ]

    keys = client.list_api_keys()
    revoked = client.revoke_api_key("k1")

    assert keys[0]["id"] == "k1"
    assert revoked is None
    assert mock_request.call_args_list[0].args == (
        "GET",
        "https://api.example.test/v1/api-keys",
    )
    assert mock_request.call_args_list[1].args == (
        "DELETE",
        "https://api.example.test/v1/api-keys/k1",
    )


@patch("memorybridge_client.requests.request")
def test_create_checkout_returns_checkout_url(mock_request, client):
    mock_request.return_value = _response(
        {"checkout_url": "https://checkout.stripe.test/session", "session_id": "cs_test_1"}
    )

    result = client.create_checkout("pro")

    assert result["session_id"] == "cs_test_1"
    mock_request.assert_called_once_with(
        "POST",
        "https://api.example.test/v1/billing/checkout",
        json={"plan": "pro"},
        headers={"X-MemoryBridge-Key": "mbs_test_key"},
        timeout=7,
    )


@patch("memorybridge_client.requests.request")
def test_http_errors_are_not_swallowed(mock_request, client):
    response = _response(status_code=429)
    response.raise_for_status.side_effect = requests.HTTPError("quota exceeded")
    mock_request.return_value = response

    with pytest.raises(requests.HTTPError):
        client.account_status()
