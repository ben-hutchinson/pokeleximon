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

    def test_rate_limit_middleware_has_auth_admin_and_public_policies(self):
        source = RATE_LIMIT_FILE.read_text(encoding="utf-8")
        self.assertIn('if path.startswith("/api/v1/auth")', source)
        self.assertIn('if path.startswith("/api/v1/admin")', source)
        self.assertIn('path in {"/api/v1/health", "/api/v1/health/ready"}', source)
        self.assertIn("status_code=429", source)

    def test_rate_limit_uses_last_trusted_forwarded_hop(self):
        source = RATE_LIMIT_FILE.read_text(encoding="utf-8")
        self.assertIn("forwarded_chain[-trusted_hops]", source)
        self.assertNotIn('forwarded_for.split(",")[0].strip()', source)

    def test_security_module_supports_bearer_and_config_header(self):
        source = SECURITY_FILE.read_text(encoding="utf-8")
        self.assertIn("alias=config.ADMIN_AUTH_HEADER_NAME", source)
        self.assertIn('auth_header.lower().startswith("bearer ")', source)
        self.assertIn("hmac.compare_digest", source)

    def test_main_exposes_readiness_routes(self):
        source = MAIN_FILE.read_text(encoding="utf-8")
        self.assertIn('@app.get("/health/ready"', source)
        self.assertIn('@app.get("/api/v1/health/ready"', source)
        self.assertIn("db.ping_db()", source)
        self.assertIn("cache.ping_cache()", source)


if __name__ == "__main__":
    unittest.main()
