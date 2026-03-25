from __future__ import annotations

import re
from typing import Any

from crossword.clue_candidate_qa import (
    detect_canon_claims,
    infer_difficulty,
    pairwise_similarity,
    validate_answer_fit,
    word_count,
)


PROVIDER_PRIORITY = {
    "bulbapedia": 0,
    "serebii": 1,
    "pokemondb": 2,
}

SEVERE_FLAGS = {
    "near_verbatim_source",
    "disallowed_pattern",
    "canon_conflict",
    "boilerplate_surface",
    "taxonomy_dump",
}

BOILERPLATE_PATTERNS = (
    re.compile(r"(?i)^this (?:pok[eé]mon|item|move|ability|type|location)\b"),
    re.compile(r"(?i)\bincluding added effects and where to find it\b"),
    re.compile(r"(?i)\band the list of pok[eé]mon that learn it\b"),
    re.compile(r"(?i)^details and added effects for the pok[eé]mon attack\.?$"),
)

TAXONOMY_DUMP_PATTERNS = (
    re.compile(r"(?i)\bintroduced in generation\s+\d+\b"),
    re.compile(r"(?i)\b[a-z]+(?:\s*/\s*[a-z]+)?\s+type pok[eé]mon\b"),
)


def score_checklist_dimensions(
    *,
    answer_row: dict[str, Any],
    provider_candidate: dict[str, Any],
    peer_candidates: list[dict[str, Any]],
) -> tuple[dict[str, float], list[str], str]:
    clue = str(provider_candidate.get("clue") or "")
    flags = list(provider_candidate.get("qualityFlags") or [])
    approved = bool(provider_candidate.get("approved", False))
    lowered = clue.lower()
    words = word_count(clue)
    base_specificity = 0.9 if 2 <= words <= 6 else 0.7 if words <= 8 else 0.45
    difficulty = infer_difficulty(clue, 0.55, base_specificity)
    answer_fit_score, answer_fit_flags = validate_answer_fit(str(answer_row.get("answerDisplay") or ""), clue)
    flags.extend(answer_fit_flags)

    claims = detect_canon_claims(clue)
    unique_providers = {
        str(row.get("provider") or "").strip().lower()
        for row in peer_candidates
        if isinstance(row, dict) and str(row.get("provider") or "").strip()
    }
    peer_claims = [detect_canon_claims(str(row.get("clue") or "")) for row in peer_candidates if row is not provider_candidate]
    if len(unique_providers) > 1:
        for claim_key, claim_value in claims.items():
            peer_values = {row.get(claim_key) for row in peer_claims if row.get(claim_key)}
            if peer_values and any(value != claim_value for value in peer_values):
                flags.append("canon_conflict")
            elif claim_value and not peer_values:
                flags.append("single_source_claim")

    if any(pattern.search(clue) for pattern in BOILERPLATE_PATTERNS):
        flags.append("boilerplate_surface")
    taxonomy_hits = sum(1 for pattern in TAXONOMY_DUMP_PATTERNS if pattern.search(clue))
    if taxonomy_hits >= 2 or ("introduced in generation" in lowered and "type pokémon" in lowered):
        flags.append("taxonomy_dump")
    if lowered.startswith("it "):
        flags.append("weak_opening")
    if sum(1 for char in clue if char.isdigit()) >= 3:
        flags.append("numeric_surface")

    accuracy = 1.0 if approved and not any(flag in flags for flag in {"answer_fragment_leak", "near_verbatim_source"}) else 0.45
    fairness = 0.92 if approved else 0.6
    if words < 2 or words > 8:
        fairness -= 0.2
        flags.append("underspecified" if words < 2 else "overly_obscure")

    clarity = 1.0
    if words > 7:
        clarity -= 0.15
    if any(char in clue for char in ";:()"):
        clarity -= 0.1
        flags.append("ambiguous_surface")
    if "weak_opening" in flags:
        clarity -= 0.15
    if "boilerplate_surface" in flags:
        clarity -= 0.35
    if "taxonomy_dump" in flags:
        clarity -= 0.2

    thematic = 1.0 if str(provider_candidate.get("provider") or "") in PROVIDER_PRIORITY and clue else 0.0
    creativity = 0.55
    if difficulty in {"medium", "hard"}:
        creativity += 0.2
    if approved:
        creativity += 0.15
    if "generic_surface" in flags:
        creativity -= 0.2
    if "numeric_surface" in flags:
        creativity -= 0.15
    if "boilerplate_surface" in flags:
        creativity -= 0.35
    if "taxonomy_dump" in flags:
        creativity -= 0.25

    if "boilerplate_surface" in flags:
        accuracy -= 0.35
        fairness -= 0.35
    if "taxonomy_dump" in flags:
        fairness -= 0.25

    difficulty_calibration = 0.95 if difficulty == "medium" else 0.8 if difficulty == "easy" else 0.85
    canon_scope = 1.0
    if "single_source_claim" in flags:
        canon_scope -= 0.15
    if "canon_conflict" in flags:
        canon_scope -= 0.5

    scores = {
        "accuracy": round(max(accuracy, 0.0), 3),
        "fairness": round(max(fairness, 0.0), 3),
        "clarity": round(max(clarity, 0.0), 3),
        "thematicConsistency": round(max(thematic, 0.0), 3),
        "creativity": round(max(creativity, 0.0), 3),
        "difficultyCalibration": round(max(difficulty_calibration, 0.0), 3),
        "answerFit": round(max(answer_fit_score, 0.0), 3),
        "canonScope": round(max(canon_scope, 0.0), 3),
    }
    return scores, sorted(set(flags)), difficulty


def rank_provider_candidates(
    *,
    answer_row: dict[str, Any],
    provider_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for candidate in provider_candidates:
        if not isinstance(candidate, dict):
            continue
        clue = str(candidate.get("clue") or "")
        if not clue:
            continue
        checklist_scores, flags, difficulty = score_checklist_dimensions(
            answer_row=answer_row,
            provider_candidate=candidate,
            peer_candidates=provider_candidates,
        )
        score = float(candidate.get("score") or 0.0)
        owner_bonus = sum(checklist_scores.values()) * 8.0
        approved_bonus = 6.0 if bool(candidate.get("approved", False)) else 0.0
        owner_penalty = 0.0
        if "boilerplate_surface" in flags:
            owner_penalty += 28.0
        if "taxonomy_dump" in flags:
            owner_penalty += 18.0
        if "numeric_surface" in flags:
            owner_penalty += 8.0
        if "weak_opening" in flags:
            owner_penalty += 4.0
        ranked.append(
            {
                **candidate,
                "productOwnerScore": round(score + owner_bonus + approved_bonus - owner_penalty, 2),
                "checklistScores": checklist_scores,
                "checklistFlags": flags,
                "difficulty": difficulty,
            }
        )

    ranked.sort(
        key=lambda row: (
            -float(row.get("productOwnerScore") or 0.0),
            PROVIDER_PRIORITY.get(str(row.get("provider") or ""), 99),
            str(row.get("clue") or ""),
        )
    )
    return ranked


def select_best_candidates(ranked_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    leftovers: list[dict[str, Any]] = []

    for row in ranked_candidates:
        if len(selected) >= 3:
            leftovers.append(dict(row))
            continue
        clue = str(row.get("clue") or "")
        if not clue:
            continue
        is_duplicate_surface = any(pairwise_similarity(clue, str(existing.get("clue") or "")) >= 0.8 for existing in selected)
        if is_duplicate_surface:
            leftovers.append(dict(row))
            continue
        selected.append(dict(row))

    for row in leftovers:
        if len(selected) >= 3:
            break
        selected.append(dict(row))

    for idx, row in enumerate(selected):
        row["rankPosition"] = idx + 1

    for left_idx in range(len(selected)):
        for right_idx in range(left_idx + 1, len(selected)):
            similarity = pairwise_similarity(str(selected[left_idx].get("clue") or ""), str(selected[right_idx].get("clue") or ""))
            if similarity < 0.8:
                continue
            selected[right_idx]["checklistFlags"] = sorted(
                set(list(selected[right_idx].get("checklistFlags") or []) + ["duplicate_surface", "style_repetition"])
            )
            selected[right_idx]["productOwnerScore"] = round(float(selected[right_idx].get("productOwnerScore") or 0.0) - 10.0, 2)

    for row in selected:
        flags = set(row.get("qualityFlags") or []) | set(row.get("checklistFlags") or [])
        row["qualityFlags"] = sorted(flags)
        row["approved"] = bool(row.get("approved", False)) and not bool(flags & SEVERE_FLAGS)
    return selected


def summarize_review_status(selected_candidates: list[dict[str, Any]]) -> tuple[str, list[str], str]:
    approved_count = sum(1 for row in selected_candidates if bool(row.get("approved", False)))
    entry_flags: list[str] = []
    unique_providers = {
        str(row.get("provider") or "").strip().lower()
        for row in selected_candidates
        if isinstance(row, dict) and str(row.get("provider") or "").strip()
    }
    if approved_count < 3:
        entry_flags.append("needs_more_crossword_clues")
    if any("canon_conflict" in row.get("qualityFlags", []) for row in selected_candidates):
        entry_flags.append("canon_conflict")
    if any("duplicate_surface" in row.get("qualityFlags", []) for row in selected_candidates):
        entry_flags.append("duplicate_surface")
    if len(unique_providers) > 1 and any("single_source_claim" in row.get("qualityFlags", []) for row in selected_candidates):
        entry_flags.append("single_source_claim")

    review_status = "approved" if approved_count >= 3 and not entry_flags else "needs_review"
    rationale = f"selected {len(selected_candidates)} generator clues; {approved_count} approved after checklist review"
    return review_status, sorted(set(entry_flags)), rationale


def evaluate_generator_candidates(
    *,
    answer_row: dict[str, Any],
    provider_candidates: list[dict[str, Any]],
    existing_selected_clues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ranked_candidates = rank_provider_candidates(answer_row=answer_row, provider_candidates=provider_candidates)
    selected_candidates = select_best_candidates(ranked_candidates)
    review_status, entry_flags, rationale = summarize_review_status(selected_candidates)
    checklist_scores: dict[str, float] = {}
    if selected_candidates:
        keys = list(selected_candidates[0].get("checklistScores", {}).keys())
        checklist_scores = {
            key: round(
                sum(float(row.get("checklistScores", {}).get(key, 0.0)) for row in selected_candidates) / len(selected_candidates),
                3,
            )
            for key in keys
        }

    standard_clues: list[dict[str, Any]] = []
    for idx, row in enumerate(selected_candidates, start=1):
        standard_clues.append(
            {
                "text": str(row.get("clue") or ""),
                "style": "agent_curated",
                "provenance": f"provider:{row.get('provider')}",
                "qualityScore": round(float(row.get("productOwnerScore") or 0.0), 2),
                "qualityFlags": sorted(set(row.get("qualityFlags") or [])),
                "approved": bool(row.get("approved", False)),
                "evidenceRef": str(row.get("evidenceRef") or "lead"),
                "source": str(row.get("provider") or ""),
                "provider": str(row.get("provider") or ""),
                "rankPosition": idx,
                "difficulty": str(row.get("difficulty") or "medium"),
                "checklistScores": dict(row.get("checklistScores") or {}),
            }
        )

    return {
        "rankedCandidates": ranked_candidates,
        "selectedCandidates": standard_clues,
        "entryFlags": entry_flags,
        "reviewStatus": review_status,
        "checklistScores": checklist_scores,
        "selectionRationale": rationale,
        "existingSelectedClues": existing_selected_clues or [],
    }
