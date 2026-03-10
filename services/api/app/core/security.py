from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from app.core import config


def validate_admin_auth_config() -> None:
    if not config.ADMIN_AUTH_ENABLED:
        return
    if not config.ADMIN_AUTH_TOKEN:
        raise RuntimeError("ADMIN_AUTH_ENABLED=true but ADMIN_AUTH_TOKEN is not configured")


def _extract_admin_token(request: Request, configured_header_value: str | None) -> str:
    if configured_header_value:
        return configured_header_value.strip()

    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def require_admin_auth(
    request: Request,
    configured_header_value: str | None = Header(default=None, alias=config.ADMIN_AUTH_HEADER_NAME),
) -> None:
    if not config.ADMIN_AUTH_ENABLED:
        return

    expected = config.ADMIN_AUTH_TOKEN
    provided = _extract_admin_token(request, configured_header_value)
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

