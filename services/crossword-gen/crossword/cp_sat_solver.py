from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crossword.grid import Entry


@dataclass(frozen=True)
class CpSatResult:
    assignments: dict[str, str] | None
    status: str
    wall_seconds: float


def cp_sat_available() -> bool:
    try:
        from ortools.sat.python import cp_model  # noqa: F401
    except Exception:
        return False
    return True


def solve_with_cp_sat(
    *,
    entries: list["Entry"],
    by_length: dict[int, list[str]],
    overlaps: dict[str, dict[str, list[tuple[int, int]]]],
    initial_assignments: dict[str, str],
    allow_reuse: bool,
    max_seconds: float,
    max_domain_per_entry: int,
    workers: int,
) -> CpSatResult:
    try:
        from ortools.sat.python import cp_model
    except Exception:
        return CpSatResult(assignments=None, status="cp_sat_unavailable", wall_seconds=0.0)

    if max_seconds <= 0:
        return CpSatResult(assignments=None, status="cp_sat_timeout_budget", wall_seconds=0.0)

    domains: dict[str, list[str]] = {}
    for entry in entries:
        words = list(by_length.get(entry.length, []))
        if not words:
            return CpSatResult(assignments=None, status=f"cp_sat_empty_domain:{entry.id}", wall_seconds=0.0)
        domains[entry.id] = words[:max_domain_per_entry]

    model = cp_model.CpModel()

    entry_vars: dict[str, "cp_model.IntVar"] = {}
    letter_vars: dict[str, list["cp_model.IntVar"]] = {}

    for entry in entries:
        entry_id = entry.id
        domain = domains[entry_id]
        word_var = model.NewIntVar(0, len(domain) - 1, f"word_{entry_id}")
        entry_vars[entry_id] = word_var

        letters: list["cp_model.IntVar"] = []
        for pos in range(entry.length):
            letter_var = model.NewIntVar(0, 25, f"letter_{entry_id}_{pos}")
            allowed = [(idx, ord(word[pos]) - 65) for idx, word in enumerate(domain)]
            model.AddAllowedAssignments([word_var, letter_var], allowed)
            letters.append(letter_var)
        letter_vars[entry_id] = letters

    for entry in entries:
        entry_id = entry.id
        for neighbor_id, pairs in overlaps.get(entry_id, {}).items():
            if neighbor_id <= entry_id:
                continue
            for pos_entry, pos_neighbor in pairs:
                model.Add(letter_vars[entry_id][pos_entry] == letter_vars[neighbor_id][pos_neighbor])

    for entry_id, word in initial_assignments.items():
        domain = domains.get(entry_id)
        word_var = entry_vars.get(entry_id)
        if domain is None or word_var is None:
            return CpSatResult(assignments=None, status=f"cp_sat_bad_seed:{entry_id}", wall_seconds=0.0)
        if word not in domain:
            return CpSatResult(assignments=None, status=f"cp_sat_seed_not_in_domain:{entry_id}", wall_seconds=0.0)
        model.Add(word_var == domain.index(word))

    if not allow_reuse:
        by_length_ids: dict[int, list[str]] = {}
        for entry in entries:
            by_length_ids.setdefault(entry.length, []).append(entry.id)
        for entry_ids in by_length_ids.values():
            if len(entry_ids) < 2:
                continue
            for i, left_id in enumerate(entry_ids):
                for right_id in entry_ids[i + 1 :]:
                    model.Add(entry_vars[left_id] != entry_vars[right_id])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = max(1, workers)

    status = solver.Solve(model)
    wall = float(solver.WallTime())

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if status == cp_model.INFEASIBLE:
            return CpSatResult(assignments=None, status="cp_sat_infeasible", wall_seconds=wall)
        if status == cp_model.MODEL_INVALID:
            return CpSatResult(assignments=None, status="cp_sat_model_invalid", wall_seconds=wall)
        return CpSatResult(assignments=None, status="cp_sat_no_solution", wall_seconds=wall)

    solved: dict[str, str] = {}
    for entry in entries:
        domain = domains[entry.id]
        idx = int(solver.Value(entry_vars[entry.id]))
        solved[entry.id] = domain[idx]
    return CpSatResult(assignments=solved, status="cp_sat_solved", wall_seconds=wall)
