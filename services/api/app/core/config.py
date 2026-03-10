import os


def _clean_env_text(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1]
    return value


APP_NAME = os.getenv("APP_NAME", "Pokeleximon API")
APP_ENV = os.getenv("APP_ENV", "dev")
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
ADMIN_AUTH_ENABLED = os.getenv("ADMIN_AUTH_ENABLED", "true").lower() in {"1", "true", "yes"}
ADMIN_AUTH_TOKEN = _clean_env_text("ADMIN_AUTH_TOKEN", "")
ADMIN_AUTH_HEADER_NAME = _clean_env_text("ADMIN_AUTH_HEADER_NAME", "X-Admin-Token")
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in {"1", "true", "yes"}
RATE_LIMIT_PUBLIC_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_PUBLIC_MAX_REQUESTS", "180"))
RATE_LIMIT_PUBLIC_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_PUBLIC_WINDOW_SECONDS", "60"))
RATE_LIMIT_ADMIN_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_ADMIN_MAX_REQUESTS", "60"))
RATE_LIMIT_ADMIN_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_ADMIN_WINDOW_SECONDS", "60"))
RATE_LIMIT_TRUST_X_FORWARDED_FOR = os.getenv("RATE_LIMIT_TRUST_X_FORWARDED_FOR", "false").lower() in {
    "1",
    "true",
    "yes",
}
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes"}
PUBLISH_ON_STARTUP = os.getenv("PUBLISH_ON_STARTUP", "true").lower() in {"1", "true", "yes"}
RESERVE_MIN_COUNT = int(os.getenv("RESERVE_MIN_COUNT", "5"))
RESERVE_TARGET_COUNT = int(os.getenv("RESERVE_TARGET_COUNT", "30"))
RESERVE_TOPUP_INTERVAL_MINUTES = int(os.getenv("RESERVE_TOPUP_INTERVAL_MINUTES", "60"))
GENERATOR_ENABLED = os.getenv("GENERATOR_ENABLED", "true").lower() in {"1", "true", "yes"}
FEATURE_CONNECTIONS_ENABLED = os.getenv("FEATURE_CONNECTIONS_ENABLED", "false").lower() in {"1", "true", "yes"}
ALERT_WEBHOOK_ENABLED = os.getenv("ALERT_WEBHOOK_ENABLED", "false").lower() in {"1", "true", "yes"}
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
ALERT_WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("ALERT_WEBHOOK_TIMEOUT_SECONDS", "5"))
POKEAPI_REFRESH_ENABLED = os.getenv("POKEAPI_REFRESH_ENABLED", "false").lower() in {"1", "true", "yes"}
POKEAPI_REFRESH_ON_STARTUP = os.getenv("POKEAPI_REFRESH_ON_STARTUP", "false").lower() in {"1", "true", "yes"}
POKEAPI_REFRESH_CRON = _clean_env_text("POKEAPI_REFRESH_CRON", "15 2 * * *")
POKEAPI_REFRESH_COMMAND = _clean_env_text("POKEAPI_REFRESH_COMMAND", "")
POKEAPI_REFRESH_WORKDIR = _clean_env_text("POKEAPI_REFRESH_WORKDIR", "")
POKEAPI_REFRESH_TIMEOUT_SECONDS = int(os.getenv("POKEAPI_REFRESH_TIMEOUT_SECONDS", "7200"))
SENTRY_DSN = _clean_env_text("SENTRY_DSN", "")
SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0"))
SENTRY_PROFILES_SAMPLE_RATE = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0"))
SENTRY_ENVIRONMENT = _clean_env_text("SENTRY_ENVIRONMENT", APP_ENV)
SENTRY_RELEASE = _clean_env_text("SENTRY_RELEASE", APP_VERSION)
ARTIFACT_STORAGE_ENABLED = os.getenv("ARTIFACT_STORAGE_ENABLED", "false").lower() in {"1", "true", "yes"}
ARTIFACT_STORAGE_BACKEND = os.getenv("ARTIFACT_STORAGE_BACKEND", "local").strip().lower()
ARTIFACT_STORAGE_DIR = os.getenv("ARTIFACT_STORAGE_DIR", "/tmp/pokeleximon-artifacts")
ARTIFACT_PUBLIC_BASE_URL = os.getenv("ARTIFACT_PUBLIC_BASE_URL", "")
ARTIFACT_S3_BUCKET = os.getenv("ARTIFACT_S3_BUCKET", "")
ARTIFACT_S3_PREFIX = os.getenv("ARTIFACT_S3_PREFIX", "artifacts")
ARTIFACT_S3_REGION = os.getenv("ARTIFACT_S3_REGION", "")
ARTIFACT_S3_ENDPOINT_URL = os.getenv("ARTIFACT_S3_ENDPOINT_URL", "")
ARTIFACT_S3_ACCESS_KEY_ID = os.getenv("ARTIFACT_S3_ACCESS_KEY_ID", "")
ARTIFACT_S3_SECRET_ACCESS_KEY = os.getenv("ARTIFACT_S3_SECRET_ACCESS_KEY", "")
ARTIFACT_S3_SESSION_TOKEN = os.getenv("ARTIFACT_S3_SESSION_TOKEN", "")
ARTIFACT_S3_ADDRESSING_STYLE = os.getenv("ARTIFACT_S3_ADDRESSING_STYLE", "")
ARTIFACT_S3_PRESIGN_TTL_SECONDS = int(os.getenv("ARTIFACT_S3_PRESIGN_TTL_SECONDS", "0"))
ARTIFACT_STORAGE_STRICT = os.getenv("ARTIFACT_STORAGE_STRICT", "false").lower() in {"1", "true", "yes"}
