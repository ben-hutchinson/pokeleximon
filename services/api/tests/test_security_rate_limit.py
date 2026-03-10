from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"
MAIN_FILE = ROOT / "main.py"
ADMIN_FILE = ROOT / "api" / "v1" / "admin.py"
RATE_LIMIT_FILE = ROOT / "core" / "rate_limit.py"
SECURITY_FILE = ROOT / "core" / "security.py"


class SecurityAndRateLimitSourceTests(unittest.TestCase):
    def test_main_wires_rate_limit_and_admin_auth_validation(self):
        source = MAIN_FILE.read_text(encoding="utf-8")
        self.assertIn("app.add_middleware(ApiRateLimitMiddleware)", source)
        self.assertIn("validate_admin_auth_config()", source)

    def test_admin_router_enforces_auth_dependency(self):
        source = ADMIN_FILE.read_text(encoding="utf-8")
        self.assertIn("dependencies=[Depends(require_admin_auth)]", source)

    def test_rate_limit_middleware_has_admin_and_public_policies(self):
        source = RATE_LIMIT_FILE.read_text(encoding="utf-8")
        self.assertIn('if path.startswith("/api/v1/admin")', source)
        self.assertIn('if path.startswith("/api/v1/puzzles") or path == "/api/v1/health"', source)
        self.assertIn("status_code=429", source)

    def test_security_module_supports_bearer_and_config_header(self):
        source = SECURITY_FILE.read_text(encoding="utf-8")
        self.assertIn("alias=config.ADMIN_AUTH_HEADER_NAME", source)
        self.assertIn('auth_header.lower().startswith("bearer ")', source)
        self.assertIn("hmac.compare_digest", source)


if __name__ == "__main__":
    unittest.main()

