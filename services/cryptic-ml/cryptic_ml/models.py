from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Mechanism = Literal["charade", "anagram", "hidden", "deletion", "container"]


@dataclass(frozen=True)
class LexiconEntry:
    answer: str
    answer_key: str
    enumeration: str
    answer_tokens: tuple[str, ...]
    source_type: str
    source_ref: str
    source_slug: str
    normalization_rule: str
    is_multiword: bool
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CluePlan:
    answer_key: str
    answer: str
    enumeration: str
    definition: str
    mechanism: Mechanism
    wordplay: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ClueCandidate:
    answer_key: str
    clue: str
    enumeration: str
    mechanism: Mechanism
    definition: str
    plan_wordplay: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    issues: tuple[ValidationIssue, ...] = ()


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    delta: float
    note: str


@dataclass(frozen=True)
class ScoreResult:
    score: float
    components: tuple[ScoreComponent, ...] = ()
