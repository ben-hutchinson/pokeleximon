from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

if "psycopg_pool" not in sys.modules:
    psycopg_pool_module = ModuleType("psycopg_pool")
    psycopg_pool_module.ConnectionPool = object
    sys.modules["psycopg_pool"] = psycopg_pool_module

if "psycopg" not in sys.modules:
    psycopg_module = ModuleType("psycopg")
    psycopg_rows_module = ModuleType("psycopg.rows")
    psycopg_rows_module.dict_row = object()
    psycopg_module.rows = psycopg_rows_module
    sys.modules["psycopg"] = psycopg_module
    sys.modules["psycopg.rows"] = psycopg_rows_module

if "redis" not in sys.modules:
    redis_module = ModuleType("redis")
    redis_module.Redis = SimpleNamespace(from_url=lambda *args, **kwargs: None)
    sys.modules["redis"] = redis_module

import app.services.alerting as alerting  # noqa: E402


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class AlertingTests(unittest.TestCase):
    def test_disabled_returns_false_without_network(self):
        with (
            patch.object(alerting.config, "ALERT_WEBHOOK_ENABLED", False),
            patch.object(alerting.config, "ALERT_WEBHOOK_URL", "https://example.test/webhook"),
            patch("urllib.request.urlopen") as mocked_urlopen,
        ):
            ok = alerting.notify_external_alert(
                event_type="reserve_low",
                severity="warning",
                message="reserve low",
                details={"gameType": "crossword"},
            )
        self.assertFalse(ok)
        mocked_urlopen.assert_not_called()

    def test_enabled_posts_payload(self):
        captured = {}

        def _fake_urlopen(req, timeout):  # noqa: ANN001
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["body"] = req.data.decode("utf-8")
            return _FakeResponse()

        with (
            patch.object(alerting.config, "ALERT_WEBHOOK_ENABLED", True),
            patch.object(alerting.config, "ALERT_WEBHOOK_URL", "https://example.test/webhook"),
            patch.object(alerting.config, "ALERT_WEBHOOK_TIMEOUT_SECONDS", 7),
            patch.object(alerting.config, "APP_NAME", "Pokeleximon API"),
            patch.object(alerting.config, "APP_ENV", "test"),
            patch("urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            ok = alerting.notify_external_alert(
                event_type="generation_job_failed",
                severity="error",
                message="job failed",
                details={"jobId": "job_123"},
            )

        self.assertTrue(ok)
        self.assertEqual(captured["url"], "https://example.test/webhook")
        self.assertEqual(captured["timeout"], 7)
        payload = json.loads(captured["body"])
        self.assertEqual(payload["eventType"], "generation_job_failed")
        self.assertEqual(payload["severity"], "error")
        self.assertEqual(payload["message"], "job failed")
        self.assertEqual(payload["details"]["jobId"], "job_123")
        self.assertIn("Pokeleximon API", payload["text"])

    def test_network_failure_returns_false(self):
        with (
            patch.object(alerting.config, "ALERT_WEBHOOK_ENABLED", True),
            patch.object(alerting.config, "ALERT_WEBHOOK_URL", "https://example.test/webhook"),
            patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")),
        ):
            ok = alerting.notify_external_alert(
                event_type="reserve_low",
                severity="warning",
                message="reserve low",
            )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
