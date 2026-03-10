from __future__ import annotations

import re
from collections import Counter

from cryptic_ml.models import ClueCandidate, LexiconEntry, ValidationIssue, ValidationResult


def _parse_enumeration(enum_text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for raw in enum_text.split(","):
        raw = raw.strip()
        if not raw.isdigit():
            return ()
        parts.append(int(raw))
    return tuple(parts)


def _normalize_text(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _contains_phrase(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _deletion_can_make_answer(fodder: str, remove: str, answer: str) -> bool:
    if not remove:
        return False

    fodder_counter = Counter(fodder)
    remove_counter = Counter(remove)

    for char, count in remove_counter.items():
        if fodder_counter[char] < count:
            return False
        fodder_counter[char] -= count

    rebuilt = []
    for char, count in fodder_counter.items():
        rebuilt.extend(char for _ in range(count))

    return Counter("".join(rebuilt)) == Counter(answer)


def validate_candidate(candidate: ClueCandidate, entry: LexiconEntry) -> ValidationResult:
    issues: list[ValidationIssue] = []

    actual_enum = tuple(len(t) for t in entry.answer_tokens)
    candidate_enum = _parse_enumeration(candidate.enumeration)
    if candidate_enum != actual_enum:
        issues.append(
            ValidationIssue(
                code="enum_mismatch",
                message=f"Enumeration mismatch: expected {actual_enum}, got {candidate.enumeration}",
            )
        )

    if len(candidate.clue.strip()) < 18:
        issues.append(
            ValidationIssue(
                code="clue_too_short",
                message="Clue surface is very short; likely low quality.",
                severity="warning",
            )
        )

    indicator = candidate.metadata.get("indicator")
    if indicator and not _contains_phrase(candidate.clue, indicator):
        issues.append(
            ValidationIssue(
                code="indicator_missing",
                message=f"Expected indicator '{indicator}' is not present in clue surface.",
                severity="warning",
            )
        )

    def_pos = candidate.metadata.get("definitionPosition", "start")
    clue_lower = candidate.clue.lower().strip()
    def_lower = candidate.definition.lower().strip()

    if def_pos == "start" and not clue_lower.startswith(def_lower):
        issues.append(
            ValidationIssue(
                code="definition_position",
                message="Definition is not at the start as planned.",
                severity="warning",
            )
        )
    if def_pos == "end" and not clue_lower.endswith(def_lower):
        issues.append(
            ValidationIssue(
                code="definition_position",
                message="Definition is not at the end as planned.",
                severity="warning",
            )
        )

    normalized_clue = _normalize_text(candidate.clue)
    answer_leak = entry.answer_key in normalized_clue

    if candidate.mechanism != "hidden" and answer_leak:
        issues.append(
            ValidationIssue(
                code="answer_leak",
                message="Clue surface contains the full answer for a non-hidden clue.",
            )
        )

    if candidate.mechanism == "charade":
        components_raw = candidate.metadata.get("components", "")
        components = [c for c in components_raw.split("|") if c]
        if len(entry.answer_tokens) < 2 or len(components) < 2:
            issues.append(
                ValidationIssue(
                    code="mechanism_invalid",
                    message="Charade requires at least 2 components.",
                )
            )

    if candidate.mechanism == "anagram":
        fodder = _normalize_text(candidate.metadata.get("fodder", ""))
        if not fodder:
            issues.append(
                ValidationIssue(
                    code="anagram_missing_fodder",
                    message="Anagram clue missing fodder metadata.",
                )
            )
        elif Counter(fodder) != Counter(entry.answer_key):
            issues.append(
                ValidationIssue(
                    code="anagram_invalid",
                    message="Anagram fodder letters do not match answer letters.",
                )
            )

    if candidate.mechanism == "hidden":
        surface = candidate.metadata.get("surface", "")
        normalized_surface = _normalize_text(surface)
        if not surface:
            issues.append(
                ValidationIssue(
                    code="hidden_missing_surface",
                    message="Hidden clue missing source surface metadata.",
                )
            )
        elif entry.answer_key not in normalized_surface:
            issues.append(
                ValidationIssue(
                    code="hidden_invalid",
                    message="Hidden clue surface does not contain answer sequence.",
                )
            )

    if candidate.mechanism == "deletion":
        fodder = _normalize_text(candidate.metadata.get("fodder", ""))
        remove = _normalize_text(candidate.metadata.get("remove", ""))
        if not fodder or not remove:
            issues.append(
                ValidationIssue(
                    code="deletion_missing_metadata",
                    message="Deletion clue missing fodder/remove metadata.",
                )
            )
        elif not _deletion_can_make_answer(fodder=fodder, remove=remove, answer=entry.answer_key):
            issues.append(
                ValidationIssue(
                    code="deletion_invalid",
                    message="Deletion metadata cannot derive the answer.",
                )
            )

    hard_errors = [issue for issue in issues if issue.severity == "error"]
    return ValidationResult(is_valid=not hard_errors, issues=tuple(issues))
