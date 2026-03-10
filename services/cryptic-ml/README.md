# Cryptic Clue Generator (ML Scaffold)

This service is the **separate daily cryptic minigame pipeline**. It is intentionally isolated from the main crossword generator.

## Why This Architecture Works
Training a model end-to-end from day one is high-risk because clue quality fails mostly due to noisy answers, not model size.

The robust path is:
1. **Canonical lexicon first** (clean answers from PokeAPI-derived data).
2. **Rule-based clue planning and validation** (enforce cryptic structure).
3. **ML ranking loop** (improve candidate ordering from real user telemetry).

That gives a stable quality floor now and measurable improvement later.

## Current Scope (Implemented)
- Lexicon builder from `/data/wordlist.json` plus cached PokeAPI list pages.
- Cryptic-specific normalization rules (including location suffix trimming).
- Rule-based clue planner with deterministic mechanisms:
  - `charade`, `anagram`, `hidden`, `deletion`
- Rule-based validator with mechanism checks:
  - enumeration validation
  - definition position validation
  - indicator presence checks
  - mechanism-specific metadata validation
  - answer leakage checks (except valid hidden clues)
- Rule-based quality scoring for candidate ranking:
  - validator status and issue counts
  - mechanism weighting
  - clue length/lexical variety heuristics
  - indicator and enumeration fit

## File Layout
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/cryptic_ml/normalizer.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/cryptic_ml/lexicon.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/cryptic_ml/planner.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/cryptic_ml/validator.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/scripts/build_lexicon.py`
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/scripts/sample_candidates.py`

## Normalization Rules
Rules are deterministic and source-type aware:

1. **Location suffix trimming**:
- `HEARTHOME-CITY` -> `HEARTHOME` (rule: `drop_location_suffix`)
- Repeated suffixes are trimmed from the end while answer length remains viable.

2. **Species honorific preservation**:
- `MR-MIME` stays `MR MIME` (rule: `preserve_species_honorific`)

3. **Hyphenated compound preservation**:
- `FIRE-STONE` becomes `FIRE STONE` (not truncated)

4. **Noisy item filtering**:
- `dynamax-crystal-*` and code-heavy item slugs are excluded.

## Data Contract (Lexicon)
Each lexicon row contains:
- `answer`: display answer (`MR MIME`)
- `answerKey`: compact canonical key (`MRMIME`)
- `enumeration`: `2,4`
- `answerTokens`: `['MR', 'MIME']`
- `sourceType`, `sourceRef`, `sourceSlug`
- `normalizationRule`
- `isMultiword`
- `metadata`

## Candidate Generation Contract
A candidate is generated via:
- `CluePlan`: answer + mechanism + definition + wordplay plan
- `ClueCandidate`: clue text realization from a plan
- `ValidationResult`: pass/fail + issues

## Phased ML Plan
### Phase 1 (Now)
- Deterministic pipeline: lexicon + plans + validator.
- Publish only validator-passing candidates.

### Phase 2
- Generate multiple candidates per answer using an LLM or templates.
- Add strict validator gates (definition position, leakage, enumeration).

### Phase 3
- Collect telemetry: solve rate, solve time, check/reveal usage.
- Train ranking model to score clue quality.
- Daily job chooses top-scoring candidate.

### Phase 4
- Continuous retraining schedule with model registry and A/B shadow evaluation.

## Run
From repo root:

```bash
python3 /Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/scripts/build_lexicon.py
python3 /Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/scripts/sample_candidates.py --limit 8 --top-per-entry 3
```

Output lexicon path:
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/data/cryptic_lexicon.json`

Score config path:
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/config/scoring.json`
- `/Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/config/scoring.aggressive.json`

Tune score behavior by editing `scoring.json` (no code changes needed).

Example with aggressive preset:
```bash
python3 /Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/scripts/sample_candidates.py \
  --limit 8 \
  --top-per-entry 3 \
  --score-config /Users/ben.hutchinson/code/pokeleximon/services/cryptic-ml/config/scoring.aggressive.json
```

## Notes
- Source remains PokeAPI-derived only (via cached list pages and wordlist).
- This scaffold is intentionally deterministic first; it is the foundation for stable ML improvement.
