# Crossword Generator Service

## Word List Builder
Builds a normalized word list from PokeAPI sources with a local cache.

Runtime note: API crossword reserve generation reads the curated CSV at
`/Users/ben.hutchinson/code/pokeleximon/data/wordlist_crossword_answer_clue.csv`.
See ADR `/Users/ben.hutchinson/code/pokeleximon/docs/adr/0001-crossword-curated-csv-source.md`.

### Setup
```bash
cd /Users/ben.hutchinson/code/pokeleximon/services/crossword-gen
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run
```bash
python scripts/build_wordlist.py
python scripts/build_crossword_wordlist.py
python scripts/build_detail_corpus.py
python scripts/rebuild_crossword_answer_clue_csv.py
# Rebuild now runs the three provider workers (Bulbapedia, Serebii, PokemonDB)
# plus the product-owner checker and writes answer, clue 1, clue 2, clue 3.
# Rebuild now also writes unresolved quality reports:
# data/crossword_clue_unresolved_report.csv and .json
# Optional: external enrichment pass for generic clues (Bulbapedia-backed, cache-aware).
python scripts/enrich_crossword_clues_external.py
# Optional: legacy variant-expansion helper for diagnostics.
python scripts/build_crossword_clue_variants.py --min-clues-per-answer 3 --max-clues-per-answer 3
# Optional: deterministic offline pass of the legacy helper.
python scripts/build_crossword_clue_variants.py --cache-only --strict-min-clues --min-clues-per-answer 3 --max-clues-per-answer 3
# Optional: cache-only run to avoid network fetches.
python scripts/build_crossword_clue_variants.py --cache-only --dry-run --verbose
# Optional: cache-only pass (no network calls).
python scripts/enrich_crossword_clues_external.py --cache-only
# Optional: dry-run preview on first 150 fetch attempts.
python scripts/enrich_crossword_clues_external.py --dry-run --max-fetch 150 --verbose
# Optional: export unresolved fallback clues to a manual curation queue.
python scripts/manage_crossword_clue_overrides.py --skip-apply
# Edit data/crossword_clue_override_candidates.csv column manual_clue
# and/or data/crossword_clue_overrides.csv with answer, clue, enabled=true
# Then apply overrides and refresh candidate queue.
python scripts/manage_crossword_clue_overrides.py
# By default unresolved low-quality rows are excluded from output CSV.
# Use --allow-unresolved only for diagnostics.
# Optional: fetch missing detail payloads into cache while building corpus.
python scripts/build_detail_corpus.py --fetch-missing --request-delay-seconds 0.05
# Optional: short connectivity/progress probe (first 100 fetches only).
python scripts/build_detail_corpus.py --fetch-missing --max-fetch 100 --fetch-timeout-seconds 3 --progress-every 25
```

### 13x13 Benchmark (CP-SAT Trial)
```bash
python scripts/benchmark_13x13.py --attempts 100 --template-prefix quick_candidate_13x13_
python scripts/benchmark_13x13.py --attempts 100 --template-prefix quick_candidate_13x13_ --cp-sat --cp-sat-seconds 2.5 --cp-sat-max-domain 1500 --no-min-conflicts
python scripts/benchmark_13x13.py --attempts 100 --template-prefix quick_13x13_ --cp-sat --cp-sat-seconds 15 --no-min-conflicts --disallow-reuse
```

### Curate Feasible 13x13 Template Bank
```bash
python scripts/curate_feasible_templates.py --include-modular-candidates --attempts 3 --target-count 8 --cp-sat-seconds 15
```

### Connected 13x13 Search Pass
```bash
python scripts/generate_guardian_connected_templates.py --skip-fill --max-layout-attempts 80 --target-count 24 --layout-seconds 0.6 --output-prefix quick_guardian_connected_candidate_13x13_
python scripts/curate_feasible_templates.py --input-prefix quick_guardian_connected_candidate_13x13_ --output-prefix quick_guardian_connected_13x13_ --attempts 2 --max-seconds 6 --cp-sat-seconds 4 --cp-sat-max-domain 250 --target-count 8
python scripts/benchmark_13x13.py --attempts 100 --template-prefix quick_guardian_connected_13x13_ --cp-sat --cp-sat-seconds 4 --cp-sat-max-domain 250 --max-seconds 6 --no-min-conflicts --disallow-reuse
```

## Grid + Solver Skeleton
```bash
python scripts/solve_template.py
```

### Output
- Word list JSON: `/Users/ben.hutchinson/code/pokeleximon/data/wordlist.json`
- Crossword word list JSON: `/Users/ben.hutchinson/code/pokeleximon/data/wordlist_crossword.json`
- Detail corpus JSON: `/Users/ben.hutchinson/code/pokeleximon/data/pokeapi_detail_corpus.json`
- Answer corpus JSON: `/Users/ben.hutchinson/code/pokeleximon/data/pokeapi_answer_corpus.json`
- PokeAPI cache: `/Users/ben.hutchinson/code/pokeleximon/services/data/pokeapi/`
- Filler words: `/Users/ben.hutchinson/code/pokeleximon/services/crossword-gen/data/fillers.txt`
