from __future__ import annotations

import random

from crossword.feasibility import evaluate_template_feasibility
from crossword.grid import Entry


def _build_overlap_pairs(entries: list[Entry]) -> dict[tuple[str, str], list[tuple[int, int]]]:
    index_by_entry: dict[str, dict[tuple[int, int], int]] = {}
    by_cell: dict[tuple[int, int], list[str]] = {}
    pairs: dict[tuple[str, str], list[tuple[int, int]]] = {}

    for entry in entries:
        local: dict[tuple[int, int], int] = {}
        for idx, cell in enumerate(entry.cells):
            local[cell] = idx
            by_cell.setdefault(cell, []).append(entry.id)
        index_by_entry[entry.id] = local

    for cell, entry_ids in by_cell.items():
        if len(entry_ids) < 2:
            continue
        for a in entry_ids:
            for b in entry_ids:
                if a == b:
                    continue
                pairs.setdefault((a, b), []).append(
                    (index_by_entry[a][cell], index_by_entry[b][cell])
                )
    return pairs


def _entry_degrees(entries: list[Entry]) -> dict[str, int]:
    by_cell: dict[tuple[int, int], list[str]] = {}
    for entry in entries:
        for cell in entry.cells:
            by_cell.setdefault(cell, []).append(entry.id)
    degrees = {entry.id: 0 for entry in entries}
    for ids in by_cell.values():
        if len(ids) < 2:
            continue
        for entry_id in ids:
            degrees[entry_id] += 1
    return degrees


def _weighted_shuffle(words: list[str], word_scores: dict[str, float]) -> list[str]:
    scored: list[tuple[float, str, float]] = []
    for word in words:
        weight = max(word_scores.get(word, 1.0), 0.0001)
        key = random.random() ** (1.0 / weight)
        scored.append((weight, word, key))
    scored.sort(key=lambda item: item[2], reverse=True)
    return [word for _, word, _ in scored]


def build_seed_assignment(
    entries: list[Entry],
    words_by_length: dict[int, list[str]],
    word_scores: dict[str, float],
    seed_count: int = 3,
    min_seed_length: int = 11,
    pool_size: int = 250,
    max_tries: int = 200,
) -> dict[str, str] | None:
    degrees = _entry_degrees(entries)
    overlap_pairs = _build_overlap_pairs(entries)
    candidates = [entry for entry in entries if entry.length >= min_seed_length]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda entry: (entry.length, degrees.get(entry.id, 0)),
        reverse=True,
    )[: max(seed_count * 3, seed_count)]
    seed_entries = ranked[:seed_count]

    domains: dict[str, list[str]] = {}
    for entry in seed_entries:
        words = words_by_length.get(entry.length, [])
        if not words:
            return None
        sorted_words = sorted(words, key=lambda word: word_scores.get(word, 0.0), reverse=True)
        domains[entry.id] = sorted_words[:pool_size]

    def compatible(entry_id: str, word: str, assigned: dict[str, str]) -> bool:
        for other_id, other_word in assigned.items():
            pairs = overlap_pairs.get((entry_id, other_id), [])
            for pos_a, pos_b in pairs:
                if word[pos_a] != other_word[pos_b]:
                    return False
        return True

    order = [entry.id for entry in seed_entries]
    for _ in range(max_tries):
        assigned: dict[str, str] = {}
        for entry_id in order:
            shuffled = _weighted_shuffle(domains[entry_id], word_scores)
            pick = None
            for word in shuffled:
                if word in assigned.values():
                    continue
                if compatible(entry_id, word, assigned):
                    pick = word
                    break
            if pick is None:
                assigned = {}
                break
            assigned[entry_id] = pick
        if assigned:
            report = evaluate_template_feasibility(
                entries,
                words_by_length=words_by_length,
                min_post_ac3_domain=1,
                forced_assignments=assigned,
            )
            if report.feasible:
                return assigned

    return None
