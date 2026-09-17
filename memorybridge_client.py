from typing import Any, Dict, Optional

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

    def create_user(self, full_name: Optional[str] = None) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/auth/token",
            json={"full_name": full_name},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def store(
        self,
        user_token: str,
        summary: str,
        session_token: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/memory/store",
            json={
                "user_token": user_token,
                "session_token": session_token,
                "stage": stage,
                "summary": summary,
            },
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def recall(
        self,
        user_token: str,
        session_token: str,
    ) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/memory/recall",
            json={"user_token": user_token, "session_token": session_token},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def update(
        self,
        user_token: str,
        session_token: str,
        summary: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        resp = requests.put(
            f"{self.base_url}/v1/memory/update",
            json={
                "user_token": user_token,
                "session_token": session_token,
                "stage": stage,
                "summary": summary,
            },
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def delete(self, user_token: str, session_token: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/memory/delete",
            json={"user_token": user_token, "session_token": session_token},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def list_sessions(self, user_token: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/memory/list",
            json={"user_token": user_token},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


class MemoryBridgeAdminClient:
    def __init__(self, base_url: str, admin_api_key: str, timeout: int = 10):
        if not admin_api_key:
            raise ValueError("admin_api_key is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {"X-MemoryBridge-Admin-Key": admin_api_key}

    def create_tenant(self, name: str, slug: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/admin/tenants",
            json={"name": name, "slug": slug},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def create_api_key(self, tenant_id: str, name: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/admin/tenants/{tenant_id}/keys",
            json={"name": name},
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def revoke_api_key(self, key_id: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/admin/keys/{key_id}/revoke",
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def suspend_tenant(self, tenant_id: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/admin/tenants/{tenant_id}/suspend",
            headers=self._headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
