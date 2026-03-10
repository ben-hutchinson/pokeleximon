from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.feasibility import build_words_by_length, evaluate_template_feasibility  # noqa: E402
from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"

SIZE = 13
MIN_LEN = 4
MAX_BLOCK_LINES = 2
KEEP_STATIC_TOP = 24
OUTPUT_COUNT = 8
PROBE_SECONDS = 0.35


@dataclass(frozen=True)
class Candidate:
    row_blocks: tuple[int, ...]
    col_blocks: tuple[int, ...]
    blocks: set[tuple[int, int]]
    static_score: float
    lengths: list[int]


def load_words() -> tuple[list[str], dict[str, float]]:
    path = WORDLIST_CROSSWORD_PATH if WORDLIST_CROSSWORD_PATH.exists() else WORDLIST_PATH
    data = json.loads(path.read_text())
    words = sorted({item["word"] for item in data})
    scores: dict[str, float] = {}
    for item in data:
        word = item["word"]
        source = item.get("sourceType", "")
        if source == "pokemon-species":
            scores[word] = 3.0
        elif source in {"move", "ability", "type"}:
            scores[word] = 2.0
        else:
            scores[word] = 1.5
    return words, scores


def valid_block_lines(indices: tuple[int, ...], size: int, min_segment: int) -> bool:
    blocked = set(indices)
    run = 0
    for i in range(size):
        if i in blocked:
            if 0 < run < min_segment:
                return False
            run = 0
        else:
            run += 1
    if 0 < run < min_segment:
        return False
    return True


def iter_block_line_sets(size: int, max_lines: int) -> Iterable[tuple[int, ...]]:
    yield tuple()
    line_ids = list(range(size))
    for k in range(1, max_lines + 1):
        if k == 1:
            for i in line_ids:
                yield (i,)
        elif k == 2:
            for i in line_ids:
                for j in line_ids:
                    if j <= i:
                        continue
                    yield (i, j)


def build_blocks(row_blocks: tuple[int, ...], col_blocks: tuple[int, ...]) -> set[tuple[int, int]]:
    blocks: set[tuple[int, int]] = set()
    for y in row_blocks:
        for x in range(SIZE):
            blocks.add((x, y))
    for x in col_blocks:
        for y in range(SIZE):
            blocks.add((x, y))
    return blocks


def static_template_score(lengths: list[int]) -> float:
    score = 0.0
    count = len(lengths)
    len4 = sum(1 for l in lengths if l == 4)
    len13 = sum(1 for l in lengths if l == 13)
    long = sum(1 for l in lengths if l >= 11)
    medium = sum(1 for l in lengths if 5 <= l <= 8)
    if len4 > 0:
        score -= len4 * 6.0
    if len13 > 0:
        score -= len13 * 40.0
    score -= long * 5.0
    score += medium * 3.0
    score += count * 0.25
    return score


def build_candidates() -> list[Candidate]:
    candidates: list[Candidate] = []
    row_sets = [
        rows
        for rows in iter_block_line_sets(SIZE, MAX_BLOCK_LINES)
        if valid_block_lines(rows, SIZE, MIN_LEN)
    ]
    col_sets = [
        cols
        for cols in iter_block_line_sets(SIZE, MAX_BLOCK_LINES)
        if valid_block_lines(cols, SIZE, MIN_LEN)
    ]
    for row_blocks in row_sets:
        for col_blocks in col_sets:
            blocks = build_blocks(row_blocks, col_blocks)
            entries = parse_entries(SIZE, SIZE, blocks)
            if not entries:
                continue
            lengths = [entry.length for entry in entries]
            if min(lengths) < MIN_LEN:
                continue
            score = static_template_score(lengths)
            candidates.append(
                Candidate(
                    row_blocks=row_blocks,
                    col_blocks=col_blocks,
                    blocks=blocks,
                    static_score=score,
                    lengths=lengths,
                )
            )
    candidates.sort(key=lambda c: c.static_score, reverse=True)
    return candidates[:KEEP_STATIC_TOP]


def probe_candidate(
    candidate: Candidate,
    words: list[str],
    words_by_length: dict[int, list[str]],
    word_scores: dict[str, float],
) -> tuple[float, bool, int, int, int]:
    entries = parse_entries(SIZE, SIZE, candidate.blocks)
    report = evaluate_template_feasibility(
        entries,
        words_by_length=words_by_length,
        min_post_ac3_domain=2,
    )
    if not report.feasible:
        return (-1e9, False, 0, 0, 0)
    lengths = set(candidate.lengths)
    filtered_words = [word for word in words if len(word) in lengths]
    solver = Solver(
        Grid(SIZE, SIZE, candidate.blocks),
        entries,
        filtered_words,
        SolverConfig(
            max_steps=800000,
            max_candidates=8000,
            weighted_shuffle=True,
            allow_reuse=True,
            max_seconds=PROBE_SECONDS,
            debug=False,
        ),
        word_scores=word_scores,
    )
    solved = solver.solve()
    min_domain = min(report.domain_sizes.values()) if report.domain_sizes else 0
    score = (
        candidate.static_score
        + solver.max_depth * 100.0
        + solver.candidate_checks * 0.02
        + min_domain * 0.15
        + (10000.0 if solved else 0.0)
    )
    return (score, solved, solver.steps, solver.candidate_checks, solver.max_depth)


def write_templates(ranked: list[tuple[float, Candidate, bool, int, int, int]]) -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    for path in TEMPLATE_DIR.glob("constructive_13x13_*.json"):
        path.unlink()

    for idx, (_, candidate, _, _, _, _) in enumerate(ranked[:OUTPUT_COUNT]):
        path = TEMPLATE_DIR / f"constructive_13x13_{idx}.json"
        payload = {
            "name": f"constructive_13x13_{idx}",
            "width": SIZE,
            "height": SIZE,
            "blocks": sorted(list(candidate.blocks)),
        }
        path.write_text(json.dumps(payload, indent=2))


def main() -> None:
    words, word_scores = load_words()
    words_by_length = build_words_by_length(words, min_len=MIN_LEN, max_len=SIZE)
    candidates = build_candidates()
    ranked: list[tuple[float, Candidate, bool, int, int, int]] = []
    for candidate in candidates:
        score, solved, steps, checks, depth = probe_candidate(
            candidate, words=words, words_by_length=words_by_length, word_scores=word_scores
        )
        if score < -1e8:
            continue
        ranked.append((score, candidate, solved, steps, checks, depth))

    ranked.sort(key=lambda item: item[0], reverse=True)
    write_templates(ranked)
    print(f"candidates_kept={len(ranked)}")
    for score, candidate, solved, steps, checks, depth in ranked[:OUTPUT_COUNT]:
        print(
            f"score={score:.2f} solved={solved} steps={steps} checks={checks} depth={depth} "
            f"rows={candidate.row_blocks} cols={candidate.col_blocks} "
            f"entries={len(candidate.lengths)} min_len={min(candidate.lengths)} max_len={max(candidate.lengths)}"
        )


if __name__ == "__main__":
    main()
