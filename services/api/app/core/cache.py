from __future__ import annotations

import os

import redis


_client: redis.Redis | None = None


def init_cache() -> None:
    global _client
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not set")
    _client = redis.Redis.from_url(redis_url, decode_responses=True)


def close_cache() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_cache() -> redis.Redis:
    if _client is None:
        raise RuntimeError("Redis client is not initialized")
    return _client
