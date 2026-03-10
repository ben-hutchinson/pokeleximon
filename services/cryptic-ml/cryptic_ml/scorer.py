from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from cryptic_ml.models import ClueCandidate, LexiconEntry, ScoreComponent, ScoreResult, ValidationResult

DEFAULT_MECHANISM_WEIGHTS = {
    "charade": 9.0,
    "anagram": 8.0,
    "deletion": 7.0,
    "container": 6.0,
    "hidden": 5.0,
}

WORD_RE = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class ScoringConfig:
    base_score: float = 50.0
    validity_bonus: float = 18.0
    validity_fail_penalty: float = 40.0
    warning_penalty: float = 3.0
    error_penalty: float = 12.0
    mechanism_weights: dict[str, float] | None = None
    clue_len_min: int = 28
    clue_len_max: int = 72
    clue_len_bonus: float = 6.0
    clue_len_penalty_factor: float = 0.35
    clue_len_penalty_min: float = 1.0
    clue_len_penalty_max: float = 9.0
    lexical_high_threshold: float = 0.72
    lexical_low_threshold: float = 0.55
    lexical_high_bonus: float = 4.0
    lexical_low_penalty: float = 3.0
    charade_multitoken_bonus: float = 5.0
    hidden_penalty: float = 2.0
    indicator_bonus: float = 2.5
    indicator_penalty: float = 2.5
    enum_match_bonus: float = 3.5
    enum_mismatch_penalty: float = 8.0
    score_min: float = 0.0
    score_max: float = 100.0

    def with_defaults(self) -> "ScoringConfig":
        if self.mechanism_weights is not None:
            return self
        return ScoringConfig(
            base_score=self.base_score,
            validity_bonus=self.validity_bonus,
            validity_fail_penalty=self.validity_fail_penalty,
            warning_penalty=self.warning_penalty,
            error_penalty=self.error_penalty,
            mechanism_weights=dict(DEFAULT_MECHANISM_WEIGHTS),
            clue_len_min=self.clue_len_min,
            clue_len_max=self.clue_len_max,
            clue_len_bonus=self.clue_len_bonus,
            clue_len_penalty_factor=self.clue_len_penalty_factor,
            clue_len_penalty_min=self.clue_len_penalty_min,
            clue_len_penalty_max=self.clue_len_penalty_max,
            lexical_high_threshold=self.lexical_high_threshold,
            lexical_low_threshold=self.lexical_low_threshold,
            lexical_high_bonus=self.lexical_high_bonus,
            lexical_low_penalty=self.lexical_low_penalty,
            charade_multitoken_bonus=self.charade_multitoken_bonus,
            hidden_penalty=self.hidden_penalty,
            indicator_bonus=self.indicator_bonus,
            indicator_penalty=self.indicator_penalty,
            enum_match_bonus=self.enum_match_bonus,
            enum_mismatch_penalty=self.enum_mismatch_penalty,
            score_min=self.score_min,
            score_max=self.score_max,
        )


def default_scoring_config() -> ScoringConfig:
    return ScoringConfig(mechanism_weights=dict(DEFAULT_MECHANISM_WEIGHTS))


def load_scoring_config(path: Path | None) -> ScoringConfig:
    config = default_scoring_config()
    if not path:
        return config
    if not path.exists():
        return config

    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        return config

    mechanism_weights = payload.get("mechanism_weights")
    merged_weights = dict(config.mechanism_weights or DEFAULT_MECHANISM_WEIGHTS)
    if isinstance(mechanism_weights, dict):
        for key, value in mechanism_weights.items():
            if isinstance(value, (int, float)):
                merged_weights[str(key)] = float(value)

    int_fields = {"clue_len_min", "clue_len_max"}
    kwargs = {**config.__dict__}
    kwargs["mechanism_weights"] = merged_weights
    for key, value in payload.items():
        if key == "mechanism_weights":
            continue
        if key in kwargs and isinstance(value, (int, float)):
            kwargs[key] = int(value) if key in int_fields else float(value)

    return ScoringConfig(**kwargs).with_defaults()


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def score_candidate(
    candidate: ClueCandidate,
    entry: LexiconEntry,
    validation: ValidationResult,
    config: ScoringConfig | None = None,
) -> ScoreResult:
    cfg = (config or default_scoring_config()).with_defaults()
    components: list[ScoreComponent] = []

    def add(name: str, delta: float, note: str) -> None:
        components.append(ScoreComponent(name=name, delta=delta, note=note))

    add("base", cfg.base_score, "Baseline score before checks")

    add(
        "validity",
        cfg.validity_bonus if validation.is_valid else -cfg.validity_fail_penalty,
        "Validator pass" if validation.is_valid else "Validator hard error",
    )

    warning_count = sum(1 for issue in validation.issues if issue.severity == "warning")
    error_count = sum(1 for issue in validation.issues if issue.severity == "error")
    if warning_count:
        add("warnings", -cfg.warning_penalty * warning_count, f"{warning_count} validator warnings")
    if error_count:
        add("errors", -cfg.error_penalty * error_count, f"{error_count} validator errors")

    mechanism_bonus = (cfg.mechanism_weights or DEFAULT_MECHANISM_WEIGHTS).get(candidate.mechanism, 0.0)
    add("mechanism", mechanism_bonus, f"Mechanism={candidate.mechanism}")

    clue_len = len(candidate.clue)
    if cfg.clue_len_min <= clue_len <= cfg.clue_len_max:
        add("clue_length", cfg.clue_len_bonus, f"Length {clue_len} in target band")
    else:
        distance = cfg.clue_len_min - clue_len if clue_len < cfg.clue_len_min else clue_len - cfg.clue_len_max
        penalty = _clamp(
            distance * cfg.clue_len_penalty_factor,
            cfg.clue_len_penalty_min,
            cfg.clue_len_penalty_max,
        )
        add("clue_length", -penalty, f"Length {clue_len} outside target band")

    words = WORD_RE.findall(candidate.clue.lower())
    unique_ratio = (len(set(words)) / len(words)) if words else 0.0
    if unique_ratio >= cfg.lexical_high_threshold:
        add("lexical_variety", cfg.lexical_high_bonus, f"Unique word ratio {unique_ratio:.2f}")
    elif unique_ratio < cfg.lexical_low_threshold:
        add("lexical_variety", -cfg.lexical_low_penalty, f"Low unique word ratio {unique_ratio:.2f}")

    token_count = len(entry.answer_tokens)
    if candidate.mechanism == "charade" and token_count >= 2:
        add("charade_fit", cfg.charade_multitoken_bonus, "Multi-token answer suits charade")

    if candidate.mechanism == "hidden":
        add("hidden_penalty", -cfg.hidden_penalty, "Hidden clues are easier; slight ranking penalty")

    indicator = candidate.metadata.get("indicator")
    if indicator and indicator.lower() in candidate.clue.lower():
        add("indicator", cfg.indicator_bonus, f"Indicator present: {indicator}")
    elif indicator:
        add("indicator", -cfg.indicator_penalty, f"Indicator missing from surface: {indicator}")

    if candidate.enumeration == entry.enumeration:
        add("enumeration", cfg.enum_match_bonus, "Enumeration matches canonical answer")
    else:
        add("enumeration", -cfg.enum_mismatch_penalty, "Enumeration mismatch")

    score = sum(component.delta for component in components)
    score = round(_clamp(score, cfg.score_min, cfg.score_max), 2)

    return ScoreResult(score=score, components=tuple(components))
