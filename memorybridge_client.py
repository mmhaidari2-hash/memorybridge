from typing import Any, Dict, List, Optional

import requests


class MemoryBridgeClient:
    def __init__(
        self,
        base_url: str,
        service_api_key: str,
        timeout: int = 10,
    ):
        if not service_api_key:
            raise ValueError("service_api_key is required")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"X-MemoryBridge-Key": service_api_key}

    def _request(self, method: str, path: str, **kwargs):
        resp = requests.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers,
            timeout=self.timeout,
            **kwargs,
        )
        resp.raise_for_status()
        return resp

    def create_user(self, full_name: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", "/v1/auth/token", json={"full_name": full_name}).json()

    def store(
        self,
        user_token: str,
        summary: str,
        session_token: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/memory/store",
            json={
                "user_token": user_token,
                "session_token": session_token,
                "stage": stage,
                "summary": summary,
            },
        ).json()

    def recall(self, user_token: str, session_token: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/memory/recall",
            json={"user_token": user_token, "session_token": session_token},
        ).json()

    def update(
        self,
        user_token: str,
        session_token: str,
        summary: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "PUT",
            "/v1/memory/update",
            json={
                "user_token": user_token,
                "session_token": session_token,
                "stage": stage,
                "summary": summary,
            },
        ).json()

    def account_status(self) -> Dict[str, Any]:
        """Return plan, subscription state, and current monthly usage/quota."""
        return self._request("GET", "/v1/account/status").json()

    def create_api_key(self, name: str) -> Dict[str, Any]:
        """Create a workspace API key. The plaintext key is returned only once."""
        return self._request("POST", "/v1/api-keys", json={"name": name}).json()

    def list_api_keys(self) -> List[Dict[str, Any]]:
        """List workspace API-key metadata without exposing plaintext keys."""
        return self._request("GET", "/v1/api-keys").json()

    def revoke_api_key(self, key_id: str) -> None:
        """Revoke one API key belonging to the authenticated workspace."""
        self._request("DELETE", f"/v1/api-keys/{key_id}")

    def create_checkout(self, plan: str) -> Dict[str, Any]:
        """Create a Stripe subscription checkout session for a paid plan."""
        return self._request("POST", "/v1/billing/checkout", json={"plan": plan}).json()
