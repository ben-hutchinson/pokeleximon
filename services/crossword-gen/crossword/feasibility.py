from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from crossword.grid import Entry


@dataclass(frozen=True)
class FeasibilityReport:
    feasible: bool
    reason: str | None
    domain_sizes: dict[str, int]


def build_words_by_length(words: list[str], min_len: int, max_len: int) -> dict[int, list[str]]:
    by_length: dict[int, list[str]] = {}
    for word in words:
        length = len(word)
        if length < min_len or length > max_len:
            continue
        by_length.setdefault(length, []).append(word)
    return by_length


def _build_overlap_graph(
    entries: list[Entry],
) -> tuple[dict[str, set[str]], dict[str, dict[str, list[tuple[int, int]]]]]:
    entry_cell_index: dict[str, dict[tuple[int, int], int]] = {}
    cell_entries: dict[tuple[int, int], list[str]] = {}
    neighbors: dict[str, set[str]] = {entry.id: set() for entry in entries}
    overlaps: dict[str, dict[str, list[tuple[int, int]]]] = {entry.id: {} for entry in entries}

    for entry in entries:
        index_map: dict[tuple[int, int], int] = {}
        for idx, cell in enumerate(entry.cells):
            index_map[cell] = idx
            cell_entries.setdefault(cell, []).append(entry.id)
        entry_cell_index[entry.id] = index_map

    for cell, entry_ids in cell_entries.items():
        if len(entry_ids) < 2:
            continue
        for entry_id in entry_ids:
            for other_id in entry_ids:
                if entry_id == other_id:
                    continue
                neighbors[entry_id].add(other_id)
                pos_a = entry_cell_index[entry_id][cell]
                pos_b = entry_cell_index[other_id][cell]
                overlaps[entry_id].setdefault(other_id, []).append((pos_a, pos_b))
    return neighbors, overlaps


def _revise(
    domains: dict[str, list[str]],
    xi: str,
    xj: str,
    overlaps: dict[str, dict[str, list[tuple[int, int]]]],
) -> bool:
    pairs = overlaps.get(xi, {}).get(xj)
    if not pairs:
        return False

    allowed_by_pos: dict[int, set[str]] = {}
    for _, pos_j in pairs:
        if pos_j in allowed_by_pos:
            continue
        allowed_by_pos[pos_j] = {word[pos_j] for word in domains[xj]}

    new_domain: list[str] = []
    revised = False
    for word in domains[xi]:
        valid = True
        for pos_i, pos_j in pairs:
            if word[pos_i] not in allowed_by_pos[pos_j]:
                valid = False
                break
        if valid:
            new_domain.append(word)
        else:
            revised = True

    if revised:
        domains[xi] = new_domain
    return revised


def _ac3(
    domains: dict[str, list[str]],
    neighbors: dict[str, set[str]],
    overlaps: dict[str, dict[str, list[tuple[int, int]]]],
) -> bool:
    queue: deque[tuple[str, str]] = deque(
        (entry_id, other_id) for entry_id, ns in neighbors.items() for other_id in ns
    )
    while queue:
        xi, xj = queue.popleft()
        if _revise(domains, xi, xj, overlaps):
            if not domains[xi]:
                return False
            for xk in neighbors[xi]:
                if xk != xj:
                    queue.append((xk, xi))
    return True


def evaluate_template_feasibility(
    entries: list[Entry],
    words_by_length: dict[int, list[str]],
    min_post_ac3_domain: int = 1,
    forced_assignments: dict[str, str] | None = None,
) -> FeasibilityReport:
    domains: dict[str, list[str]] = {
        entry.id: list(words_by_length.get(entry.length, [])) for entry in entries
    }
    if forced_assignments:
        for entry_id, word in forced_assignments.items():
            domain = domains.get(entry_id)
            if domain is None:
                return FeasibilityReport(
                    feasible=False,
                    reason=f"invalid-forced-entry:{entry_id}",
                    domain_sizes={k: len(v) for k, v in domains.items()},
                )
            if word not in domain:
                return FeasibilityReport(
                    feasible=False,
                    reason=f"invalid-forced-word:{entry_id}",
                    domain_sizes={k: len(v) for k, v in domains.items()},
                )
            domains[entry_id] = [word]

    empty = [entry_id for entry_id, domain in domains.items() if not domain]
    if empty:
        return FeasibilityReport(
            feasible=False,
            reason=f"empty-initial-domain:{empty[0]}",
            domain_sizes={k: len(v) for k, v in domains.items()},
        )

    neighbors, overlaps = _build_overlap_graph(entries)
    if not _ac3(domains, neighbors, overlaps):
        zero = [entry_id for entry_id, domain in domains.items() if not domain]
        reason = f"ac3-empty-domain:{zero[0]}" if zero else "ac3-infeasible"
        return FeasibilityReport(
            feasible=False,
            reason=reason,
            domain_sizes={k: len(v) for k, v in domains.items()},
        )

    if min_post_ac3_domain > 1:
        fragile = [
            entry_id for entry_id, domain in domains.items() if len(domain) < min_post_ac3_domain
        ]
        if fragile:
            return FeasibilityReport(
                feasible=False,
                reason=f"fragile-domain:{fragile[0]}<{min_post_ac3_domain}",
                domain_sizes={k: len(v) for k, v in domains.items()},
            )

    return FeasibilityReport(
        feasible=True,
        reason=None,
        domain_sizes={k: len(v) for k, v in domains.items()},
    )
