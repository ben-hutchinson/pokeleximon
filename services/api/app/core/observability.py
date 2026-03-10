from __future__ import annotations

import logging

from app.core import config


logger = logging.getLogger(__name__)
_sentry_enabled = False


def init_sentry() -> None:
    global _sentry_enabled
    if not config.SENTRY_DSN:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except ModuleNotFoundError:
        logger.warning("SENTRY_DSN configured but sentry_sdk is not installed")
        return

    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.SENTRY_ENVIRONMENT,
        release=config.SENTRY_RELEASE,
        traces_sample_rate=max(0.0, config.SENTRY_TRACES_SAMPLE_RATE),
        profiles_sample_rate=max(0.0, config.SENTRY_PROFILES_SAMPLE_RATE),
        integrations=[FastApiIntegration()],
    )
    _sentry_enabled = True


def capture_exception(exc: Exception) -> None:
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk
    except ModuleNotFoundError:
        return
    sentry_sdk.capture_exception(exc)


def capture_message(message: str, *, level: str = "error") -> None:
    if not _sentry_enabled:
        return
    try:
        import sentry_sdk
    except ModuleNotFoundError:
        return
    sentry_sdk.capture_message(message, level=level)
