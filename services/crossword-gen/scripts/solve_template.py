from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from time import perf_counter
import os
import re

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

sys.setrecursionlimit(10000)

from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.publishable import PublishabilityConfig, evaluate_publishability  # noqa: E402
from crossword.seeding import build_seed_assignment  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402
from crossword.templates import load_templates  # noqa: E402

WORDLIST_PATH = BASE_DIR.parents[1] / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = BASE_DIR.parents[1] / "data" / "wordlist_crossword.json"
ANSWER_CLUE_CSV_PATH = BASE_DIR.parents[1] / "data" / "wordlist_crossword_answer_clue.csv"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
TOKEN_RE = re.compile(r"[^A-Z0-9]")


def _normalize_answer(answer: str) -> str:
    return TOKEN_RE.sub("", answer.upper())


def load_words_and_clues() -> tuple[list[str], dict[str, str]]:
    if not ANSWER_CLUE_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV source at {ANSWER_CLUE_CSV_PATH}")
    clues_by_word: dict[str, str] = {}
    with ANSWER_CLUE_CSV_PATH.open(newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            answer = _normalize_answer(row[0].strip())
            clue = row[1].strip()
            if not answer or not clue:
                continue
            if answer not in clues_by_word:
                clues_by_word[answer] = clue
    words = sorted(clues_by_word.keys())
    return words, clues_by_word


def build_word_scores() -> dict[str, float]:
    words, _ = load_words_and_clues()
    return {word: 1.0 for word in words}


def _build_publishability_puzzle(
    template,
    grid: Grid,
    entries,
    *,
    clues_by_word: dict[str, str],
) -> dict:
    cells = []
    for y in range(template.height):
        for x in range(template.width):
            if (x, y) in template.blocks:
                cells.append({"x": x, "y": y, "isBlock": True, "solution": None})
            else:
                cells.append({"x": x, "y": y, "isBlock": False, "solution": grid.get(x, y)})

    payload_entries = []
    for entry in entries:
        answer = "".join(grid.get(x, y) or "" for x, y in entry.cells)
        clue = clues_by_word.get(answer, "Pokemon term from the CSV lexicon.")
        source_ref = f"csv://wordlist_crossword_answer_clue.csv#{answer}"
        payload_entries.append(
            {
                "id": entry.id,
                "direction": entry.direction,
                "number": entry.number,
                "answer": answer,
                "clue": clue,
                "length": entry.length,
                "cells": [list(cell) for cell in entry.cells],
                "sourceRef": source_ref,
            }
        )

    return {
        "grid": {"width": template.width, "height": template.height, "cells": cells},
        "entries": payload_entries,
    }


def try_solve(
    template,
    words: list[str],
    scores: dict[str, float],
    *,
    clues_by_word: dict[str, str],
) -> bool:
    grid = Grid(template.width, template.height, template.blocks)
    entries = parse_entries(template.width, template.height, template.blocks)
    lengths = [e.length for e in entries]
    min_len = min(lengths) if lengths else 0
    max_len = max(lengths) if lengths else 0

    if min_len < 4:
        print(f"Template {template.name}: skipped (min entry length {min_len})")
        return False

    filtered_words = [
        w for w in words if len(w) in set(lengths) and 4 <= len(w) <= 13
    ]
    words_by_length: dict[int, list[str]] = {}
    for word in filtered_words:
        words_by_length.setdefault(len(word), []).append(word)

    attempts = 5
    debug = os.getenv("SOLVER_DEBUG", "0") == "1"
    use_seeding = os.getenv("SEED_MODE", "1") == "1"
    require_clues = os.getenv("REQUIRE_CLUES", "0") == "1"
    allow_reuse = os.getenv("ALLOW_REUSE", "0") == "1"
    for attempt in range(1, attempts + 1):
        grid = Grid(template.width, template.height, template.blocks)
        seed_assignments: dict[str, str] | None = None
        if use_seeding:
            seed_assignments = build_seed_assignment(
                entries,
                words_by_length=words_by_length,
                word_scores=scores,
                seed_count=3,
                min_seed_length=11,
                pool_size=250,
                max_tries=120,
            )
        solver = Solver(
            grid,
            entries,
            filtered_words,
            SolverConfig(
                max_steps=600000,
                max_candidates=8000,
                weighted_shuffle=True,
                allow_reuse=allow_reuse,
                max_seconds=20.0,
                debug=debug,
            ),
            word_scores=scores,
            initial_assignments=seed_assignments,
        )
        start = perf_counter()
        solved = solver.solve()
        elapsed = perf_counter() - start
        print(
            f"Template {template.name}: attempt={attempt}/{attempts}, solved={solved}, "
            f"steps={solver.steps}, checks={solver.candidate_checks}, depth={solver.max_depth}, "
            f"seeds={len(seed_assignments or {})}, min_len={min_len}, max_len={max_len}, time={elapsed:.2f}s"
        )
        if solved:
            publishability = evaluate_publishability(
                _build_publishability_puzzle(
                    template,
                    grid,
                    entries,
                    clues_by_word=clues_by_word,
                ),
                config=PublishabilityConfig(require_clues=require_clues),
            )
            print(
                f"Template {template.name}: publishable={publishability.publishable} "
                f"blockers={publishability.blockers}"
            )
            if not publishability.publishable:
                continue
            for y in range(grid.height):
                row = []
                for x in range(grid.width):
                    if grid.is_block(x, y):
                        row.append("#")
                    else:
                        row.append(grid.get(x, y) or ".")
                print("".join(row))
            return True
    return False


def main() -> None:
    templates = load_templates(TEMPLATE_DIR)
    size_preference = [13, 11, 9]
    templates = [
        t
        for t in templates
        if (
            t.width == t.height
            and t.width in size_preference
            and (
                t.name.startswith("auto_")
                or t.name.startswith("mini_")
                or t.name.startswith("constructive_")
                or t.name.startswith("a_9x9_")
            )
        )
    ]
    templates = sorted(templates, key=lambda t: (t.width, t.name))
    words, clues_by_word = load_words_and_clues()
    scores = build_word_scores()

    print("=== Adaptive Worksheet Track (13/11/9) ===")
    buckets: dict[int, list] = {size: [] for size in size_preference}
    for template in templates:
        entries = parse_entries(template.width, template.height, template.blocks)
        if not entries:
            continue
        lengths = [entry.length for entry in entries]
        if min(lengths) < 4 or max(lengths) > 13:
            continue
        buckets[template.width].append(template)

    solved_any = False
    for size in size_preference:
        size_templates = buckets.get(size, [])[:3]
        if not size_templates:
            continue
        print(f"=== {size}x{size} ===")
        for template in size_templates:
            if try_solve(
                template,
                words,
                scores,
                clues_by_word=clues_by_word,
            ):
                solved_any = True
                break
        if solved_any:
            break
    if not solved_any:
        print("No solution found for adaptive worksheet-track templates")


if __name__ == "__main__":
    main()
