# Pokeleximon API Service

Minimal FastAPI service scaffolding for the public and admin puzzle endpoints.

## Quickstart
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Docker Compose
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/api
cp .env.example .env
docker compose up --build
```

## OpenAPI Export
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/export_openapi.py
```
Output: `/Users/ben.hutchinson/code/pokeleximon/services/api/docs/openapi.json`

## Migrations (Alembic)
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/api
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic -c alembic.ini upgrade head
```

## Seed Reserve Puzzles (Dev)
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/api
docker compose exec api python scripts/seed_reserve.py --game-type crossword --count 10
docker compose exec api python scripts/seed_reserve.py --game-type cryptic --count 10
```

## Cache
Read endpoints cache for 5 minutes in Redis. Keys follow:
- `puzzle:daily:{gameType}:{date|latest}`
- `puzzle:id:{id}`
- `puzzle:archive:{gameType}:{limit}:{cursor}`
- `puzzle:meta:{id}`

## Metrics
- `GET /metrics` exposes Prometheus metrics for API traffic, process health, reserve coverage, users, gameplay activity, jobs, and alerts.
- In production this path is scraped only on the internal Docker network by Prometheus; it is not proxied publicly by Caddy.

## Examples
See `/Users/ben.hutchinson/code/pokeleximon/docs/api-examples.md`.

## Env
Create a local env file if needed:
```bash
cp .env.example .env
```
Set `DATABASE_URL` (use `postgresql+psycopg://...`) and `REDIS_URL` in `.env`.
Set reserve controls in `.env`:
- `ADMIN_AUTH_ENABLED` enforce admin endpoint authentication (`true`/`false`)
- `ADMIN_AUTH_TOKEN` shared secret token required on admin requests
- `ADMIN_AUTH_HEADER_NAME` admin token header name (default `X-Admin-Token`)
- `RATE_LIMIT_ENABLED` enable API rate limiting middleware (`true`/`false`)
- `RATE_LIMIT_PUBLIC_MAX_REQUESTS` max public requests per window (default `180`)
- `RATE_LIMIT_PUBLIC_WINDOW_SECONDS` public limiter window seconds (default `60`)
- `RATE_LIMIT_ADMIN_MAX_REQUESTS` max admin requests per window (default `60`)
- `RATE_LIMIT_ADMIN_WINDOW_SECONDS` admin limiter window seconds (default `60`)
- `RATE_LIMIT_TRUST_X_FORWARDED_FOR` trust `X-Forwarded-For` client IPs behind reverse proxy (`true`/`false`)
- `SENTRY_DSN` optional backend Sentry DSN
- `SENTRY_TRACES_SAMPLE_RATE` backend traces sample rate (`0..1`)
- `SENTRY_PROFILES_SAMPLE_RATE` backend profiles sample rate (`0..1`)
- `SENTRY_ENVIRONMENT` backend Sentry environment label
- `SENTRY_RELEASE` backend Sentry release label
- `SCHEDULER_ENABLED` enable/disable scheduler jobs (`true`/`false`)
- `PUBLISH_ON_STARTUP` publish today's puzzle once when API boots (`true`/`false`)
- `RESERVE_MIN_COUNT` low-reserve alert threshold (default `5`)
- `RESERVE_TARGET_COUNT` desired unpublished reserve size per game (default `30`)
- `RESERVE_TOPUP_INTERVAL_MINUTES` generator cadence (default `60`)
- `GENERATOR_ENABLED` enable/disable reserve top-up worker (`true`/`false`)
- `ALERT_WEBHOOK_ENABLED` enable external webhook notifications (`true`/`false`)
- `ALERT_WEBHOOK_URL` webhook URL (Slack/Teams-compatible JSON webhook)
- `ALERT_WEBHOOK_TIMEOUT_SECONDS` outbound timeout in seconds (default `5`)
- `POKEAPI_REFRESH_ENABLED` enable scheduled offline snapshot/artifact refresh command (`true`/`false`)
- `POKEAPI_REFRESH_ON_STARTUP` run refresh command once on API startup (`true`/`false`)
- `POKEAPI_REFRESH_CRON` cron schedule (5-field crontab, default `"15 2 * * *"`, Europe/London)
- `POKEAPI_REFRESH_COMMAND` shell command (tokenized via `shlex`) to regenerate snapshots/artifacts
- `POKEAPI_REFRESH_WORKDIR` optional working directory for refresh command
- `POKEAPI_REFRESH_TIMEOUT_SECONDS` command timeout in seconds (default `7200`)
- `ARTIFACT_STORAGE_ENABLED` persist generated puzzle artifacts (`true`/`false`)
- `ARTIFACT_STORAGE_BACKEND` artifact backend (`local` or `s3`, default `local`)
- `ARTIFACT_STORAGE_STRICT` fail request/job when artifact writes fail instead of best-effort logging (`true`/`false`, default `false`)
- `ARTIFACT_STORAGE_DIR` local artifact root directory (default `/tmp/pokeleximon-artifacts`)
- `ARTIFACT_PUBLIC_BASE_URL` optional public base URL for artifact references (default empty)
- `ARTIFACT_S3_BUCKET` S3 bucket name when `ARTIFACT_STORAGE_BACKEND=s3`
- `ARTIFACT_S3_PREFIX` S3 key prefix (default `artifacts`)
- `ARTIFACT_S3_REGION` S3 region (optional)
- `ARTIFACT_S3_ENDPOINT_URL` optional S3-compatible endpoint (useful for LocalStack/MinIO)
- `ARTIFACT_S3_ACCESS_KEY_ID` optional static access key (otherwise use AWS env/role)
- `ARTIFACT_S3_SECRET_ACCESS_KEY` optional static secret key
- `ARTIFACT_S3_SESSION_TOKEN` optional session token
- `ARTIFACT_S3_ADDRESSING_STYLE` optional `path` or `virtual`
- `ARTIFACT_S3_PRESIGN_TTL_SECONDS` return presigned GET URL when > 0 (default `0`)
- `CROSSWORD_CSV_PATH` optional override for crossword curated CSV path
- `CRYPTIC_CLUES_PATH` optional override for the curated cryptic lexicon path
- `CRYPTIC_CSV_PATH` legacy override for the curated cryptic lexicon path

Local testing tip:
- Keep `ARTIFACT_STORAGE_BACKEND=local` to write JSON artifacts under `ARTIFACT_STORAGE_DIR`.
- Switch to `ARTIFACT_STORAGE_BACKEND=s3` only in environments where S3 credentials/bucket are configured.
- Example refresh command:
  `POKEAPI_REFRESH_COMMAND=bash -lc 'cd /app/services/crossword-gen && python scripts/build_wordlist.py && python scripts/build_crossword_wordlist.py && python scripts/build_detail_corpus.py && python scripts/rebuild_crossword_answer_clue_csv.py'`

### Suggested env profiles
- Local/dev profile: `/Users/ben.hutchinson/code/pokeleximon/services/api/.env`
  - Includes a concrete daily refresh command + cron with repo-local paths.
- EC2 profile template: `/Users/ben.hutchinson/code/pokeleximon/services/api/.env.ec2.example`
  - Uses `/opt/pokeleximon/...` paths and S3 artifact defaults.

Important:
- The refresh command must run where crossword-gen scripts are available and where the curated CSV path is writable.
- If running via Docker Compose with read-only `/app/data` mount, keep refresh disabled in the API container and run refresh on host/worker instead.

## Endpoints
Base: `/api/v1`
- `GET /health`
- `GET /puzzles/daily`
- `GET /puzzles/{id}`
- `GET /puzzles/archive`
- `GET /puzzles/{id}/metadata`
- `POST /puzzles/cryptic/telemetry`
- `POST /puzzles/crossword/telemetry`
- `POST /puzzles/client-errors`
- `POST /admin/generate`
- `POST /admin/publish`
- `POST /admin/publish/daily`
- `POST /admin/publish/rollback`
- `GET /admin/analytics/summary`
- `GET /admin/reserve`
- `POST /admin/reserve/topup`
- `POST /admin/cryptic/generate`
- `GET /admin/alerts`
- `POST /admin/alerts/{id}/resolve`
- `GET /admin/jobs`
- `GET /admin/jobs/{id}`
- `POST /admin/puzzles/{id}/approve`
- `POST /admin/puzzles/{id}/reject`

## Reserve Generator Worker
- Scheduler runs reserve top-up periodically when `GENERATOR_ENABLED=true`.
- Optional scheduler job can run the PokeAPI snapshot/artifact refresh command when
  `POKEAPI_REFRESH_ENABLED=true`.
- Crossword reserve loads curated answer/clue rows from `/app/data/wordlist_crossword_answer_clue.csv` (or `CROSSWORD_CSV_PATH` override).
- Cryptic reserve loads curated answer/clue rows from `/app/cryptic_clues.json` by default, with legacy CSV fallback at `/app/data/wordlist_cryptic_answer_clue.csv`.
- `CRYPTIC_CLUES_PATH` can point at either the curated JSON file or the legacy CSV file.
- Canonical decision record: `/Users/ben.hutchinson/code/pokeleximon/docs/adr/0001-crossword-curated-csv-source.md`.
- Crossword generation now applies a publishability governance pass (fill ratio, clue uniqueness, intersection density, direction balance, word-length balance, and answer leakage checks) with bounded retries.
- Cryptic generation now uses manually curated clue variants only; the runtime picks an answer and one of its stored clues for the target date.
- The selected cryptic clue is still recorded in `cryptic_candidates` for telemetry linkage, but there is no live ranking/model pipeline in the generation path.
- Manual trigger:
```bash
ADMIN_TOKEN="replace-with-your-admin-token"
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" -X POST "http://localhost:8000/api/v1/admin/reserve/topup"
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" -X POST "http://localhost:8000/api/v1/admin/reserve/topup?gameType=crossword&targetCount=30"
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" -X POST "http://localhost:8000/api/v1/admin/reserve/topup?gameType=cryptic&targetCount=30"
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" -X POST "http://localhost:8000/api/v1/admin/cryptic/generate?limit=5&topK=3"
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" -X POST "http://localhost:8000/api/v1/admin/cryptic/generate?answerKey=FIRESTONE&topK=5&includeInvalid=true"
```
- Job history:
```bash
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" "http://localhost:8000/api/v1/admin/jobs?type=reserve_topup&limit=20"
```

## Rollback Playbook (One-click)
Use this when daily publish failed or produced a bad puzzle and you need a fast fallback.

API path:
```bash
ADMIN_TOKEN="replace-with-your-admin-token"
curl -H "X-Admin-Token: ${ADMIN_TOKEN}" -X POST \
  "http://localhost:8000/api/v1/admin/publish/rollback?gameType=crossword&date=2026-02-18&reason=manual%20rollback"
```

CLI path:
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/api
python scripts/rollback_daily_publish.py --game-type crossword --date 2026-02-18 --reason "manual rollback"
```
