# Pokeleximon

Pokeleximon is a Pokemon-themed daily word-games app. The core product is a daily crossword published at `00:00` Europe/London, with a separate daily cryptic minigame driven by its own generation pipeline. The app is web-first, mobile-friendly, and built to support additional game formats over time.

## Product Summary

- Daily Pokemon crossword with standard, curated clues.
- Separate daily cryptic clue game with a distinct ML-assisted pipeline.
- Archive, local progress, stats, leaderboard, challenge, and admin surfaces in the web app.
- Operational publishing flow with reserve generation, scheduled publishing, rollback, and alerts.
- PokeAPI-derived source data cached and transformed offline into runtime artifacts.

The main product requirements live in [`PRD.md`](/Users/ben.hutchinson/code/personal/pokeleximon/PRD.md).

## Architecture

### Runtime surfaces

- [`apps/web`](/Users/ben.hutchinson/code/personal/pokeleximon/apps/web): React + Vite frontend.
- [`services/api`](/Users/ben.hutchinson/code/personal/pokeleximon/services/api): FastAPI app for public puzzle endpoints, admin flows, telemetry, scheduler, and reserve publishing.
- [`services/crossword-gen`](/Users/ben.hutchinson/code/personal/pokeleximon/services/crossword-gen): offline crossword wordlist/clue artifact pipeline.
- [`services/cryptic-ml`](/Users/ben.hutchinson/code/personal/pokeleximon/services/cryptic-ml): separate cryptic candidate generation and ranking scaffold.
- [`data`](/Users/ben.hutchinson/code/personal/pokeleximon/data): generated runtime artifacts, including the curated crossword CSV used by the API.

### Important runtime rule

The crossword generator does not use live PokeAPI data at runtime. It reads the curated CSV at [`data/wordlist_crossword_answer_clue.csv`](/Users/ben.hutchinson/code/personal/pokeleximon/data/wordlist_crossword_answer_clue.csv), with the container contract documented in [`docs/adr/0001-crossword-curated-csv-source.md`](/Users/ben.hutchinson/code/personal/pokeleximon/docs/adr/0001-crossword-curated-csv-source.md).

## Local Development

### Prerequisites

- Node.js and `npm`
- Python 3
- Docker with `docker compose`

### 1. Start the API stack

From [`services/api`](/Users/ben.hutchinson/code/personal/pokeleximon/services/api):

```bash
cp .env.example .env
docker compose up --build
```

This starts:

- API at `http://localhost:8000`
- Postgres at `localhost:5432`
- Redis at `localhost:6379`

Health check:

```bash
curl -sS http://localhost:8000/health
```

### 2. Start the web app

From [`apps/web`](/Users/ben.hutchinson/code/personal/pokeleximon/apps/web):

```bash
cp .env.example .env
npm install
npm run dev
```

The Vite app runs at `http://localhost:5173` and proxies `/api` requests to `http://localhost:8000`.

### 3. Open the main routes

- `/daily`
- `/cryptic`
- `/archive`
- `/stats`
- `/leaderboard`
- `/admin`
- `/text-only`

`/connections` exists in the frontend but is feature-gated by `VITE_FEATURE_CONNECTIONS_ENABLED`.

## Environment Notes

### Frontend

[`apps/web/.env.example`](/Users/ben.hutchinson/code/personal/pokeleximon/apps/web/.env.example) includes:

- `VITE_SENTRY_*` for frontend observability
- `VITE_ADMIN_API_TOKEN` for admin requests from the web UI
- `VITE_FEATURE_CONNECTIONS_ENABLED` for the experimental Connections route

### API

[`services/api/.env.example`](/Users/ben.hutchinson/code/personal/pokeleximon/services/api/.env.example) covers:

- `DATABASE_URL`
- `REDIS_URL`
- admin auth and rate limiting
- scheduler and reserve generation
- artifact storage
- offline PokeAPI refresh command configuration
- `CROSSWORD_CSV_PATH` override for crossword runtime input

## Generation and Publishing Model

- Daily publication targets `00:00` Europe/London and is DST-aware.
- Crossword and cryptic generation are intentionally separated.
- Crossword reserve generation uses curated local artifacts.
- Cryptic generation builds ranked candidates and can promote trained ranker models.
- The API includes admin endpoints for generation, publish, rollback, reserve top-up, jobs, alerts, and analytics.

Request/response examples are in [`docs/api-examples.md`](/Users/ben.hutchinson/code/personal/pokeleximon/docs/api-examples.md).

## Rebuilding Content Artifacts

If you change crossword source data or clue quality rules, rebuild the offline artifacts from [`services/crossword-gen`](/Users/ben.hutchinson/code/personal/pokeleximon/services/crossword-gen):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_wordlist.py
python scripts/build_crossword_wordlist.py
python scripts/build_detail_corpus.py
python scripts/rebuild_crossword_answer_clue_csv.py
```

For the separate cryptic pipeline, see [`services/cryptic-ml/README.md`](/Users/ben.hutchinson/code/personal/pokeleximon/services/cryptic-ml/README.md).

## Testing

### Frontend smoke/e2e

From [`apps/web`](/Users/ben.hutchinson/code/personal/pokeleximon/apps/web):

```bash
npm run test:e2e
```

The smoke coverage lives in [`apps/web/tests/smoke.spec.ts`](/Users/ben.hutchinson/code/personal/pokeleximon/apps/web/tests/smoke.spec.ts).

### API tests

API tests live under [`services/api/tests`](/Users/ben.hutchinson/code/personal/pokeleximon/services/api/tests).

## Useful Docs

- [`PRD.md`](/Users/ben.hutchinson/code/personal/pokeleximon/PRD.md)
- [`SESSION_CHECKLIST.md`](/Users/ben.hutchinson/code/personal/pokeleximon/SESSION_CHECKLIST.md)
- [`docs/api-examples.md`](/Users/ben.hutchinson/code/personal/pokeleximon/docs/api-examples.md)
- [`docs/adr/README.md`](/Users/ben.hutchinson/code/personal/pokeleximon/docs/adr/README.md)
- [`infra/production/aws-ec2/RUNBOOK.md`](/Users/ben.hutchinson/code/personal/pokeleximon/infra/production/aws-ec2/RUNBOOK.md)
- [`services/api/README.md`](/Users/ben.hutchinson/code/personal/pokeleximon/services/api/README.md)
- [`services/crossword-gen/README.md`](/Users/ben.hutchinson/code/personal/pokeleximon/services/crossword-gen/README.md)
- [`services/cryptic-ml/README.md`](/Users/ben.hutchinson/code/personal/pokeleximon/services/cryptic-ml/README.md)
