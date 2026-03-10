# GitHub Issue Pack: Crossword + Cryptic Feature Roadmap (March 2026)

This file contains one copy-pastable GitHub issue body per ticket.

Suggested labels:
- `area/frontend`
- `area/backend`
- `area/generation`
- `area/quality`
- `area/analytics`
- `type/feature`
- `type/tech-debt`
- `priority/p0`, `priority/p1`, `priority/p2`
- `size/s`, `size/m`, `size/l`, `size/xl`

---

## PLX-101: Enforce hard clue quality gate (crossword + cryptic)

**Priority:** P0  
**Size:** M (3-5 days)  
**Areas:** backend, generation, quality

### Problem
Bad clues are reaching production (placeholder/token content, answer leakage, boilerplate surfaces). Quality needs to be blocked at generation/publish time, not only detected later.

### Scope
- Strengthen quality rules for crossword clues in `services/api/app/services/puzzle_quality.py`.
- Strengthen cryptic candidate publishability checks in `services/api/app/services/cryptic_runtime.py`.
- Ensure admin generate/publish surfaces explicit failure reasons.
- Add/expand tests for known failure patterns.

### Acceptance Criteria
- Generation/publish fails if clue text contains placeholder/token strings.
- Generation/publish fails if clue contains full answer (including standalone-token checks).
- Cryptic publishability rejects boilerplate clue surfaces.
- Admin response includes machine-readable failure codes for quality rejects.
- Unit tests cover all new failure conditions.

### Test Checklist
- [ ] Run crossword quality tests and confirm new reject cases fail.
- [ ] Run cryptic runtime quality tests and confirm boilerplate/answer leak rejects.
- [ ] Manual admin generate call returns clear quality failure payload.
- [ ] Manual publish cannot promote a quality-failing puzzle.

### Dependencies
- None.

### Out of Scope
- Rewriting clue-generation strategy itself (handled in PLX-102/PLX-103).

---

## PLX-102: Cryptic surface rewrite v2 (proper, puzzling clues)

**Priority:** P0  
**Size:** L (6-10 days)  
**Areas:** backend, generation, cryptic

### Problem
Cryptic clues are too formulaic and sometimes spoil answers. Current surfaces read like templates rather than real cryptic clues.

### Scope
- Replace current surface templates in `services/api/app/services/cryptic_runtime.py` with richer realizations per mechanism.
- Align/extend planner phrasing in `services/cryptic-ml/cryptic_ml/planner.py`.
- Add anti-pattern detector for repetitive phrasing and low-variety clues.
- Keep strict validation for definition/wordplay consistency.

### Acceptance Criteria
- Each mechanism (charade/anagram/deletion/hidden if enabled) has at least 3-5 varied surface patterns.
- No selected clue contains the answer text.
- Clues pass validator and read naturally (human spot-check sample of 50).
- Mean duplicate surface rate in sample drops below 10%.

### Test Checklist
- [ ] Add tests for surface diversity and banned phrase patterns.
- [ ] Add golden-sample regression test set for cryptic outputs.
- [ ] Run `admin/cryptic/generate` preview and verify top candidates look non-formulaic.
- [ ] Verify selected candidate remains validator-passed.

### Dependencies
- PLX-101.

### Out of Scope
- ML reranker retraining workflow changes (existing pipeline remains).

---

## PLX-103: Crossword clue pipeline cleanup + fallback removal

**Priority:** P0  
**Size:** M (3-5 days)  
**Areas:** generation, crossword, quality

### Problem
Crossword clue pipeline still allows weak fallback content and generic clue text that harms solve quality.

### Scope
- Improve clue construction quality in `services/crossword-gen/scripts/rebuild_crossword_answer_clue_csv.py`.
- Tighten unresolved candidate handling in `services/crossword-gen/scripts/manage_crossword_clue_overrides.py`.
- Prevent low-quality fallback clue text from shipping to final CSV.
- Add quality report output for unresolved entries.

### Acceptance Criteria
- Generated CSV contains zero placeholder/token clues.
- Clue dedupe and answer-fragment stripping remain valid after changes.
- Unresolved low-quality clues are exported for editorial override, not silently published.
- Quality report includes total unresolved count and reasons.

### Test Checklist
- [ ] Run CSV rebuild script on current corpus.
- [ ] Verify no disallowed pattern appears in output CSV.
- [ ] Run override management script and confirm unresolved export works.
- [ ] Smoke-generate daily crossword and check clue quality manually.

### Dependencies
- PLX-101.

### Out of Scope
- Frontend gameplay changes.

---

## PLX-104: Cryptic reveal, hint ladder, and explanation view

**Priority:** P0  
**Size:** L (6-10 days)  
**Areas:** frontend, backend, cryptic UX

### Problem
Cryptic page has placeholder reveal behavior and lacks proper hint/explanation flow.

### Scope
- Implement actual reveal behavior in `apps/web/src/pages/Cryptic.tsx`.
- Add hint ladder: Hint 1 (non-spoiler), Hint 2 (stronger), Reveal.
- Add post-solve explanation panel showing mechanism + wordplay breakdown.
- Extend API models/routes if needed to return explanation-safe metadata.

### Acceptance Criteria
- Reveal button reveals answer and records telemetry.
- Hint ladder is progressive and non-spoiler-first.
- Explanation appears only after solve/reveal/give-up.
- Telemetry includes hint usage step and reveal usage.

### Test Checklist
- [ ] Manual solve path: no hints -> correct -> explanation visible.
- [ ] Manual hint path: hint1/hint2/reveal event sequence recorded.
- [ ] Regression: input/submit/check-length still works.
- [ ] Accessibility check for ARIA/status updates in hint/explanation UI.

### Dependencies
- PLX-101, PLX-102.

### Out of Scope
- Multi-clue cryptic grids.

---

## PLX-105: Crossword granular assist controls + optional autocheck

**Priority:** P1  
**Size:** L (6-10 days)  
**Areas:** frontend, gameplay, telemetry

### Problem
Crossword assist controls are too coarse (entry/all only). Missing expected controls like check/reveal square/word and optional autocheck.

### Scope
- Add controls for check/reveal square and check/reveal word.
- Add optional autocheck toggle in gameplay settings.
- Extend grid action model in `apps/web/src/components/PuzzleGrid.tsx`.
- Extend telemetry schema/events in `apps/web/src/api/puzzles.ts`.

### Acceptance Criteria
- User can perform check/reveal at square and word granularity.
- Existing controls (entry/all) continue to function.
- Autocheck can be toggled on/off and persists locally.
- Telemetry captures granular assist actions.

### Test Checklist
- [ ] Manual test each new assist action on correct and incorrect letters.
- [ ] Confirm no regressions for check-entry/check-all/reveal-all/clear-all.
- [ ] Verify action counts in recap still correct.
- [ ] Verify telemetry payloads for new action types.

### Dependencies
- PLX-101.

### Out of Scope
- Contest lockouts (handled in PLX-301).

---

## PLX-106: Clue-quality feedback loop (player ratings + reason)

**Priority:** P1  
**Size:** M (3-5 days)  
**Areas:** frontend, backend, analytics

### Problem
No direct user-level clue quality signal is captured, slowing quality iteration.

### Scope
- Add thumbs up/down UI for clues (cryptic first, crossword optional).
- Add optional reason tags for downvotes.
- Persist feedback in backend repository layer and expose in admin analytics.

### Acceptance Criteria
- User can submit clue feedback with optional reason.
- Feedback is persisted with puzzle/clue identifiers.
- Admin can query feedback aggregates by date and clue type.
- Duplicate spam protection per session is applied.

### Test Checklist
- [ ] Submit positive and negative ratings from UI.
- [ ] Verify persisted rows in DB and API responses.
- [ ] Verify duplicate submission handling.
- [ ] Verify admin summary includes feedback metrics.

### Dependencies
- PLX-101.

### Out of Scope
- Automated retraining triggers based on feedback.

---

## PLX-201: Rebus + pencil mode

**Priority:** P1  
**Size:** XL (11-15 days)  
**Areas:** frontend, data model

### Problem
Grid supports only single-letter fills and no pencil mode, missing expected advanced crossword behavior.

### Scope
- Add pencil mode state and visual treatment.
- Add optional multi-character cell support (rebus).
- Update save/load logic and completion logic accordingly.
- Ensure clue/check/reveal actions handle rebus cells.

### Acceptance Criteria
- User can toggle pencil mode and enter tentative values.
- Rebus cells accept multi-letter values.
- Validation/check/reveal respects rebus rules.
- Persistence roundtrip works for pencil + rebus values.

### Test Checklist
- [ ] Keyboard entry in normal vs pencil mode.
- [ ] Rebus entry solve and check behavior.
- [ ] Reload page preserves state correctly.
- [ ] Completion detection works with rebus entries.

### Dependencies
- PLX-105.

### Out of Scope
- New rebus-specific puzzle authoring UI.

---

## PLX-202: Archive search/filter/calendar navigation

**Priority:** P1  
**Size:** L (6-10 days)  
**Areas:** frontend, backend API

### Problem
Archive is page/cursor based only; lacks fast discovery and historical browsing.

### Scope
- Add query parameters for search/filter in `/puzzles/archive`.
- Add date jump/calendar input and filter controls in `Archive.tsx`.
- Optional filters: difficulty, gameType, theme tags, title text.

### Acceptance Criteria
- Archive supports date jump and text search.
- Filters apply server-side and preserve pagination behavior.
- Empty-state messaging is clear for no results.
- URL reflects active filters for shareable state.

### Test Checklist
- [ ] Filter combinations return expected subsets.
- [ ] Pagination remains stable under filters.
- [ ] Direct URL load restores filter state.
- [ ] Performance sanity check on archive query latency.

### Dependencies
- None.

### Out of Scope
- Constructor/editor profile pages.

---

## PLX-203: Player stats page (personal performance dashboard)

**Priority:** P1  
**Size:** L (6-10 days)  
**Areas:** frontend, analytics API

### Problem
Current stats are limited to per-puzzle recap and basic admin analytics. Players lack personal history and trend visibility.

### Scope
- Add player-facing stats page route and UI.
- Include streak history, median solve time, clean-solve rate, completion rate.
- Add backend endpoints for session-aggregated personal stats (anonymous session or account id).

### Acceptance Criteria
- Stats page loads and displays historical performance metrics.
- Time-window filters (7/30/90 days) available.
- Metrics match telemetry source-of-truth queries.
- Works on desktop and mobile layouts.

### Test Checklist
- [ ] Validate metric calculations against fixture data.
- [ ] Verify filters update charts/cards correctly.
- [ ] Verify no-data state for new users.
- [ ] Basic accessibility checks on charts and stat cards.

### Dependencies
- PLX-106 recommended.

### Out of Scope
- Public/global leaderboard.

---

## PLX-204: Account + cloud sync for puzzle progress

**Priority:** P1  
**Size:** XL (11-15 days)  
**Areas:** backend auth/session, frontend state

### Problem
Progress is local-storage only; users lose continuity across devices/browsers.

### Scope
- Introduce user identity/auth (or durable anonymous account token).
- Persist progress server-side (grid state, completion, streak inputs).
- Add sync conflict strategy (latest-write or merge policy).
- Keep local fallback for offline use.

### Acceptance Criteria
- Progress syncs across at least two devices for same account.
- Local/offline play resumes and syncs when online.
- Streak logic remains stable after sync.
- Data model supports both crossword and cryptic progress.

### Test Checklist
- [ ] Cross-device resume test (device A to B).
- [ ] Offline edits then reconnect sync test.
- [ ] Conflict scenario test with concurrent edits.
- [ ] Privacy/security validation for stored progress.

### Dependencies
- PLX-203 optional.

### Out of Scope
- Social graph and friend features.

---

## PLX-205: Editorial metadata + puzzle notes

**Priority:** P2  
**Size:** M (3-5 days)  
**Areas:** backend schema, frontend display

### Problem
Puzzle pages lack editorial context (constructor, editor, notes/theme writeup), which is standard on major puzzle products.

### Scope
- Extend puzzle metadata to include byline/editor/notes fields.
- Render metadata in Daily/Cryptic pages.
- Add optional note snippet in archive entries.

### Acceptance Criteria
- Puzzle metadata schema supports constructor/editor/notes.
- Daily and Cryptic pages display metadata when present.
- Existing puzzles without metadata still render cleanly.

### Test Checklist
- [ ] Backfill-safe migration behavior.
- [ ] Display checks on both puzzle types.
- [ ] Archive card optional-note display behavior.
- [ ] Validate no layout break on long notes.

### Dependencies
- None.

### Out of Scope
- Full CMS/editorial tooling.

---

## PLX-301: Contest mode (assist/reveal lockout)

**Priority:** P2  
**Size:** M (3-5 days)  
**Areas:** frontend, admin publishing

### Problem
No strict “no assists” mode for competitive or event-based puzzle days.

### Scope
- Add contest-mode flag at publish or puzzle metadata level.
- Disable hints/check/reveal controls in contest mode.
- Add clear UI indicator and telemetry tagging for contest sessions.

### Acceptance Criteria
- Contest mode can be enabled per puzzle date/game type.
- Disallowed actions are hidden or disabled with explanation.
- Telemetry marks contest sessions distinctly.

### Test Checklist
- [ ] Contest mode toggle through admin flow.
- [ ] Verify restricted controls in UI.
- [ ] Verify normal mode unaffected.
- [ ] Verify telemetry includes contest flag.

### Dependencies
- PLX-105 recommended.

### Out of Scope
- Prize handling or anti-cheat system.

---

## PLX-302: Challenge + leaderboard layer

**Priority:** P2  
**Size:** XL (11-15 days)  
**Areas:** backend, frontend, product

### Problem
No competitive/social loop to drive retention and sharing.

### Scope
- Add challenge creation/share flow.
- Add leaderboard API and UI (daily/weekly scopes).
- Add privacy controls for display name and ranking visibility.

### Acceptance Criteria
- Users can create/join challenge links.
- Leaderboards render correctly with pagination.
- Opt-out/privacy controls work.
- Abuse protections (rate limits/basic anti-spam) in place.

### Test Checklist
- [ ] Challenge link flow end-to-end.
- [ ] Leaderboard ranking correctness for fixture data.
- [ ] Privacy toggle behavior verification.
- [ ] Load test basic leaderboard queries.

### Dependencies
- PLX-204.

### Out of Scope
- Real-time multiplayer co-solving.

---

## PLX-303: Print/PDF export + text-only accessibility view

**Priority:** P2  
**Size:** L (6-10 days)  
**Areas:** frontend, backend export

### Problem
Missing print/export and alternative accessible formats.

### Scope
- Add print-friendly puzzle layout.
- Add optional PDF export endpoint.
- Add text-only clue/answer structure view optimized for screen readers.

### Acceptance Criteria
- Users can print puzzle cleanly from browser.
- PDF export works for both crossword and cryptic.
- Text-only mode passes basic accessibility checks.

### Test Checklist
- [ ] Browser print preview QA on major viewport sizes.
- [ ] PDF export generation and download test.
- [ ] Screen reader walkthrough for text-only mode.
- [ ] Verify no answer leakage in pre-solve exports.

### Dependencies
- None.

### Out of Scope
- Full offline app packaging.

---

## Milestone Suggestions

### Milestone 1: `Quality Floor` (4 weeks)
- PLX-101
- PLX-102
- PLX-103
- PLX-104

### Milestone 2: `Core Solver UX` (4-6 weeks)
- PLX-105
- PLX-106
- PLX-202

### Milestone 3: `Retention + Platform` (6-10 weeks)
- PLX-203
- PLX-204
- PLX-205
- PLX-301
- PLX-302
- PLX-303

