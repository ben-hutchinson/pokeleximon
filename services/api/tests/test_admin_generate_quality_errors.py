from __future__ import annotations

import unittest
from pathlib import Path


ADMIN_FILE = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "admin.py"


class AdminGenerateQualityErrorTests(unittest.TestCase):
    def test_generate_route_maps_quality_gate_error_to_http_422(self):
        source = ADMIN_FILE.read_text(encoding="utf-8")
        self.assertIn("except QualityGateError as exc:", source)
        self.assertIn("status_code=422", source)
        self.assertIn("detail=exc.to_detail()", source)

    def test_topup_route_surfaces_structured_quality_gate_error_details(self):
        source = ADMIN_FILE.read_text(encoding="utf-8")
        self.assertIn('"error": exc.code', source)
        self.assertIn('"detail": exc.to_detail()', source)


if __name__ == "__main__":
    unittest.main()
