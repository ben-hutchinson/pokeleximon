# Cryptic ML Delivery Plan

## Objective
Deliver a daily Pokemon cryptic minigame that improves quality over time while staying operationally safe for daily publishing.

## Hard Constraints
- Data source: PokeAPI-derived only.
- Cryptic pipeline is isolated from standard crossword clueing.
- Daily publish time uses `Europe/London`.
- Maintain reserve fallback so daily publication never blocks.

## Architecture
1. Build canonical `cryptic_lexicon` from existing PokeAPI wordlist and cached endpoint lists.
2. Generate clue plans (mechanism + definition + wordplay intent).
3. Realize candidate clues (template/LLM).
4. Validate candidates with strict rule gate.
5. Rank candidates (initial heuristics, later ML model).
6. Store top candidates in reserve.

## Proposed DB Tables (Phase 2+)

### `cryptic_lexicon`
- `id` (pk)
- `answer_key` (unique)
- `answer_display`
- `answer_tokens` (json)
- `enumeration`
- `source_type`
- `source_ref`
- `source_slug`
- `normalization_rule`
- `active`
- `created_at`

### `cryptic_candidates`
- `id` (pk)
- `date`
- `answer_key`
- `clue_text`
- `mechanism`
- `definition`
- `wordplay_plan` (json)
- `validator_passed` (bool)
- `validator_issues` (json)
- `rank_score` (float)
- `model_version`
- `created_at`

### `cryptic_feedback`
- `id` (pk)
- `candidate_id`
- `event_type` (`solve`, `check`, `reveal`, `abandon`, `rating`)
- `event_value` (json)
- `created_at`

### `cryptic_model_registry`
- `id` (pk)
- `model_version` (unique)
- `model_type` (`ranker`)
- `metrics` (json)
- `trained_at`
- `is_active`

## Training Strategy

### Stage A: Cold Start
- No model training.
- Use heuristic ranking:
  - validator pass required
  - prefer clean definition placement
  - penalize repetitive indicator language
- Status: implemented in `services/cryptic-ml/cryptic_ml/scorer.py`.
- Weights are configurable in `services/cryptic-ml/config/scoring.json`.
- Alternate tuning preset exists at `services/cryptic-ml/config/scoring.aggressive.json` for stricter ranking.

### Stage B: Ranker V1
- Train a lightweight model (logistic regression / gradient boosting) on telemetry labels:
  - success label proxy: solved without reveal + moderate solve time
- Features:
  - mechanism, answer length, clue length
  - lexical entropy, indicator diversity
  - validator warning count

### Stage C: Online Improvement
- Daily retrain or weekly retrain once sample size grows.
- Keep shadow scoring for rollback safety.
- Promote model only if metrics beat active baseline.

## Operational Gates
- Candidate must pass validator hard checks.
- Maintain reserve target (>= 5 minimum, 30 preferred).
- Low reserve auto-alert via existing operational alerts.

## Immediate Next Build Steps
1. Wire `services/cryptic-ml` lexicon build into admin top-up flow. ✅ Done (2026-02-11)
2. Store generated candidates in DB with validator metadata. ✅ Done (2026-02-11)
3. Add `/api/v1/admin/cryptic/generate` endpoint. ✅ Done (2026-02-11)
4. Add telemetry collection in cryptic page. ✅ Done (2026-02-11)
5. Add ranker training job and model registry entries. ✅ Done (2026-02-11)
