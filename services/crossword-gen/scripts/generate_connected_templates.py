from __future__ import annotations

import argparse
from collections import Counter
import json
import random
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.detail_corpus import (  # noqa: E402
    build_word_metadata_index,
    clue_for_answer,
    load_detail_corpus_index,
)
from crossword.feasibility import build_words_by_length, evaluate_template_feasibility  # noqa: E402
from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.publishable import PublishabilityConfig, evaluate_publishability  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
DETAIL_CORPUS_PATH = ROOT_DIR / "data" / "pokeapi_detail_corpus.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate connected 13x13 template candidates and keep publishable CP-SAT passers"
    )
    parser.add_argument("--size", type=int, default=13)
    parser.add_argument("--target-count", type=int, default=16)
    parser.add_argument("--max-tries", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20260211)
    parser.add_argument("--output-prefix", type=str, default="quick_connected_candidate_13x13_")
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=TEMPLATE_DIR / "quick_connected_candidate_13x13_manifest.json",
    )
    parser.add_argument("--min-blocks", type=int, default=28)
    parser.add_argument("--max-blocks", type=int, default=62)
    parser.add_argument("--row-block-min", type=int, default=1)
    parser.add_argument("--row-block-max", type=int, default=6)
    parser.add_argument("--center-block-min", type=int, default=1)
    parser.add_argument("--center-block-max", type=int, default=7)
    parser.add_argument("--min-entries", type=int, default=24)
    parser.add_argument("--max-entries", type=int, default=44)
    parser.add_argument("--cp-sat-seconds", type=float, default=2.5)
    parser.add_argument("--max-seconds", type=float, default=3.0)
    parser.add_argument("--cp-sat-max-domain", type=int, default=250)
    parser.add_argument("--cp-sat-workers", type=int, default=8)
    parser.add_argument("--allow-reuse", action="store_true")
    parser.add_argument("--require-clues", action="store_true")
    return parser.parse_args()


def load_words_and_scores() -> tuple[list[str], dict[str, float], dict[str, dict[str, str]]]:
    path = WORDLIST_CROSSWORD_PATH if WORDLIST_CROSSWORD_PATH.exists() else WORDLIST_PATH
    data = json.loads(path.read_text())
    words = sorted({item["word"] for item in data if item.get("word")})
    scores: dict[str, float] = {}
    for item in data:
        word = item.get("word")
        if not word:
            continue
        source = item.get("sourceType", "")
        if source == "pokemon-species":
            scores[word] = 3.0
        elif source in {"move", "ability", "type"}:
            scores[word] = 2.0
        else:
            scores[word] = 1.5
    metadata = build_word_metadata_index(data)
    return words, scores, metadata


def _line_has_short_run(line: list[bool], min_len: int = 4) -> bool:
    run = 0
    for blocked in line:
        if blocked:
            if 0 < run < min_len:
                return True
            run = 0
        else:
            run += 1
    if 0 < run < min_len:
        return True
    return False


def _valid_row_patterns(size: int) -> list[tuple[bool, ...]]:
    patterns: list[tuple[bool, ...]] = []
    for mask in range(1 << size):
        line = [bool((mask >> bit) & 1) for bit in range(size)]
        if _line_has_short_run(line):
            continue
        patterns.append(tuple(line))
    return patterns


def _build_blocks(
    *,
    size: int,
    row_patterns: list[tuple[bool, ...]],
    center_patterns: list[tuple[bool, ...]],
    rng: random.Random,
) -> set[tuple[int, int]]:
    rows: list[tuple[bool, ...]] = [tuple(False for _ in range(size)) for _ in range(size)]
    for y in range(size // 2):
        pattern = rng.choice(row_patterns)
        rows[y] = pattern
        rows[size - 1 - y] = tuple(reversed(pattern))
    rows[size // 2] = rng.choice(center_patterns)

    blocks: set[tuple[int, int]] = set()
    for y in range(size):
        for x in range(size):
            if rows[y][x]:
                blocks.add((x, y))
    return blocks


def _is_connected_open_grid(size: int, blocks: set[tuple[int, int]]) -> bool:
    open_cells = [(x, y) for y in range(size) for x in range(size) if (x, y) not in blocks]
    if not open_cells:
        return False
    stack = [open_cells[0]]
    seen = {open_cells[0]}
    while stack:
        x, y = stack.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= size or ny >= size:
                continue
            cell = (nx, ny)
            if cell in blocks or cell in seen:
                continue
            seen.add(cell)
            stack.append(cell)
    return len(seen) == len(open_cells)


def _build_publishability_payload(
    size: int,
    blocks: set[tuple[int, int]],
    grid: Grid,
    entries,
    *,
    word_metadata_by_word: dict[str, dict[str, str]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cells = []
    for y in range(size):
        for x in range(size):
            if (x, y) in blocks:
                cells.append({"x": x, "y": y, "isBlock": True, "solution": None})
            else:
                cells.append({"x": x, "y": y, "isBlock": False, "solution": grid.get(x, y)})

    payload_entries = []
    for entry in entries:
        answer = "".join(grid.get(x, y) or "" for x, y in entry.cells)
        clue, source_ref = clue_for_answer(
            answer=answer,
            word_metadata_by_word=word_metadata_by_word,
            detail_corpus_by_ref=detail_corpus_by_ref,
        )
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
        "grid": {"width": size, "height": size, "cells": cells},
        "entries": payload_entries,
    }


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    words, scores, word_metadata_by_word = load_words_and_scores()
    detail_corpus_by_ref = load_detail_corpus_index(DETAIL_CORPUS_PATH)
    words_by_length = build_words_by_length(words, min_len=4, max_len=args.size)
    publish_cfg = PublishabilityConfig(require_clues=args.require_clues)

    all_row_patterns = _valid_row_patterns(args.size)
    row_patterns = [
        pattern
        for pattern in all_row_patterns
        if args.row_block_min <= sum(pattern) <= args.row_block_max
    ]
    center_patterns = [
        pattern
        for pattern in row_patterns
        if pattern == tuple(reversed(pattern))
        and args.center_block_min <= sum(pattern) <= args.center_block_max
    ]
    if not row_patterns or not center_patterns:
        raise RuntimeError("No row/center patterns available for the configured block ranges")

    stage_counts = Counter()
    accepted: list[dict[str, Any]] = []
    seen_signatures: set[tuple[tuple[int, int], ...]] = set()

    for _ in range(args.max_tries):
        stage_counts["tries"] += 1
        blocks = _build_blocks(
            size=args.size,
            row_patterns=row_patterns,
            center_patterns=center_patterns,
            rng=rng,
        )

        if not (args.min_blocks <= len(blocks) <= args.max_blocks):
            stage_counts["blocks_out_of_range"] += 1
            continue

        signature = tuple(sorted(blocks))
        if signature in seen_signatures:
            stage_counts["duplicate"] += 1
            continue
        seen_signatures.add(signature)

        if not _is_connected_open_grid(args.size, blocks):
            stage_counts["disconnected"] += 1
            continue

        entries = parse_entries(args.size, args.size, blocks)
        if not entries:
            stage_counts["no_entries"] += 1
            continue
        lengths = [entry.length for entry in entries]
        if min(lengths) < 4 or max(lengths) > args.size:
            stage_counts["slot_length_out_of_bounds"] += 1
            continue
        if not (args.min_entries <= len(entries) <= args.max_entries):
            stage_counts["entry_count_out_of_range"] += 1
            continue

        feasibility = evaluate_template_feasibility(
            entries,
            words_by_length=words_by_length,
            min_post_ac3_domain=1,
        )
        if not feasibility.feasible:
            stage_counts["ac3_infeasible"] += 1
            continue

        lengths_set = set(lengths)
        filtered_words = [word for word in words if len(word) in lengths_set]
        solver = Solver(
            Grid(args.size, args.size, blocks),
            entries,
            filtered_words,
            SolverConfig(
                max_steps=500000,
                max_candidates=8000,
                weighted_shuffle=True,
                allow_reuse=args.allow_reuse,
                max_seconds=args.max_seconds,
                debug=False,
                use_min_conflicts=False,
                use_cp_sat=True,
                cp_sat_first=True,
                cp_sat_max_seconds=args.cp_sat_seconds,
                cp_sat_max_domain_per_entry=args.cp_sat_max_domain,
                cp_sat_workers=args.cp_sat_workers,
            ),
            word_scores=scores,
        )

        start = perf_counter()
        solved = solver.solve()
        elapsed = perf_counter() - start
        if not solved:
            stage_counts[solver.cp_sat_status or "solve_failed"] += 1
            continue

        publishability = evaluate_publishability(
            _build_publishability_payload(
                args.size,
                blocks,
                solver.grid,
                entries,
                word_metadata_by_word=word_metadata_by_word,
                detail_corpus_by_ref=detail_corpus_by_ref,
            ),
            config=publish_cfg,
        )
        if not publishability.publishable:
            blocker = publishability.blockers[0] if publishability.blockers else "publishability_failed"
            stage_counts[f"publishability:{blocker}"] += 1
            continue

        stage_counts["accepted"] += 1
        # Prefer faster fills and moderate block counts.
        score = 100000.0 - elapsed * 100.0 - abs(len(blocks) - 45) * 2.0
        accepted.append(
            {
                "score": score,
                "blocks": blocks,
                "elapsedSeconds": elapsed,
                "entryCount": len(entries),
                "minLength": min(lengths),
                "maxLength": max(lengths),
            }
        )
        if len(accepted) >= args.target_count * 3:
            break

    accepted.sort(key=lambda row: row["score"], reverse=True)
    selected = accepted[: args.target_count]

    if not selected:
        print("connected_candidate_templates_written=0 (existing connected candidates preserved)")
    else:
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        for path in TEMPLATE_DIR.glob(f"{args.output_prefix}*.json"):
            path.unlink()
        for idx, row in enumerate(selected):
            name = f"{args.output_prefix}{idx}"
            payload = {
                "name": name,
                "width": args.size,
                "height": args.size,
                "blocks": sorted(list(row["blocks"])),
                "curationStats": {
                    "elapsedSeconds": row["elapsedSeconds"],
                    "entryCount": row["entryCount"],
                    "minLength": row["minLength"],
                    "maxLength": row["maxLength"],
                },
            }
            (TEMPLATE_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2))
            print(
                f"{name}: blocks={len(row['blocks'])} entries={row['entryCount']} "
                f"min_len={row['minLength']} max_len={row['maxLength']} "
                f"time={row['elapsedSeconds']:.2f}s"
            )
        print(f"connected_candidate_templates_written={len(selected)}")

    manifest = {
        "size": args.size,
        "seed": args.seed,
        "targetCount": args.target_count,
        "maxTries": args.max_tries,
        "outputPrefix": args.output_prefix,
        "selectedCount": len(selected),
        "stageCounts": dict(stage_counts),
        "selected": [
            {
                "name": f"{args.output_prefix}{idx}",
                "blocks": len(row["blocks"]),
                "entryCount": row["entryCount"],
                "minLength": row["minLength"],
                "maxLength": row["maxLength"],
                "elapsedSeconds": round(row["elapsedSeconds"], 4),
            }
            for idx, row in enumerate(selected)
        ],
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, indent=2))
    print(f"manifest_written={args.manifest_out}")
    print(f"stage_counts={dict(stage_counts)}")


if __name__ == "__main__":
    main()
