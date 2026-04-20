"""API key middleware for /wechat/* and /mcp."""

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings


PROTECTED_PREFIXES = ("/wechat/", "/mcp")
EXEMPT_PATHS = {"/healthz", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def _is_protected(path: str) -> bool:
    if path in EXEMPT_PATHS:
        return False
    return path.startswith(PROTECTED_PREFIXES)


async def api_key_middleware(request: Request, call_next):
    """Enforce X-API-Key on protected paths when settings.api_key is configured."""
    if not settings.api_key or not _is_protected(request.url.path):
        return await call_next(request)

    provided = request.headers.get(settings.api_key_header.lower())
    if provided != settings.api_key:
        return JSONResponse(
            {"detail": "Invalid or missing API key"},
            status_code=401,
            headers={"WWW-Authenticate": settings.api_key_header},
        )
    return await call_next(request)
