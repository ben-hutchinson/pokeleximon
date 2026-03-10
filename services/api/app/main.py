from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from app.api.v1.router import router as v1_router
from app.core import config
from app.api.v1.models import HealthResponse
from app.core import db, cache, scheduler
from app.core.observability import init_sentry
from app.core.rate_limit import ApiRateLimitMiddleware
from app.core.security import validate_admin_auth_config

app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION)
app.add_middleware(ApiRateLimitMiddleware)


@app.on_event("startup")
def on_startup() -> None:
    init_sentry()
    validate_admin_auth_config()
    db.init_db()
    cache.init_cache()
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


app.include_router(v1_router)
