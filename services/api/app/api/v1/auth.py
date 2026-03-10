from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.v1.models import AuthLoginRequest, AuthSessionResponse, AuthSignupRequest
from app.core import config
from app.data import repo


router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookie(response: Response, raw_session_token: str) -> None:
    response.set_cookie(
        key=config.AUTH_SESSION_COOKIE_NAME,
        value=raw_session_token,
        httponly=True,
        samesite="lax",
        secure=config.APP_ENV != "dev",
        max_age=max(1, config.AUTH_SESSION_DURATION_DAYS) * 24 * 60 * 60,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=config.AUTH_SESSION_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=config.APP_ENV != "dev",
        path="/",
    )


@router.post("/signup", response_model=AuthSessionResponse)
def signup(payload: AuthSignupRequest, request: Request, response: Response):
    try:
        session, raw_session_token = repo.create_player_account(
            username=payload.username,
            password=payload.password,
            guest_player_token=payload.guestPlayerToken,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _set_auth_cookie(response, raw_session_token)
    return {"data": session}


@router.post("/login", response_model=AuthSessionResponse)
def login(payload: AuthLoginRequest, request: Request, response: Response):
    try:
        session, raw_session_token = repo.login_player_account(
            username=payload.username,
            password=payload.password,
            guest_player_token=payload.guestPlayerToken,
            merge_guest_data=payload.mergeGuestData,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 401 if "invalid username or password" in detail.lower() else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    _set_auth_cookie(response, raw_session_token)
    return {"data": session}


@router.post("/logout", response_model=AuthSessionResponse)
def logout(request: Request, response: Response):
    repo.revoke_player_auth_session(session_token=request.cookies.get(config.AUTH_SESSION_COOKIE_NAME, ""))
    _clear_auth_cookie(response)
    return {
        "data": {
            "authenticated": False,
            "playerToken": None,
            "username": None,
            "profile": None,
            "mergedGuestToken": None,
        }
    }


@router.get("/session", response_model=AuthSessionResponse)
def session(request: Request):
    return {"data": repo.get_player_auth_session(session_token=request.cookies.get(config.AUTH_SESSION_COOKIE_NAME, ""))}
