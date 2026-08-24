import requests
from typing import Optional, Dict, Any


class MemoryBridgeClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def create_user(self, full_name: Optional[str] = None) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/auth/token",
            json={"full_name": full_name},
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
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def recall(
        self,
        user_token: str,
        session_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/v1/memory/recall",
            json={"user_token": user_token, "session_token": session_token},
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
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
