from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import random
import time

from crossword.cp_sat_solver import solve_with_cp_sat
from crossword.grid import Grid, Entry


@dataclass
class SolverConfig:
    max_steps: int = 200000
    allow_reuse: bool = False
    max_candidates: int | None = None
    weighted_shuffle: bool = False
    max_seconds: float | None = None
    use_lcv: bool = True
    debug: bool = False
    beam_width: int = 0
    beam_depth: int = 0
    use_min_conflicts: bool = True
    min_conflicts_steps: int = 16000
    min_conflicts_restarts: int = 10
    min_conflicts_sample: int = 240
    use_cp_sat: bool = False
    cp_sat_first: bool = True
    cp_sat_max_seconds: float = 2.0
    cp_sat_max_domain_per_entry: int = 1200
    cp_sat_workers: int = 8


class Solver:
    def __init__(
        self,
        grid: Grid,
        entries: list[Entry],
        words: list[str],
        config: SolverConfig | None = None,
        word_scores: dict[str, float] | None = None,
        initial_assignments: dict[str, str] | None = None,
    ):
        self.grid = grid
        self.entries = entries
        self.config = config or SolverConfig()
        self.word_scores = word_scores or {}
        self.initial_assignments = initial_assignments or {}
        self.start_time = time.monotonic()
        self.steps = 0
        self.max_depth = 0
        self.candidate_checks = 0
        self.used: set[str] = set()
        self.cp_sat_attempted = False
        self.cp_sat_status: str | None = None
        self.cp_sat_wall_seconds = 0.0

        self.by_length: dict[int, list[str]] = {}
        for word in words:
            self.by_length.setdefault(len(word), []).append(word)
        for length, bucket in self.by_length.items():
            bucket.sort(key=lambda w: self.word_scores.get(w, 0.0), reverse=True)

        self.entry_ids = [entry.id for entry in entries]
        self.entry_by_id = {entry.id: entry for entry in entries}
        self.entry_cell_index: dict[str, dict[tuple[int, int], int]] = {}
        self.cell_entries: dict[tuple[int, int], list[str]] = {}
        self.neighbors: dict[str, set[str]] = {entry.id: set() for entry in entries}
        self.overlaps: dict[str, dict[str, list[tuple[int, int]]]] = {
            entry.id: {} for entry in entries
        }

        for entry in entries:
            cell_index: dict[tuple[int, int], int] = {}
            for idx, cell in enumerate(entry.cells):
                cell_index[cell] = idx
                self.cell_entries.setdefault(cell, []).append(entry.id)
            self.entry_cell_index[entry.id] = cell_index

        for cell, entry_ids in self.cell_entries.items():
            if len(entry_ids) > 1:
                for eid in entry_ids:
                    for oid in entry_ids:
                        if eid == oid:
                            continue
                        self.neighbors[eid].add(oid)
                        pos_e = self.entry_cell_index[eid][cell]
                        pos_o = self.entry_cell_index[oid][cell]
                        self.overlaps[eid].setdefault(oid, []).append((pos_e, pos_o))

    def solve(self) -> bool:
        self._reset_grid()
        domains: dict[str, list[str]] = {
            entry.id: list(self.by_length.get(entry.length, [])) for entry in self.entries
        }
        assignments: dict[str, str] = {}

        if not self._apply_initial_assignments(domains, assignments):
            return False

        if not self._ac3(domains):
            return False
        ok, added_entries, added_used = self._sync_singletons(domains, assignments)
        if not ok:
            self._rollback_assignments(assignments, added_entries, added_used)
            return False

        if self.config.use_cp_sat and self.config.cp_sat_first:
            solved = self._try_cp_sat()
            if solved:
                return True

        solved = self._backtrack(domains, assignments, depth=0)
        if solved:
            final_assignments = {
                entry_id: domains[entry_id][0] for entry_id in domains.keys()
            }
            for entry_id, word in final_assignments.items():
                entry = self.entry_by_id[entry_id]
                self.grid.place_word(entry.cells, word)
            return True

        if self.config.use_cp_sat and not self.config.cp_sat_first:
            solved = self._try_cp_sat()
            if solved:
                return True

        if self.config.use_min_conflicts:
            mc_assignments = self._min_conflicts_search()
            if mc_assignments:
                for entry_id, word in mc_assignments.items():
                    entry = self.entry_by_id[entry_id]
                    self.grid.place_word(entry.cells, word)
                return True

        return False

    def _try_cp_sat(self) -> bool:
        self.cp_sat_attempted = True
        cp_sat_seconds = self.config.cp_sat_max_seconds
        if self.config.max_seconds is not None:
            remaining = self.config.max_seconds - (time.monotonic() - self.start_time)
            cp_sat_seconds = min(cp_sat_seconds, max(0.0, remaining))

        cp_sat_result = solve_with_cp_sat(
            entries=self.entries,
            by_length=self.by_length,
            overlaps=self.overlaps,
            initial_assignments=self.initial_assignments,
            allow_reuse=self.config.allow_reuse,
            max_seconds=cp_sat_seconds,
            max_domain_per_entry=self.config.cp_sat_max_domain_per_entry,
            workers=self.config.cp_sat_workers,
        )
        self.cp_sat_status = cp_sat_result.status
        self.cp_sat_wall_seconds = cp_sat_result.wall_seconds
        if cp_sat_result.assignments:
            for entry_id, word in cp_sat_result.assignments.items():
                entry = self.entry_by_id[entry_id]
                self.grid.place_word(entry.cells, word)
            return True
        return False

    def _reset_grid(self) -> None:
        for key in self.grid.cells.keys():
            self.grid.cells[key] = None

    def _backtrack(
        self,
        domains: dict[str, list[str]],
        assignments: dict[str, str],
        depth: int,
    ) -> bool:
        if self.config.max_seconds is not None:
            if time.monotonic() - self.start_time > self.config.max_seconds:
                return False
        if self.steps > self.config.max_steps:
            return False
        self.steps += 1
        if depth > self.max_depth:
            self.max_depth = depth

        entry_id = self._select_unassigned(domains, assignments)
        if entry_id is None:
            return True

        domain = domains[entry_id]
        if not domain:
            return False

        ordered = self._order_domain(entry_id, domain, domains)
        if self.config.beam_width > 0 and depth < self.config.beam_depth:
            ordered = self._beam_filter_candidates(entry_id, ordered, domains, assignments)
        for word in ordered:
            self.candidate_checks += 1
            if not self.config.allow_reuse and word in self.used:
                continue
            if not self._consistent(entry_id, word, assignments):
                continue

            changes: dict[str, list[str]] = {}
            if domains[entry_id] != [word]:
                changes[entry_id] = domains[entry_id]
                domains[entry_id] = [word]

            added_entries, added_used = self._add_assignment(assignments, entry_id, word)
            if added_entries is None:
                self._restore_domains(domains, changes)
                continue

            ok = self._ac3(domains, queue=deque((n, entry_id) for n in self.neighbors[entry_id]), changes=changes)
            if ok:
                ok, forced_entries, forced_used = self._sync_singletons(domains, assignments)
            else:
                forced_entries, forced_used = [], []

            if ok and self._backtrack(domains, assignments, depth=depth + 1):
                return True

            self._restore_domains(domains, changes)
            self._rollback_assignments(assignments, forced_entries, forced_used)
            self._rollback_assignments(assignments, added_entries, added_used)

        return False

    def _beam_filter_candidates(
        self,
        entry_id: str,
        ordered: list[str],
        domains: dict[str, list[str]],
        assignments: dict[str, str],
    ) -> list[str]:
        scored: list[tuple[tuple[float, float, float, float], str]] = []
        for word in ordered:
            if not self.config.allow_reuse and word in self.used:
                continue
            if not self._consistent(entry_id, word, assignments):
                continue

            changes: dict[str, list[str]] = {}
            if domains[entry_id] != [word]:
                changes[entry_id] = domains[entry_id]
                domains[entry_id] = [word]

            added_entries, added_used = self._add_assignment(assignments, entry_id, word)
            if added_entries is None:
                self._restore_domains(domains, changes)
                continue

            ok = self._ac3(
                domains,
                queue=deque((neighbor, entry_id) for neighbor in self.neighbors[entry_id]),
                changes=changes,
            )
            if ok:
                ok, forced_entries, forced_used = self._sync_singletons(domains, assignments)
            else:
                forced_entries, forced_used = [], []

            if ok:
                score = self._branch_score(domains, assignments)
                scored.append((score, word))

            self._restore_domains(domains, changes)
            self._rollback_assignments(assignments, forced_entries, forced_used)
            self._rollback_assignments(assignments, added_entries, added_used)

        if not scored:
            return []

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[: self.config.beam_width]
        return [word for _, word in top]

    def _branch_score(
        self,
        domains: dict[str, list[str]],
        assignments: dict[str, str],
    ) -> tuple[float, float, float, float]:
        remaining = [
            len(domains[entry.id]) for entry in self.entries if entry.id not in assignments
        ]
        if not remaining:
            return (1_000_000.0, 1_000_000.0, 0.0, 0.0)
        min_domain = min(remaining)
        singleton_count = sum(1 for size in remaining if size == 1)
        avg_domain = sum(remaining) / len(remaining)
        assigned_count = len(assignments)
        return (
            float(assigned_count),
            float(min_domain),
            -float(singleton_count),
            float(avg_domain),
        )

    def _apply_initial_assignments(
        self, domains: dict[str, list[str]], assignments: dict[str, str]
    ) -> bool:
        for entry_id, word in self.initial_assignments.items():
            if entry_id not in domains:
                return False
            if word not in domains[entry_id]:
                return False
            if not self.config.allow_reuse and word in self.used:
                return False
            if not self._consistent(entry_id, word, assignments):
                return False
            domains[entry_id] = [word]
            assignments[entry_id] = word
            if not self.config.allow_reuse:
                self.used.add(word)
        return True

    def _select_unassigned(
        self, domains: dict[str, list[str]], assignments: dict[str, str]
    ) -> str | None:
        best_entry = None
        best_len = None
        for entry in self.entries:
            if entry.id in assignments:
                continue
            domain = domains[entry.id]
            if not self.config.allow_reuse:
                domain = [w for w in domain if w not in self.used]
            length = len(domain)
            if best_len is None or length < best_len:
                best_entry = entry.id
                best_len = length
            elif length == best_len and best_entry is not None:
                if len(self.neighbors[entry.id]) > len(self.neighbors[best_entry]):
                    best_entry = entry.id
        return best_entry

    def _order_domain(self, entry_id: str, domain: list[str], domains: dict[str, list[str]]) -> list[str]:
        if not domain:
            return []

        ordered = list(domain)
        if self.config.use_lcv:
            neighbor_letters: dict[str, dict[int, dict[str, int]]] = {}
            for neighbor_id, pairs in self.overlaps[entry_id].items():
                counts: dict[int, dict[str, int]] = {}
                for _, pos_n in pairs:
                    if pos_n in counts:
                        continue
                    bucket: dict[str, int] = {}
                    for w in domains[neighbor_id]:
                        letter = w[pos_n]
                        bucket[letter] = bucket.get(letter, 0) + 1
                    counts[pos_n] = bucket
                neighbor_letters[neighbor_id] = counts

            def lcv_score(word: str) -> float:
                score = 0.0
                for neighbor_id, pairs in self.overlaps[entry_id].items():
                    counts = neighbor_letters.get(neighbor_id, {})
                    for pos_e, pos_n in pairs:
                        score += counts.get(pos_n, {}).get(word[pos_e], 0)
                score += self.word_scores.get(word, 0.0) * 0.05
                return score

            ordered.sort(key=lcv_score, reverse=True)

        if self.config.weighted_shuffle:
            scored = [(self.word_scores.get(w, 1.0), w) for w in ordered]
            ordered = self._weighted_shuffle(scored)

        if self.config.max_candidates is not None:
            ordered = ordered[: self.config.max_candidates]
        return ordered

    def _weighted_shuffle(self, scored: list[tuple[float, str]]) -> list[str]:
        shuffled: list[tuple[float, str, float]] = []
        for score, word in scored:
            weight = max(score, 0.0001)
            r = random.random()
            key = r ** (1.0 / weight)
            shuffled.append((score, word, key))
        shuffled.sort(key=lambda x: x[2], reverse=True)
        return [word for _, word, _ in shuffled]

    def _consistent(self, entry_id: str, word: str, assignments: dict[str, str]) -> bool:
        for neighbor_id, pairs in self.overlaps[entry_id].items():
            if neighbor_id not in assignments:
                continue
            neighbor_word = assignments[neighbor_id]
            for pos_e, pos_n in pairs:
                if word[pos_e] != neighbor_word[pos_n]:
                    return False
        return True

    def _ac3(
        self,
        domains: dict[str, list[str]],
        queue: deque[tuple[str, str]] | None = None,
        changes: dict[str, list[str]] | None = None,
    ) -> bool:
        if queue is None:
            queue = deque(
                (entry_id, neighbor_id)
                for entry_id in self.entry_ids
                for neighbor_id in self.neighbors[entry_id]
            )

        while queue:
            xi, xj = queue.popleft()
            if self._revise(domains, xi, xj, changes):
                if not domains[xi]:
                    if self.config.debug:
                        self._debug_ac3_empty(domains, xi, xj)
                    return False
                for xk in self.neighbors[xi]:
                    if xk != xj:
                        queue.append((xk, xi))
        return True

    def _revise(
        self,
        domains: dict[str, list[str]],
        xi: str,
        xj: str,
        changes: dict[str, list[str]] | None,
    ) -> bool:
        overlaps = self.overlaps.get(xi, {}).get(xj)
        if not overlaps:
            return False

        allowed: dict[int, set[str]] = {}
        for _, pos_j in overlaps:
            if pos_j in allowed:
                continue
            letters = {word[pos_j] for word in domains[xj]}
            allowed[pos_j] = letters

        new_domain: list[str] = []
        revised = False
        for word in domains[xi]:
            valid = True
            for pos_i, pos_j in overlaps:
                if word[pos_i] not in allowed[pos_j]:
                    valid = False
                    break
            if valid:
                new_domain.append(word)
            else:
                revised = True

        if revised:
            if changes is not None and xi not in changes:
                changes[xi] = domains[xi]
            domains[xi] = new_domain
            if self.config.debug and not new_domain:
                self._debug_ac3_empty(domains, xi, xj)
        return revised

    def _sync_singletons(
        self, domains: dict[str, list[str]], assignments: dict[str, str]
    ) -> tuple[bool, list[str], list[str]]:
        added_entries: list[str] = []
        added_used: list[str] = []
        for entry_id, domain in domains.items():
            if len(domain) != 1:
                continue
            word = domain[0]
            if entry_id in assignments:
                if assignments[entry_id] != word:
                    return False, added_entries, added_used
                continue
            entries, used = self._add_assignment(assignments, entry_id, word)
            if entries is None:
                return False, added_entries, added_used
            added_entries.extend(entries)
            added_used.extend(used)
        return True, added_entries, added_used

    def _add_assignment(
        self, assignments: dict[str, str], entry_id: str, word: str
    ) -> tuple[list[str] | None, list[str]]:
        if entry_id in assignments:
            if assignments[entry_id] != word:
                return None, []
            return [], []
        if not self._consistent(entry_id, word, assignments):
            return None, []
        if not self.config.allow_reuse and word in self.used:
            return None, []
        assignments[entry_id] = word
        added_entries = [entry_id]
        added_used: list[str] = []
        if not self.config.allow_reuse:
            self.used.add(word)
            added_used.append(word)
        return added_entries, added_used

    def _restore_domains(self, domains: dict[str, list[str]], changes: dict[str, list[str]]) -> None:
        for entry_id, previous in changes.items():
            domains[entry_id] = previous

    def _rollback_assignments(
        self, assignments: dict[str, str], added_entries: list[str], added_used: list[str]
    ) -> None:
        for entry_id in added_entries:
            assignments.pop(entry_id, None)
        for word in added_used:
            self.used.discard(word)

    def _debug_ac3_empty(self, domains: dict[str, list[str]], xi: str, xj: str) -> None:
        overlaps = self.overlaps.get(xi, {}).get(xj, [])
        overlap_str = ",".join(f"{a}->{b}" for a, b in overlaps)
        xi_len = len(domains.get(xi, []))
        xj_len = len(domains.get(xj, []))
        print(
            f"[AC3] domain empty: xi={xi} xj={xj} overlaps={overlap_str} "
            f"xi_len={xi_len} xj_len={xj_len}",
            flush=True,
        )

    def _min_conflicts_search(self) -> dict[str, str] | None:
        domains: dict[str, list[str]] = {
            entry.id: list(self.by_length.get(entry.length, [])) for entry in self.entries
        }
        if any(not domain for domain in domains.values()):
            return None

        seed_assignments = self._build_min_conflicts_initial_assignments(domains)
        if seed_assignments is None:
            return None

        best_assignment = seed_assignments
        best_conflicts = self._total_conflicts(seed_assignments)
        if best_conflicts == 0:
            return seed_assignments

        for _ in range(self.config.min_conflicts_restarts):
            assignments = dict(seed_assignments)
            if _ > 0:
                self._random_perturb(assignments, domains, fraction=0.25)
            for _ in range(self.config.min_conflicts_steps):
                if self.config.max_seconds is not None:
                    if time.monotonic() - self.start_time > self.config.max_seconds:
                        return None
                conflicted = [eid for eid in self.entry_ids if self._entry_conflicts(eid, assignments) > 0]
                if not conflicted:
                    return assignments

                entry_id = random.choice(conflicted)
                current = assignments[entry_id]
                candidate = self._pick_min_conflicts_candidate(entry_id, assignments, domains)
                if candidate is not None:
                    assignments[entry_id] = candidate
                else:
                    assignments[entry_id] = current

                total_conflicts = self._total_conflicts(assignments)
                if total_conflicts < best_conflicts:
                    best_conflicts = total_conflicts
                    best_assignment = dict(assignments)
                    if best_conflicts == 0:
                        return best_assignment

        return best_assignment if best_conflicts == 0 else None

    def _build_min_conflicts_initial_assignments(
        self,
        domains: dict[str, list[str]],
    ) -> dict[str, str] | None:
        assignments: dict[str, str] = {}
        for entry_id in self.entry_ids:
            domain = domains[entry_id]
            if not domain:
                return None
            pick = self._pick_weighted_word(domain)
            if pick is None:
                return None
            assignments[entry_id] = pick
        return assignments

    def _pick_weighted_word(self, domain: list[str]) -> str | None:
        if not domain:
            return None
        if len(domain) == 1:
            return domain[0]
        weights = [max(self.word_scores.get(word, 1.0), 0.01) for word in domain]
        total = sum(weights)
        target = random.random() * total
        running = 0.0
        for word, weight in zip(domain, weights):
            running += weight
            if running >= target:
                return word
        return domain[-1]

    def _random_perturb(
        self,
        assignments: dict[str, str],
        domains: dict[str, list[str]],
        fraction: float,
    ) -> None:
        if fraction <= 0:
            return
        count = max(1, int(len(assignments) * fraction))
        picks = random.sample(self.entry_ids, min(count, len(self.entry_ids)))
        for entry_id in picks:
            domain = domains[entry_id]
            if not domain:
                continue
            assignments[entry_id] = self._pick_weighted_word(domain) or assignments[entry_id]

    def _pick_min_conflicts_candidate(
        self,
        entry_id: str,
        assignments: dict[str, str],
        domains: dict[str, list[str]],
    ) -> str | None:
        domain = domains.get(entry_id, [])
        if not domain:
            return None
        if len(domain) > self.config.min_conflicts_sample:
            candidates = random.sample(domain, self.config.min_conflicts_sample)
        else:
            candidates = domain

        best_words: list[str] = []
        best_score: tuple[int, float] | None = None
        for word in candidates:
            score = (
                self._entry_conflicts(entry_id, assignments, candidate=word),
                -self.word_scores.get(word, 0.0),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_words = [word]
            elif score == best_score:
                best_words.append(word)

        if not best_words:
            return None
        return random.choice(best_words)

    def _entry_conflicts(
        self,
        entry_id: str,
        assignments: dict[str, str],
        candidate: str | None = None,
    ) -> int:
        word = candidate if candidate is not None else assignments[entry_id]
        conflicts = 0
        for neighbor_id, pairs in self.overlaps.get(entry_id, {}).items():
            neighbor_word = assignments.get(neighbor_id)
            if neighbor_word is None:
                continue
            for pos_e, pos_n in pairs:
                if word[pos_e] != neighbor_word[pos_n]:
                    conflicts += 1
        return conflicts

    def _total_conflicts(self, assignments: dict[str, str]) -> int:
        total = 0
        for entry_id in self.entry_ids:
            total += self._entry_conflicts(entry_id, assignments)
        return total // 2
