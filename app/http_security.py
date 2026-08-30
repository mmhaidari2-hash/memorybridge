from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # API and other responses stay unstoreable. The /app shell is
        # revalidated so the PWA service worker can keep an offline copy.
        if request.method == "GET" and request.url.path.startswith("/app/"):
            response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response
