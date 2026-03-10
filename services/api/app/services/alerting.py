from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.core import config


logger = logging.getLogger(__name__)


def notify_external_alert(
    *,
    event_type: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> bool:
    if not config.ALERT_WEBHOOK_ENABLED or not config.ALERT_WEBHOOK_URL:
        return False

    text = (
        f"[{config.APP_NAME}][{config.APP_ENV}] "
        f"[{severity.upper()}] {event_type}: {message}"
    )
    payload = {
        "text": text,
        "app": config.APP_NAME,
        "env": config.APP_ENV,
        "severity": severity,
        "eventType": event_type,
        "message": message,
        "details": details or {},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        config.ALERT_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1, config.ALERT_WEBHOOK_TIMEOUT_SECONDS)):
            return True
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning(
            "external alert delivery failed: event_type=%s severity=%s error=%s",
            event_type,
            severity,
            exc,
        )
        return False
