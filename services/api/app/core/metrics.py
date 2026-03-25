from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, REGISTRY, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from psycopg.rows import dict_row
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core import config, db


logger = logging.getLogger(__name__)

GAME_TYPES = ("crossword", "cryptic", "connections")
WINDOWS = ("1d", "7d", "30d")

HTTP_REQUESTS_TOTAL = Counter(
    "pokeleximon_http_requests_total",
    "HTTP requests handled by the API.",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "pokeleximon_http_request_duration_seconds",
    "HTTP request latency for the API.",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "pokeleximon_http_requests_in_progress",
    "HTTP requests currently in progress.",
    ["method"],
)
BUILD_INFO = Gauge(
    "pokeleximon_build_info",
    "Build and environment metadata for the running API.",
    ["version", "environment"],
)
FEATURE_FLAG_ENABLED = Gauge(
    "pokeleximon_feature_flag_enabled",
    "Feature flag state for runtime-controlled product surfaces.",
    ["feature"],
)
RESERVE_TARGET = Gauge(
    "pokeleximon_reserve_target",
    "Configured reserve thresholds by game type.",
    ["game_type", "kind"],
)

_metrics_initialized = False


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is None:
        return "unmatched"
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    return str(template or "unmatched")


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method.upper()
        start = time.perf_counter()
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = int(response.status_code)
            return response
        finally:
            elapsed = max(time.perf_counter() - start, 0.0)
            path = _route_template(request)
            HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=path).observe(elapsed)
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()


class ApplicationMetricsCollector:
    def collect(self):
        sections = {
            "inventory": False,
            "users": False,
            "engagement": False,
            "operations": False,
        }

        for section_name, collector in (
            ("inventory", self._collect_inventory_metrics),
            ("users", self._collect_user_metrics),
            ("engagement", self._collect_engagement_metrics),
            ("operations", self._collect_operations_metrics),
        ):
            try:
                for metric in collector():
                    yield metric
                sections[section_name] = True
            except Exception:
                logger.exception("metrics collection failed for section=%s", section_name)

        success = GaugeMetricFamily(
            "pokeleximon_metrics_collection_success",
            "Whether each database-backed metrics section collected successfully.",
            labels=["section"],
        )
        for section_name, state in sections.items():
            success.add_metric([section_name], 1 if state else 0)
        yield success

    def _collect_inventory_metrics(self) -> list[Any]:
        inventory = GaugeMetricFamily(
            "pokeleximon_puzzle_inventory_count",
            "Current published and reserve puzzle inventory by game type.",
            labels=["game_type", "state"],
        )
        reserve_days = GaugeMetricFamily(
            "pokeleximon_reserve_days_covered",
            "Distinct future unpublished puzzle dates available in reserve.",
            labels=["game_type"],
        )

        today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
        rows_by_game: dict[str, dict[str, int]] = {}
        with db.get_db() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        game_type,
                        COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published_total,
                        COUNT(*) FILTER (WHERE published_at IS NULL AND date > %(today)s) AS reserve_future,
                        COUNT(*) FILTER (WHERE published_at IS NOT NULL AND date = %(today)s) AS published_today,
                        COUNT(DISTINCT date) FILTER (WHERE published_at IS NULL AND date > %(today)s) AS reserve_days
                    FROM puzzles
                    GROUP BY game_type
                    """,
                    {"today": today},
                )
                rows_by_game = {str(row["game_type"]): row for row in cur.fetchall()}

        for game_type in GAME_TYPES:
            row = rows_by_game.get(game_type, {})
            inventory.add_metric([game_type, "published_total"], int(row.get("published_total") or 0))
            inventory.add_metric([game_type, "reserve_future"], int(row.get("reserve_future") or 0))
            inventory.add_metric([game_type, "published_today"], int(row.get("published_today") or 0))
            reserve_days.add_metric([game_type], int(row.get("reserve_days") or 0))

        return [inventory, reserve_days]

    def _collect_user_metrics(self) -> list[Any]:
        profiles = GaugeMetricFamily(
            "pokeleximon_player_profiles_count",
            "Current player profile counts.",
            labels=["visibility"],
        )
        accounts = GaugeMetricFamily(
            "pokeleximon_player_accounts_count",
            "Current player account counts.",
            labels=["state"],
        )
        auth_sessions = GaugeMetricFamily(
            "pokeleximon_auth_sessions_count",
            "Current auth session counts by state.",
            labels=["state"],
        )
        active_players = GaugeMetricFamily(
            "pokeleximon_active_players",
            "Distinct authenticated players active in leaderboard submissions over recent windows.",
            labels=["game_type", "window"],
        )
        active_sessions = GaugeMetricFamily(
            "pokeleximon_active_sessions",
            "Distinct gameplay sessions seen in telemetry over recent windows.",
            labels=["game_type", "window"],
        )
        challenges = GaugeMetricFamily(
            "pokeleximon_challenges_count",
            "Current social challenge and member counts.",
            labels=["game_type", "kind"],
        )

        profile_row: dict[str, Any] = {}
        account_row: dict[str, Any] = {}
        auth_row: dict[str, Any] = {}
        active_player_rows: dict[str, dict[str, Any]] = {}
        active_session_rows: dict[str, dict[str, Any]] = {}
        challenge_rows: dict[str, dict[str, Any]] = {}

        with db.get_db() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE leaderboard_visible = TRUE) AS leaderboard_visible
                    FROM player_profiles
                    """
                )
                profile_row = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '1 day') AS active_1d,
                        COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '7 day') AS active_7d,
                        COUNT(*) FILTER (WHERE last_login_at >= NOW() - INTERVAL '30 day') AS active_30d
                    FROM player_accounts
                    """
                )
                account_row = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE revoked_at IS NULL AND expires_at > NOW()) AS active,
                        COUNT(*) FILTER (WHERE revoked_at IS NOT NULL) AS revoked,
                        COUNT(*) FILTER (WHERE revoked_at IS NULL AND expires_at <= NOW()) AS expired
                    FROM player_auth_sessions
                    """
                )
                auth_row = cur.fetchone() or {}

                cur.execute(
                    """
                    SELECT
                        game_type,
                        COUNT(DISTINCT player_token) FILTER (WHERE updated_at >= NOW() - INTERVAL '1 day') AS players_1d,
                        COUNT(DISTINCT player_token) FILTER (WHERE updated_at >= NOW() - INTERVAL '7 day') AS players_7d,
                        COUNT(DISTINCT player_token) FILTER (WHERE updated_at >= NOW() - INTERVAL '30 day') AS players_30d
                    FROM leaderboard_submissions
                    GROUP BY game_type
                    """
                )
                active_player_rows = {str(row["game_type"]): row for row in cur.fetchall()}

                cur.execute(
                    """
                    WITH sessions AS (
                        SELECT 'crossword'::text AS game_type, session_id, created_at
                        FROM crossword_feedback
                        WHERE session_id IS NOT NULL AND session_id <> ''
                        UNION ALL
                        SELECT 'cryptic'::text AS game_type, session_id, created_at
                        FROM cryptic_feedback
                        WHERE session_id IS NOT NULL AND session_id <> ''
                        UNION ALL
                        SELECT 'connections'::text AS game_type, session_id, created_at
                        FROM connections_feedback
                        WHERE session_id IS NOT NULL AND session_id <> ''
                    )
                    SELECT
                        game_type,
                        COUNT(DISTINCT session_id) FILTER (WHERE created_at >= NOW() - INTERVAL '1 day') AS sessions_1d,
                        COUNT(DISTINCT session_id) FILTER (WHERE created_at >= NOW() - INTERVAL '7 day') AS sessions_7d,
                        COUNT(DISTINCT session_id) FILTER (WHERE created_at >= NOW() - INTERVAL '30 day') AS sessions_30d
                    FROM sessions
                    GROUP BY game_type
                    """
                )
                active_session_rows = {str(row["game_type"]): row for row in cur.fetchall()}

                cur.execute(
                    """
                    SELECT
                        c.game_type,
                        COUNT(DISTINCT c.id) AS challenge_total,
                        COUNT(m.id) AS member_total
                    FROM challenges c
                    LEFT JOIN challenge_members m ON m.challenge_id = c.id
                    GROUP BY c.game_type
                    """
                )
                challenge_rows = {str(row["game_type"]): row for row in cur.fetchall()}

        profiles.add_metric(["all"], int(profile_row.get("total") or 0))
        profiles.add_metric(["leaderboard_visible"], int(profile_row.get("leaderboard_visible") or 0))

        accounts.add_metric(["all"], int(account_row.get("total") or 0))
        accounts.add_metric(["active_1d"], int(account_row.get("active_1d") or 0))
        accounts.add_metric(["active_7d"], int(account_row.get("active_7d") or 0))
        accounts.add_metric(["active_30d"], int(account_row.get("active_30d") or 0))

        auth_sessions.add_metric(["active"], int(auth_row.get("active") or 0))
        auth_sessions.add_metric(["revoked"], int(auth_row.get("revoked") or 0))
        auth_sessions.add_metric(["expired"], int(auth_row.get("expired") or 0))

        for game_type in GAME_TYPES:
            player_row = active_player_rows.get(game_type, {})
            session_row = active_session_rows.get(game_type, {})
            challenge_row = challenge_rows.get(game_type, {})
            for window in WINDOWS:
                active_players.add_metric([game_type, window], int(player_row.get(f"players_{window}") or 0))
                active_sessions.add_metric([game_type, window], int(session_row.get(f"sessions_{window}") or 0))
            challenges.add_metric([game_type, "challenges"], int(challenge_row.get("challenge_total") or 0))
            challenges.add_metric([game_type, "members"], int(challenge_row.get("member_total") or 0))

        return [profiles, accounts, auth_sessions, active_players, active_sessions, challenges]

    def _collect_engagement_metrics(self) -> list[Any]:
        feedback = CounterMetricFamily(
            "pokeleximon_feedback_events_total",
            "Total gameplay telemetry and feedback events ingested by game type and event type.",
            labels=["game_type", "event_type"],
        )
        submissions = CounterMetricFamily(
            "pokeleximon_leaderboard_submissions_total",
            "Total leaderboard submissions by game type and completion state.",
            labels=["game_type", "completed"],
        )
        solve_time = GaugeMetricFamily(
            "pokeleximon_leaderboard_solve_time_ms",
            "Recent leaderboard solve time stats in milliseconds.",
            labels=["game_type", "window", "stat"],
        )

        feedback_rows: list[dict[str, Any]] = []
        submission_rows: list[dict[str, Any]] = []
        solve_time_rows: dict[str, dict[str, Any]] = {}

        with db.get_db() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    WITH events AS (
                        SELECT 'crossword'::text AS game_type, event_type, COUNT(*)::bigint AS total
                        FROM crossword_feedback
                        GROUP BY event_type
                        UNION ALL
                        SELECT 'cryptic'::text AS game_type, event_type, COUNT(*)::bigint AS total
                        FROM cryptic_feedback
                        GROUP BY event_type
                        UNION ALL
                        SELECT 'connections'::text AS game_type, event_type, COUNT(*)::bigint AS total
                        FROM connections_feedback
                        GROUP BY event_type
                    )
                    SELECT game_type, event_type, SUM(total) AS total
                    FROM events
                    GROUP BY game_type, event_type
                    ORDER BY game_type, event_type
                    """
                )
                feedback_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT game_type, completed, COUNT(*) AS total
                    FROM leaderboard_submissions
                    GROUP BY game_type, completed
                    ORDER BY game_type, completed
                    """
                )
                submission_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        game_type,
                        AVG(solve_time_ms) FILTER (
                            WHERE completed = TRUE
                            AND solve_time_ms IS NOT NULL
                            AND updated_at >= NOW() - INTERVAL '7 day'
                        ) AS avg_solve_time_ms_7d,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY solve_time_ms::double precision) FILTER (
                            WHERE completed = TRUE
                            AND solve_time_ms IS NOT NULL
                            AND updated_at >= NOW() - INTERVAL '7 day'
                        ) AS p50_solve_time_ms_7d
                    FROM leaderboard_submissions
                    GROUP BY game_type
                    """
                )
                solve_time_rows = {str(row["game_type"]): row for row in cur.fetchall()}

        for row in feedback_rows:
            feedback.add_metric([str(row["game_type"]), str(row["event_type"])], int(row.get("total") or 0))

        for game_type in GAME_TYPES:
            states = {
                "true": 0,
                "false": 0,
            }
            for row in submission_rows:
                if str(row["game_type"]) != game_type:
                    continue
                states[str(bool(row.get("completed"))).lower()] = int(row.get("total") or 0)
            for completed, total in states.items():
                submissions.add_metric([game_type, completed], total)

            solve_row = solve_time_rows.get(game_type, {})
            avg_solve = solve_row.get("avg_solve_time_ms_7d")
            p50_solve = solve_row.get("p50_solve_time_ms_7d")
            solve_time.add_metric([game_type, "7d", "avg"], float(avg_solve or 0.0))
            solve_time.add_metric([game_type, "7d", "p50"], float(p50_solve or 0.0))

        return [feedback, submissions, solve_time]

    def _collect_operations_metrics(self) -> list[Any]:
        jobs = CounterMetricFamily(
            "pokeleximon_generation_jobs_total",
            "Total generation jobs recorded by type and status.",
            labels=["job_type", "status"],
        )
        job_duration = GaugeMetricFamily(
            "pokeleximon_generation_job_duration_seconds",
            "Recent generation job duration stats.",
            labels=["job_type", "window", "stat"],
        )
        alerts = GaugeMetricFamily(
            "pokeleximon_operational_alerts_count",
            "Current operational alert counts by game type, severity, and state.",
            labels=["game_type", "severity", "state"],
        )

        job_rows: list[dict[str, Any]] = []
        duration_rows: dict[str, dict[str, Any]] = {}
        alert_rows: list[dict[str, Any]] = []

        with db.get_db() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT type, status, COUNT(*) AS total
                    FROM generation_jobs
                    GROUP BY type, status
                    ORDER BY type, status
                    """
                )
                job_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        type,
                        AVG(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (
                            WHERE started_at IS NOT NULL
                            AND finished_at IS NOT NULL
                            AND created_at >= NOW() - INTERVAL '7 day'
                        ) AS avg_duration_7d
                    FROM generation_jobs
                    GROUP BY type
                    """
                )
                duration_rows = {str(row["type"]): row for row in cur.fetchall()}

                cur.execute(
                    """
                    SELECT
                        game_type,
                        severity,
                        COUNT(*) FILTER (WHERE resolved_at IS NULL) AS open_total,
                        COUNT(*) FILTER (WHERE resolved_at IS NOT NULL) AS resolved_total
                    FROM operational_alerts
                    GROUP BY game_type, severity
                    ORDER BY game_type, severity
                    """
                )
                alert_rows = cur.fetchall()

        for row in job_rows:
            jobs.add_metric([str(row["type"]), str(row["status"])], int(row.get("total") or 0))

        for job_type in sorted({str(row["type"]) for row in job_rows} | set(duration_rows.keys())):
            duration_row = duration_rows.get(job_type, {})
            job_duration.add_metric([job_type, "7d", "avg"], float(duration_row.get("avg_duration_7d") or 0.0))

        for row in alert_rows:
            alerts.add_metric([str(row["game_type"]), str(row["severity"]), "open"], int(row.get("open_total") or 0))
            alerts.add_metric(
                [str(row["game_type"]), str(row["severity"]), "resolved"],
                int(row.get("resolved_total") or 0),
            )

        return [jobs, job_duration, alerts]


def init_metrics() -> None:
    global _metrics_initialized
    if _metrics_initialized:
        return

    BUILD_INFO.labels(version=config.APP_VERSION, environment=config.APP_ENV).set(1)
    FEATURE_FLAG_ENABLED.labels(feature="connections").set(1 if config.FEATURE_CONNECTIONS_ENABLED else 0)
    FEATURE_FLAG_ENABLED.labels(feature="scheduler").set(1 if config.SCHEDULER_ENABLED else 0)
    FEATURE_FLAG_ENABLED.labels(feature="generator").set(1 if config.GENERATOR_ENABLED else 0)
    FEATURE_FLAG_ENABLED.labels(feature="rate_limit").set(1 if config.RATE_LIMIT_ENABLED else 0)
    FEATURE_FLAG_ENABLED.labels(feature="alert_webhook").set(1 if config.ALERT_WEBHOOK_ENABLED else 0)
    for game_type in GAME_TYPES:
        RESERVE_TARGET.labels(game_type=game_type, kind="min").set(config.RESERVE_MIN_COUNT)
        RESERVE_TARGET.labels(game_type=game_type, kind="target").set(config.RESERVE_TARGET_COUNT)

    REGISTRY.register(ApplicationMetricsCollector())
    _metrics_initialized = True


def render_metrics() -> Response:
    payload = generate_latest(REGISTRY)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
