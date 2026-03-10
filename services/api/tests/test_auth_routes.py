from __future__ import annotations

import unittest
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "app" / "api" / "v1"
AUTH_FILE = API_ROOT / "auth.py"
ROUTER_FILE = API_ROOT / "router.py"


class AuthRouteSourceTests(unittest.TestCase):
    def test_auth_router_exposes_signup_login_logout_and_session_routes(self):
        source = AUTH_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.post("/signup"', source)
        self.assertIn('@router.post("/login"', source)
        self.assertIn('@router.post("/logout"', source)
        self.assertIn('@router.get("/session"', source)

    def test_api_router_includes_auth_router(self):
        source = ROUTER_FILE.read_text(encoding="utf-8")
        self.assertIn("from app.api.v1 import auth, puzzles, admin", source)
        self.assertIn("router.include_router(auth.router)", source)


if __name__ == "__main__":
    unittest.main()
