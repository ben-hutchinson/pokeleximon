from __future__ import annotations

from collections import Counter
from collections import deque
from dataclasses import dataclass
import re
from typing import Any


ANSWER_RE = re.compile(r"[^A-Z]")
PLACEHOLDER_CLUE_RE = re.compile(
    r"(clue unavailable|pokemon answer|pokemon term|tbd|todo|placeholder)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class PublishabilityConfig:
    min_fill_percent: float = 100.0
    min_entry_count: int = 24
    max_entry_count: int = 44
    require_connected_open_cells: bool = True
    min_intersections_per_entry: int = 1
    min_share_entries_with_two_intersections: float = 0.65
    max_duplicate_answers: int = 0
    require_clues: bool = True
    min_clue_chars: int = 8
    min_clue_quality_ratio: float = 0.95


@dataclass(frozen=True)
class PublishabilityResult:
    publishable: bool
    blockers: list[str]
    checks: dict[str, bool]
    metrics: dict[str, float]


def _normalize_answer(text: str) -> str:
    return ANSWER_RE.sub("", text.upper())


def _entry_cells(entry: dict[str, Any]) -> list[tuple[int, int]]:
    cells = entry.get("cells", [])
    out: list[tuple[int, int]] = []
    if not isinstance(cells, list):
        return out
    for cell in cells:
        if not isinstance(cell, (list, tuple)) or len(cell) != 2:
            continue
        x, y = cell
        if isinstance(x, int) and isinstance(y, int):
            out.append((x, y))
    return out


def _open_cells(puzzle: dict[str, Any], entries: list[dict[str, Any]]) -> set[tuple[int, int]]:
    grid = puzzle.get("grid", {})
    if isinstance(grid, dict):
        cells = grid.get("cells")
        if isinstance(cells, list):
            out: set[tuple[int, int]] = set()
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                if bool(cell.get("isBlock", False)):
                    continue
                x = cell.get("x")
                y = cell.get("y")
                if isinstance(x, int) and isinstance(y, int):
                    out.add((x, y))
            if out:
                return out

    out: set[tuple[int, int]] = set()
    for entry in entries:
        out.update(_entry_cells(entry))
    return out


def _filled_cells(entries: list[dict[str, Any]], puzzle: dict[str, Any]) -> set[tuple[int, int]]:
    filled: set[tuple[int, int]] = set()
    for entry in entries:
        cells = _entry_cells(entry)
        answer = _normalize_answer(str(entry.get("answer", "")))
        for idx, cell in enumerate(cells):
            if idx < len(answer) and answer[idx].isalpha():
                filled.add(cell)

    grid = puzzle.get("grid", {})
    if isinstance(grid, dict):
        cells = grid.get("cells")
        if isinstance(cells, list):
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                if bool(cell.get("isBlock", False)):
                    continue
                value = cell.get("solution")
                if not isinstance(value, str):
                    continue
                if _normalize_answer(value):
                    x = cell.get("x")
                    y = cell.get("y")
                    if isinstance(x, int) and isinstance(y, int):
                        filled.add((x, y))
    return filled


def _entry_intersection_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    by_cell: dict[tuple[int, int], list[str]] = {}

    for entry in entries:
        entry_id = str(entry.get("id", ""))
        counts[entry_id] = 0
        for cell in _entry_cells(entry):
            by_cell.setdefault(cell, []).append(entry_id)

    for ids in by_cell.values():
        if len(ids) < 2:
            continue
        for entry_id in ids:
            counts[entry_id] = counts.get(entry_id, 0) + 1
    return counts


def _count_open_components(open_cells: set[tuple[int, int]]) -> int:
    if not open_cells:
        return 0
    seen: set[tuple[int, int]] = set()
    components = 0
    for start in open_cells:
        if start in seen:
            continue
        components += 1
        queue: deque[tuple[int, int]] = deque([start])
        seen.add(start)
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (x + dx, y + dy)
                if nxt in open_cells and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return components


def _good_clue(entry: dict[str, Any], min_chars: int) -> bool:
    clue = str(entry.get("clue", "")).strip()
    answer = _normalize_answer(str(entry.get("answer", "")))
    if len(clue) < min_chars:
        return False
    if PLACEHOLDER_CLUE_RE.search(clue):
        return False
    if answer:
        normalized_clue = _normalize_answer(clue)
        if normalized_clue == answer:
            return False
        if answer in normalized_clue:
            return False
    return True


def evaluate_publishability(
    puzzle: dict[str, Any],
    config: PublishabilityConfig | None = None,
) -> PublishabilityResult:
    cfg = config or PublishabilityConfig()

    raw_entries = puzzle.get("entries", [])
    entries = [entry for entry in raw_entries if isinstance(entry, dict)]
    open_cells = _open_cells(puzzle, entries)
    filled_cells = _filled_cells(entries, puzzle)
    open_components = _count_open_components(open_cells)
    fill_percent = 100.0 * (len(filled_cells) / len(open_cells)) if open_cells else 0.0

    intersection_counts = _entry_intersection_counts(entries)
    min_intersections = min(intersection_counts.values()) if intersection_counts else 0
    share_two_plus = (
        sum(1 for value in intersection_counts.values() if value >= 2) / len(intersection_counts)
        if intersection_counts
        else 0.0
    )

    answers = [_normalize_answer(str(entry.get("answer", ""))) for entry in entries]
    answer_counts = Counter(answer for answer in answers if answer)
    duplicate_answers = sum(count - 1 for count in answer_counts.values() if count > 1)

    clue_count = 0
    good_clue_count = 0
    if cfg.require_clues:
        for entry in entries:
            clue = str(entry.get("clue", "")).strip()
            if not clue:
                continue
            clue_count += 1
            if _good_clue(entry, cfg.min_clue_chars):
                good_clue_count += 1

    clue_quality_ratio = (
        (good_clue_count / len(entries)) if cfg.require_clues and entries else 1.0
    )

    checks = {
        "fill_percent": fill_percent >= cfg.min_fill_percent,
        "entry_count": cfg.min_entry_count <= len(entries) <= cfg.max_entry_count,
        "connected_open_cells": (not cfg.require_connected_open_cells) or (open_components == 1),
        "min_intersections": min_intersections >= cfg.min_intersections_per_entry,
        "intersection_share": share_two_plus >= cfg.min_share_entries_with_two_intersections,
        "duplicate_answers": duplicate_answers <= cfg.max_duplicate_answers,
        "clue_quality": (not cfg.require_clues)
        or (
            clue_count == len(entries)
            and clue_quality_ratio >= cfg.min_clue_quality_ratio
        ),
    }

    blockers = [name for name, passed in checks.items() if not passed]
    metrics = {
        "fillPercent": round(fill_percent, 2),
        "entryCount": float(len(entries)),
        "openCellComponents": float(open_components),
        "duplicateAnswers": float(duplicate_answers),
        "minIntersectionsPerEntry": float(min_intersections),
        "shareEntriesWithTwoIntersections": round(share_two_plus, 4),
        "clueQualityRatio": round(clue_quality_ratio, 4),
    }

    return PublishabilityResult(
        publishable=not blockers,
        blockers=blockers,
        checks=checks,
        metrics=metrics,
    )


def is_publishable(
    puzzle: dict[str, Any],
    config: PublishabilityConfig | None = None,
) -> bool:
    return evaluate_publishability(puzzle, config=config).publishable
