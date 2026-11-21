"""Request guards: host and origin checks, size limits, safe headers, and a first login gate."""
import logging
import re
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from app import auth
from app.config import settings

MAX_BODY = 25 * 1024 * 1024  # a few receipts per request; single files are capped at 20 MB
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Telegram bot tokens, Discord bot tokens (three dot-separated base64 parts) and our own MCP tokens
_TOKEN = re.compile(r"bot\d+:[\w-]+|\d{6,}:[A-Za-z0-9_-]{30,}|[\w-]{23,28}\.[\w-]{6,7}\.[\w-]{27,40}|v[tu]_[\w-]{20,}")


def needs_login(path: str) -> bool:
    """Everything that exposes data. The SPA shell, its assets and /healthz stay public."""
    if path.startswith("/api/v1/auth/"):
        return False
    return path.startswith("/api/") or path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


def _origin_ok(origin: str, host: str) -> bool:
    """Same host as the request, or one of ALLOWED_HOSTS (a reverse proxy may rewrite Host, but the
    browser's Origin is still the address you typed, which must be listed there anyway)."""
    if origin == "null":
        return False
    parts = urlsplit(origin)
    if parts.netloc.lower() == host.lower():
        return True
    allowed = {h.lower() for h in settings.allowed_host_list if h != "*"}
    return (parts.hostname or "").lower() in allowed


def cross_site_write(request: Request) -> bool:
    """True for a state-changing request that a browser sent on behalf of another site."""
    if request.method in SAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is not None:
        return not _origin_ok(origin, request.headers.get("host", ""))
    site = request.headers.get("sec-fetch-site")
    return site is not None and site not in ("same-origin", "none")


async def guard(request: Request, call_next):
    if cross_site_write(request):
        return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        return JSONResponse({"detail": "Request is too large"}, status_code=413)
    # cheap first gate (signature + expiry, no database); routes then load and check the user itself
    if needs_login(request.url.path) and not auth.cookie_looks_valid(request):
        return JSONResponse({"detail": "Sign in first"}, status_code=401)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


class BodySizeLimit:
    """Counts the bytes actually received, so a chunked request (no Content-Length) can't get around
    MAX_BODY by streaming gigabytes into the multipart parser's temp files."""

    def __init__(self, app, max_body: int = MAX_BODY) -> None:
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0
        started = False
        rejected = False

        async def counted_receive():
            # Raising here wouldn't work: FastAPI turns any error while parsing a form into a 400.
            # So answer 413 ourselves, then tell the app the client went away.
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    rejected = True
                    if not started:
                        await JSONResponse({"detail": "Request is too large"}, status_code=413)(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def tracked_send(message):
            nonlocal started
            if rejected:
                return  # the 413 has already been sent; drop whatever the app answers after the disconnect
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counted_receive, tracked_send)


class RedactingFormatter(logging.Formatter):
    """Strips anything that looks like a bot token or access token from log lines, tracebacks included."""

    def format(self, record: logging.LogRecord) -> str:
        return _TOKEN.sub("<redacted>", super().format(record))


class RedactingWrapper(logging.Formatter):
    """Redacts the output of another formatter, keeping it as it is (uvicorn's add fields such as levelprefix)."""

    def __init__(self, inner: logging.Formatter | None) -> None:
        super().__init__()
        self.inner = inner or logging.Formatter("%(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return _TOKEN.sub("<redacted>", self.inner.format(record))
