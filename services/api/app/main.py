from fastapi import FastAPI, Response
from dotenv import load_dotenv

load_dotenv()

from app.api.v1.router import router as v1_router
from app.core import config
from app.api.v1.models import HealthResponse, ReadyResponse
from app.core import db, cache, scheduler
from app.core.metrics import PrometheusMiddleware, init_metrics, render_metrics
from app.core.observability import init_sentry
from app.core.rate_limit import ApiRateLimitMiddleware
from app.core.security import validate_admin_auth_config

app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION)
app.add_middleware(ApiRateLimitMiddleware)
app.add_middleware(PrometheusMiddleware)


@app.on_event("startup")
def on_startup() -> None:
    init_sentry()
    validate_admin_auth_config()
    db.init_db()
    cache.init_cache()
    init_metrics()
    scheduler.start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    cache.close_cache()
    db.close_db()
    scheduler.stop_scheduler()


@app.get("/health", response_model=HealthResponse)
def health_root():
    return {"status": "ok", "version": config.APP_VERSION}


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "version": config.APP_VERSION}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return render_metrics()


def _readiness_payload() -> dict[str, object]:
    checks: dict[str, str] = {}

    try:
        db.ping_db()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error:{type(exc).__name__}"

    try:
        cache.ping_cache()
        checks["cache"] = "ok"
    except Exception as exc:
        checks["cache"] = f"error:{type(exc).__name__}"

    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, "version": config.APP_VERSION, "checks": checks}


@app.get("/health/ready", response_model=ReadyResponse)
def health_ready(response: Response):
    payload = _readiness_payload()
    if payload["status"] != "ok":
        response.status_code = 503
    return payload


@app.get("/api/v1/health/ready", response_model=ReadyResponse)
def api_health_ready(response: Response):
    payload = _readiness_payload()
    if payload["status"] != "ok":
        response.status_code = 503
    return payload


app.include_router(v1_router)
