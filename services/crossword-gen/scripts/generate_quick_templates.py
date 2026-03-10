from __future__ import annotations

import argparse
import json
import random
import sys
from collections import deque
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.feasibility import build_words_by_length, evaluate_template_feasibility  # noqa: E402
from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"

SIZE = 13
DEFAULT_TARGET_COUNT = 48
DEFAULT_MAX_TRIES = 120000
OUTPUT_PREFIX_DEFAULT = "quick_candidate_13x13_"

# Middle-density quick-style range (13x13), biased toward longer entries.
MIN_BLOCKS = 24
MAX_BLOCKS = 44
MIN_LEN = 4
MAX_LEN = 13
TARGET_BLOCKS = 30
ROW_BLOCKS_MIN = 1
ROW_BLOCKS_MAX = 6
CENTER_BLOCKS_MIN = 1
CENTER_BLOCKS_MAX = 7

MIN_INTERSECTIONS_SHARE_GE2 = 0.72
MAX_LEN4_ENTRIES = 20
MAX_LEN10_ENTRIES = 8
MAX_ACROSS_DOWN_DIFF = 7
MIN_ENTRIES = 24
MAX_ENTRIES = 44
MIN_AVG_LEN = 5.8
MIN_POST_AC3_DOMAIN = 1

PROBE_SECONDS = 0.5
PROBE_MAX_STEPS = 300000


def load_words_and_scores() -> tuple[list[str], dict[str, float]]:
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
    return words, scores


def is_connected_open_grid(size: int, blocks: set[tuple[int, int]]) -> bool:
    open_cells = [(x, y) for y in range(size) for x in range(size) if (x, y) not in blocks]
    if not open_cells:
        return False
    start = open_cells[0]
    queue: deque[tuple[int, int]] = deque([start])
    seen = {start}
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if nx < 0 or ny < 0 or nx >= size or ny >= size:
                continue
            if (nx, ny) in blocks or (nx, ny) in seen:
                continue
            seen.add((nx, ny))
            queue.append((nx, ny))
    return len(seen) == len(open_cells)


def line_has_short_run(line: list[bool], min_len: int) -> bool:
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


def valid_row_patterns(size: int, min_len: int) -> list[tuple[bool, ...]]:
    patterns: list[tuple[bool, ...]] = []
    for mask in range(1 << size):
        line = [bool((mask >> bit) & 1) for bit in range(size)]
        if line_has_short_run(line, min_len):
            continue
        patterns.append(tuple(line))
    return patterns


def build_blocks_from_row_patterns(
    size: int,
    row_patterns: list[tuple[bool, ...]],
    center_patterns: list[tuple[bool, ...]],
) -> set[tuple[int, int]]:
    rows: list[tuple[bool, ...]] = [tuple(False for _ in range(size)) for _ in range(size)]
    for y in range(size // 2):
        pattern = random.choice(row_patterns)
        rows[y] = pattern
        rows[size - 1 - y] = tuple(reversed(pattern))
    rows[size // 2] = random.choice(center_patterns)

    blocks: set[tuple[int, int]] = set()
    for y in range(size):
        for x in range(size):
            if rows[y][x]:
                blocks.add((x, y))
    return blocks


def intersection_counts(entries) -> dict[str, int]:
    counts = {entry.id: 0 for entry in entries}
    by_cell: dict[tuple[int, int], list[str]] = {}
    for entry in entries:
        for cell in entry.cells:
            by_cell.setdefault(cell, []).append(entry.id)
    for entry_ids in by_cell.values():
        if len(entry_ids) < 2:
            continue
        for entry_id in entry_ids:
            counts[entry_id] += 1
    return counts


def template_passes_shape_rules(entries) -> bool:
    if not entries:
        return False
    if len(entries) < MIN_ENTRIES or len(entries) > MAX_ENTRIES:
        return False
    lengths = [entry.length for entry in entries]
    if min(lengths) < MIN_LEN or max(lengths) > MAX_LEN:
        return False
    if (sum(lengths) / len(lengths)) < MIN_AVG_LEN:
        return False
    len4 = sum(1 for length in lengths if length == 4)
    len10 = sum(1 for length in lengths if length == 10)
    if len4 > MAX_LEN4_ENTRIES or len10 > MAX_LEN10_ENTRIES:
        return False

    across = sum(1 for entry in entries if entry.direction == "across")
    down = len(entries) - across
    if abs(across - down) > MAX_ACROSS_DOWN_DIFF:
        return False

    counts = intersection_counts(entries)
    if any(value == 0 for value in counts.values()):
        return False
    share_ge2 = sum(1 for value in counts.values() if value >= 2) / max(len(counts), 1)
    if share_ge2 < MIN_INTERSECTIONS_SHARE_GE2:
        return False
    return True


def probe_score(
    entries,
    blocks: set[tuple[int, int]],
    words: list[str],
    scores: dict[str, float],
) -> tuple[float, bool]:
    lengths = {entry.length for entry in entries}
    filtered_words = [word for word in words if len(word) in lengths]
    solver = Solver(
        Grid(SIZE, SIZE, blocks),
        entries,
        filtered_words,
        SolverConfig(
            max_steps=PROBE_MAX_STEPS,
            max_candidates=8000,
            weighted_shuffle=True,
            allow_reuse=True,
            max_seconds=PROBE_SECONDS,
            debug=False,
        ),
        word_scores=scores,
    )
    solved = solver.solve()
    score = solver.max_depth * 250.0 + solver.candidate_checks * 0.05 + solver.steps * 2.0
    if solved:
        score += 100000.0
    return score, solved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quick-style 13x13 candidate templates")
    parser.add_argument("--target-count", type=int, default=DEFAULT_TARGET_COUNT)
    parser.add_argument("--max-tries", type=int, default=DEFAULT_MAX_TRIES)
    parser.add_argument("--output-prefix", type=str, default=OUTPUT_PREFIX_DEFAULT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    existing_paths = list(TEMPLATE_DIR.glob(f"{args.output_prefix}*.json"))

    words, scores = load_words_and_scores()
    words_by_length = build_words_by_length(words, min_len=MIN_LEN, max_len=SIZE)
    row_patterns = [
        pattern
        for pattern in valid_row_patterns(SIZE, MIN_LEN)
        if ROW_BLOCKS_MIN <= sum(pattern) <= ROW_BLOCKS_MAX
    ]
    center_patterns = [
        pattern
        for pattern in row_patterns
        if pattern == tuple(reversed(pattern))
        and CENTER_BLOCKS_MIN <= sum(pattern) <= CENTER_BLOCKS_MAX
    ]
    kept: list[tuple[float, bool, set[tuple[int, int]], list[int], int]] = []
    seen_block_signatures: set[tuple[tuple[int, int], ...]] = set()
    stage_counts = {
        "tries": 0,
        "dup": 0,
        "empty": 0,
        "disconnected": 0,
        "shape_fail": 0,
        "ac3_fail": 0,
        "accepted": 0,
    }

    for _ in range(args.max_tries):
        stage_counts["tries"] += 1
        blocks = build_blocks_from_row_patterns(SIZE, row_patterns, center_patterns)
        if len(blocks) < MIN_BLOCKS or len(blocks) > MAX_BLOCKS:
            stage_counts["empty"] += 1
            continue
        signature = tuple(sorted(blocks))
        if signature in seen_block_signatures:
            stage_counts["dup"] += 1
            continue
        seen_block_signatures.add(signature)

        if not is_connected_open_grid(SIZE, blocks):
            stage_counts["disconnected"] += 1
            continue

        entries = parse_entries(SIZE, SIZE, blocks)
        if not template_passes_shape_rules(entries):
            stage_counts["shape_fail"] += 1
            continue

        report = evaluate_template_feasibility(
            entries,
            words_by_length=words_by_length,
            min_post_ac3_domain=MIN_POST_AC3_DOMAIN,
        )
        if not report.feasible:
            stage_counts["ac3_fail"] += 1
            continue

        score, solved = probe_score(entries, blocks, words, scores)
        score -= abs(len(blocks) - TARGET_BLOCKS) * 3.5
        score += min(report.domain_sizes.values()) * 0.2
        entry_count = len(entries)
        score -= abs(entry_count - 32) * 6.0
        kept.append((score, solved, blocks, [entry.length for entry in entries], entry_count))
        stage_counts["accepted"] += 1

        kept.sort(key=lambda item: item[0], reverse=True)
        if len(kept) > args.target_count * 5:
            kept = kept[: args.target_count * 5]
        if len(kept) >= args.target_count and stage_counts["accepted"] >= args.target_count * 3:
            break

    top = kept[: args.target_count]
    if not top:
        print("quick_candidate_templates_written=0 (existing candidates preserved)")
        print("stage_counts", stage_counts)
        return

    for path in existing_paths:
        path.unlink()

    for idx, (_, solved, blocks, lengths, entry_count) in enumerate(top):
        name = f"{args.output_prefix}{idx}"
        out = {
            "name": name,
            "width": SIZE,
            "height": SIZE,
            "blocks": sorted(list(blocks)),
        }
        (TEMPLATE_DIR / f"{name}.json").write_text(json.dumps(out, indent=2))
        print(
            f"{name}: blocks={len(blocks)} open={SIZE*SIZE-len(blocks)} "
            f"entries={entry_count} min_len={min(lengths)} max_len={max(lengths)} "
            f"avg_len={sum(lengths)/len(lengths):.2f} solved_probe={solved}"
        )
    print(f"quick_candidate_templates_written={len(top)}")
    print("stage_counts", stage_counts)


if __name__ == "__main__":
    main()
