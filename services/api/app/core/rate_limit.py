from __future__ import annotations

from collections import deque
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core import config


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    max_requests: int
    window_seconds: int


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.RLock()

    def _trim(self, bucket: deque[float], cutoff: float) -> None:
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def check(self, *, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events.get(key)
            if bucket is None:
                bucket = deque()
                self._events[key] = bucket
            self._trim(bucket, cutoff)

            if len(bucket) >= max_requests:
                oldest = bucket[0]
                retry_after = max(1, int(math.ceil(window_seconds - (now - oldest))))
                return False, 0, retry_after

            bucket.append(now)
            remaining = max(0, max_requests - len(bucket))
            return True, remaining, 0


def _client_ip_from_request(request: Request) -> str:
    if config.RATE_LIMIT_TRUST_X_FORWARDED_FOR:
        forwarded_for = request.headers.get("x-forwarded-for", "").strip()
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

    client = request.client
    if client and client.host:
        return client.host
    return "unknown"


def _policy_for_path(path: str) -> RateLimitPolicy | None:
    if path.startswith("/api/v1/admin"):
        return RateLimitPolicy(
            name="admin",
            max_requests=max(1, config.RATE_LIMIT_ADMIN_MAX_REQUESTS),
            window_seconds=max(1, config.RATE_LIMIT_ADMIN_WINDOW_SECONDS),
        )
    if path.startswith("/api/v1/puzzles") or path == "/api/v1/health":
        return RateLimitPolicy(
            name="public",
            max_requests=max(1, config.RATE_LIMIT_PUBLIC_MAX_REQUESTS),
            window_seconds=max(1, config.RATE_LIMIT_PUBLIC_WINDOW_SECONDS),
        )
    return None


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        limiter: SlidingWindowRateLimiter | None = None,
        policy_resolver: Callable[[str], RateLimitPolicy | None] = _policy_for_path,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter or SlidingWindowRateLimiter()
        self._policy_resolver = policy_resolver

    async def dispatch(self, request: Request, call_next) -> Response:
        if not config.RATE_LIMIT_ENABLED or request.method == "OPTIONS":
            return await call_next(request)

        policy = self._policy_resolver(request.url.path)
        if policy is None:
            return await call_next(request)

        key = f"{policy.name}:{_client_ip_from_request(request)}"
        allowed, remaining, retry_after = self._limiter.check(
            key=key,
            max_requests=policy.max_requests,
            window_seconds=policy.window_seconds,
        )

        headers = {
            "X-RateLimit-Limit": str(policy.max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Window": str(policy.window_seconds),
        }
        if not allowed:
            headers["Retry-After"] = str(retry_after)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Retry later.",
                    "scope": policy.name,
                    "retryAfterSeconds": retry_after,
                },
                headers=headers,
            )

        response = await call_next(request)
        for key_name, value in headers.items():
            response.headers[key_name] = value
        return response

