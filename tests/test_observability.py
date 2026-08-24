import base64
import logging
import os

from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    base64.b64encode(b"x" * 32).decode("ascii"),
)
os.environ.setdefault("SERVICE_API_KEYS", "mbs_observability_test_key")

from main import app

client = TestClient(app)


def test_request_id_is_echoed_and_sensitive_request_data_is_not_logged(caplog):
    request_id = "req-observability-123"
    secret_query = "do-not-log-query-secret"
    secret_header = "do-not-log-service-key"

    caplog.set_level(logging.INFO, logger="memorybridge.http")
    response = client.get(
        f"/health?token={secret_query}",
        headers={
            "X-Request-ID": request_id,
            "X-MemoryBridge-Key": secret_header,
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == request_id

    log_text = caplog.text
    assert "method=GET" in log_text
    assert "path=/health" in log_text
    assert f"request_id={request_id}" in log_text
    assert secret_query not in log_text
    assert secret_header not in log_text
    assert "?token=" not in log_text


def test_generated_request_id_is_returned():
    response = client.get("/health")
    request_id = response.headers.get("x-request-id")

    assert response.status_code == 200
    assert request_id
    assert len(request_id) >= 16
