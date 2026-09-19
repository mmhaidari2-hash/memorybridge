from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies early using Content-Length when present."""

    async def dispatch(self, request: Request, call_next) -> Response:
        max_bytes = get_settings().max_request_bytes
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
            if length > max_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})

        return await call_next(request)
