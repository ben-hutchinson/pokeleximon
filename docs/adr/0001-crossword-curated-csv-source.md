# ADR 0001: Crossword Runtime Source of Truth Is Curated CSV

- Status: Accepted
- Date: 2026-02-17
- Owners: API + Crossword generation

## Context

The crossword reserve generator originally derived clues directly from PokeAPI payloads at runtime. That produced unstable clue quality and duplicate/vague clue text.

The current implementation already moved runtime generation to a curated worksheet CSV:

- Runtime file: `/Users/ben.hutchinson/code/pokeleximon/data/wordlist_crossword_answer_clue.csv`
- API loader: `/Users/ben.hutchinson/code/pokeleximon/services/api/app/services/reserve_generator.py`
- Container mount contract: `../../data:/app/data:ro` in `/Users/ben.hutchinson/code/pokeleximon/services/api/docker-compose.yml`
- Optional runtime override: `CROSSWORD_CSV_PATH`

PokeAPI remains part of the offline enrichment/build pipeline, not the online crossword generation path.

## Decision

For `gameType=crossword`, the canonical runtime source of truth is the curated CSV (`wordlist_crossword_answer_clue.csv`).

- Reserve generation must load answer/clue rows from that CSV.
- The CSV may contain multiple clue rows per normalized answer; runtime generation selects one clue variant per answer per puzzle build.
- Offline clue-variant build should enforce a floor of at least 3 clues per answer (`build_crossword_clue_variants.py --cache-only --strict-min-clues`), using deterministic local fallbacks when external fetches are unavailable.
- Runtime crossword generation must not require live PokeAPI requests.
- PokeAPI is allowed for offline corpus build and clue enrichment workflows only.
- API puzzle metadata source for crossword should remain `curated`.

## Consequences

Positive:
- Stable, deterministic runtime input for daily/reserve generation.
- Higher clue quality via offline curation and override passes.
- Operational reliability (runtime decoupled from external API availability).

Tradeoffs:
- CSV curation pipeline becomes a release dependency.
- If CSV is stale or missing, crossword top-up fails until data is refreshed.

## Operational Contract

1. Keep `/Users/ben.hutchinson/code/pokeleximon/data/wordlist_crossword_answer_clue.csv` present in runtime environments.
2. In containerized API runtime, mount repo `/data` to `/app/data` read-only.
3. If required, set `CROSSWORD_CSV_PATH` explicitly to point at the curated CSV.

## Related

- `/Users/ben.hutchinson/code/pokeleximon/services/crossword-gen/scripts/rebuild_crossword_answer_clue_csv.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/crossword-gen/scripts/enrich_crossword_clues_external.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/crossword-gen/scripts/build_crossword_clue_variants.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/crossword-gen/scripts/manage_crossword_clue_overrides.py`
