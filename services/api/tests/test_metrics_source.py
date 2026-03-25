from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_FILE = ROOT / "app" / "main.py"
METRICS_FILE = ROOT / "app" / "core" / "metrics.py"
REQUIREMENTS_FILE = ROOT / "requirements.txt"
COMPOSE_FILE = ROOT.parents[1] / "infra" / "production" / "aws-ec2" / "docker-compose.prod.yml"


class MetricsSourceTests(unittest.TestCase):
    def test_main_wires_prometheus_middleware_and_metrics_route(self):
        source = MAIN_FILE.read_text(encoding="utf-8")
        self.assertIn("app.add_middleware(PrometheusMiddleware)", source)
        self.assertIn('@app.get("/metrics"', source)
        self.assertIn("init_metrics()", source)

    def test_metrics_module_exposes_http_and_business_metrics(self):
        source = METRICS_FILE.read_text(encoding="utf-8")
        self.assertIn("pokeleximon_http_requests_total", source)
        self.assertIn("pokeleximon_puzzle_inventory_count", source)
        self.assertIn("pokeleximon_active_players", source)
        self.assertIn("pokeleximon_generation_jobs_total", source)
        self.assertIn('feature="scheduler"', source)
        self.assertIn('feature="generator"', source)

    def test_requirements_include_prometheus_client(self):
        source = REQUIREMENTS_FILE.read_text(encoding="utf-8")
        self.assertIn("prometheus-client==", source)

    def test_ec2_compose_includes_monitoring_services(self):
        source = COMPOSE_FILE.read_text(encoding="utf-8")
        for marker in ("prometheus:", "grafana:", "alertmanager:", "node-exporter:", "postgres-exporter:", "redis-exporter:"):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
