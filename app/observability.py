import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("memorybridge.http")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def safe_request_id(candidate: str | None) -> str:
    """Accept only bounded non-secret-shaped correlation IDs.

    Request bodies, query strings, authorization headers, workspace API keys,
    Stripe signatures, and memory content are intentionally never logged.
    """
    value = (candidate or "").strip()
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return str(uuid.uuid4())


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log minimal request metadata without bodies, query strings or credentials."""

    async def dispatch(self, request: Request, call_next):
        request_id = safe_request_id(request.headers.get("X-Request-ID"))
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request_failed method=%s path=%s duration_ms=%s request_id=%s",
                request.method,
                request.url.path,
                duration_ms,
                request_id,
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
