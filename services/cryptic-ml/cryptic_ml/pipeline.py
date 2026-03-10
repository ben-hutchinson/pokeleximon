from __future__ import annotations

from dataclasses import dataclass

from cryptic_ml.models import ClueCandidate, CluePlan, LexiconEntry, ScoreResult, ValidationResult
from cryptic_ml.planner import build_plans_for_entry, realize_candidate
from cryptic_ml.scorer import ScoringConfig, score_candidate
from cryptic_ml.validator import validate_candidate


@dataclass(frozen=True)
class CandidateEvaluation:
    plan: CluePlan
    candidate: ClueCandidate
    validation: ValidationResult
    score: ScoreResult


def evaluate_entry(entry: LexiconEntry, scoring_config: ScoringConfig | None = None) -> list[CandidateEvaluation]:
    evaluations: list[CandidateEvaluation] = []

    for plan in build_plans_for_entry(entry):
        candidate = realize_candidate(plan)
        validation = validate_candidate(candidate, entry)
        score = score_candidate(candidate, entry, validation, config=scoring_config)
        evaluations.append(
            CandidateEvaluation(
                plan=plan,
                candidate=candidate,
                validation=validation,
                score=score,
            )
        )

    evaluations.sort(
        key=lambda item: (
            item.validation.is_valid,
            item.score.score,
            -len(item.validation.issues),
        ),
        reverse=True,
    )
    return evaluations
