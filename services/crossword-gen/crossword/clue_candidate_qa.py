from __future__ import annotations

from difflib import SequenceMatcher
import re
from typing import Any


TOKEN_RE = re.compile(r"[^A-Z0-9]")
WHITESPACE_RE = re.compile(r"\s+")

GENERIC_ANSWER_FRAGMENTS = {
    "ABILITY",
    "ITEM",
    "MOVE",
    "TYPE",
    "ROUTE",
    "CITY",
    "TOWN",
    "CAVE",
    "GATE",
    "BAY",
    "ROAD",
    "PATH",
    "FOREST",
    "DESERT",
    "MOUNTAIN",
    "MEADOW",
    "LAKE",
    "RUINS",
    "HILL",
    "FIELD",
    "TEMPLE",
    "TOWER",
    "MINE",
    "VILLA",
    "CAFE",
    "BALL",
    "PARK",
    "ORE",
    "MAIL",
    "BERRY",
    "CANDY",
    "STONE",
}

GENERIC_PATTERNS = (
    re.compile(r"(?i)\bbattle move\b"),
    re.compile(r"(?i)\bbattle ability\b"),
    re.compile(r"(?i)\bbattle element\b"),
    re.compile(r"(?i)\bgame item\b"),
    re.compile(r"(?i)\bcore-series species\b"),
    re.compile(r"(?i)\bcore-games item\b"),
    re.compile(r"(?i)\binventory item\b"),
    re.compile(r"(?i)\bgen\s+[ivx]+\s+(species|move|ability|item|location|type)\b"),
    re.compile(r"(?i)\bincluding added effects and where to find it\b"),
    re.compile(r"(?i)\band the list of pok[eé]mon that learn it\b"),
    re.compile(r"(?i)^details and added effects for the pok[eé]mon attack\.?$"),
    re.compile(r"(?i)\bintroduced in generation\s+\d+\b"),
)

BAD_PATTERNS = (
    re.compile(r"(?i)\bpokeapi\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\btodo\b"),
    re.compile(r"\*{2,}"),
    re.compile(r"(?i)^this (?:pok[eé]mon|item|move|ability|type|location)\b"),
    re.compile(r"(?i)^details and added effects for the pok[eé]mon attack\.?$"),
    re.compile(r"(?i)^this pok[eé]mon is an? [a-z0-9 /-]+ type pok[eé]mon introduced in generation \d+\.?$"),
)

TYPE_TOKENS = {
    "BUG",
    "DARK",
    "DRAGON",
    "ELECTRIC",
    "FAIRY",
    "FIGHTING",
    "FIRE",
    "FLYING",
    "GHOST",
    "GRASS",
    "GROUND",
    "ICE",
    "NORMAL",
    "POISON",
    "PSYCHIC",
    "ROCK",
    "STEEL",
    "WATER",
}

REGION_TOKENS = {
    "KANTO",
    "JOHTO",
    "HOENN",
    "SINNOH",
    "UNOVA",
    "KALOS",
    "ALOLA",
    "GALAR",
    "PALDEA",
    "HISUI",
    "KITAKAMI",
}


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "").strip())


def normalize_token_text(value: str) -> str:
    return TOKEN_RE.sub("", str(value or "").upper())


def word_count(value: str) -> int:
    return len([part for part in normalize_text(value).split(" ") if part])


def answer_fragments(answer_display: str) -> list[str]:
    parts = [part for part in str(answer_display or "").upper().replace("-", " ").split() if part]
    fragments: set[str] = set()
    for part in parts:
        if len(part) >= 2:
            fragments.add(part)
    for joined in ("".join(parts), " ".join(parts), "-".join(parts)):
        compact = joined.replace(" ", "").replace("-", "")
        if len(compact) >= 2:
            fragments.add(joined)
    return sorted(fragments, key=len, reverse=True)


def contains_answer_fragment(text: str, answer_display: str) -> bool:
    for fragment in answer_fragments(answer_display):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(str(text or "")):
            return True
    return False


def answer_fragment_flags(text: str, answer_display: str) -> tuple[bool, bool]:
    hits: list[str] = []
    for fragment in answer_fragments(answer_display):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(str(text or "")):
            hits.append(fragment.upper())
    if not hits:
        return False, False
    generic_only = all(hit in GENERIC_ANSWER_FRAGMENTS for hit in hits)
    return True, generic_only


def evidence_refs(evidence: dict[str, Any] | None) -> set[str]:
    refs = {"lead"}
    if not isinstance(evidence, dict):
        return refs
    for row in evidence.get("sections", []):
        if not isinstance(row, dict):
            continue
        title = normalize_text(str(row.get("title") or ""))
        if title:
            refs.add(title.lower())
    return refs


def _evidence_texts(evidence: dict[str, Any] | None) -> list[str]:
    texts: list[str] = []
    if not isinstance(evidence, dict):
        return texts
    lead = normalize_text(str(evidence.get("leadText") or ""))
    if lead:
        texts.append(lead)
    for row in evidence.get("sections", []):
        if not isinstance(row, dict):
            continue
        text = normalize_text(str(row.get("text") or ""))
        if text:
            texts.append(text)
    return texts


def near_verbatim_match(text: str, evidence: dict[str, Any] | None) -> bool:
    clue = normalize_text(text).lower()
    if not clue:
        return False
    if clue in {normalize_text(item).lower() for item in _evidence_texts(evidence)}:
        return True
    clue_words = [part for part in clue.split(" ") if part]
    if len(clue_words) < 4:
        return False
    shingles = {" ".join(clue_words[idx : idx + 4]) for idx in range(len(clue_words) - 3)}
    if not shingles:
        return False
    for evidence_text in _evidence_texts(evidence):
        lowered = evidence_text.lower()
        hit_count = sum(1 for shingle in shingles if shingle in lowered)
        if hit_count >= max(1, len(shingles) - 1):
            return True
    return False


def score_candidate(
    *,
    text: str,
    answer_display: str,
    evidence: dict[str, Any] | None,
    evidence_ref: str | None,
    style: str,
    agent_confidence: float,
    mystery_score: float,
    specificity_score: float,
) -> tuple[float, list[str], bool]:
    flags: list[str] = []
    score = 100.0
    normalized = normalize_text(text)
    if not normalized:
        return 0.0, ["empty_clue"], False
    if any(pattern.search(normalized) for pattern in BAD_PATTERNS):
        flags.append("disallowed_pattern")
        score -= 100.0
    has_fragment, generic_only_fragment = answer_fragment_flags(normalized, answer_display)
    if has_fragment:
        flags.append("answer_fragment_leak")
        score -= 18.0 if generic_only_fragment else 80.0
    if near_verbatim_match(normalized, evidence):
        flags.append("near_verbatim_source")
        score -= 55.0
    if any(pattern.search(normalized) for pattern in GENERIC_PATTERNS):
        flags.append("generic_surface")
        score -= 20.0

    words = word_count(normalized)
    if words < 2:
        flags.append("too_short")
        score -= 18.0
    elif words > 8:
        flags.append("long_form")
        score -= (words - 8) * 5.0
    if words > 14:
        flags.append("too_long")
        score -= 50.0

    if evidence_ref:
        refs = evidence_refs(evidence)
        if evidence_ref.lower() not in refs:
            flags.append("unknown_evidence_ref")
            score -= 10.0
    else:
        flags.append("missing_evidence_ref")
        score -= 10.0

    style_penalty = {
        "manual_override": 0.0,
        "agent_curated": 0.0,
        "agent_curated_fallback": 6.0,
        "signature": 4.0,
        "semantic": 6.0,
        "taxonomy": 8.0,
        "descriptor": 10.0,
        "fallback": 14.0,
    }.get(style, 10.0)
    score -= style_penalty

    score += max(0.0, min(1.0, agent_confidence)) * 8.0
    score += max(0.0, min(1.0, mystery_score)) * 10.0
    score += max(0.0, min(1.0, specificity_score)) * 8.0

    approved = True
    hard_flags = {"disallowed_pattern", "near_verbatim_source", "too_long"}
    if "answer_fragment_leak" in flags and not generic_only_fragment:
        hard_flags.add("answer_fragment_leak")
    for hard_flag in hard_flags:
        if hard_flag in flags:
            approved = False
            break
    return round(max(score, 0.0), 2), sorted(set(flags)), approved


def infer_difficulty(text: str, mystery_score: float, specificity_score: float) -> str:
    words = word_count(text)
    lowered = normalize_text(text).lower()
    direct_markers = ("pokemon", "type", "move", "ability", "item", "region", "evolves from")
    if words <= 4 and (mystery_score < 0.45 or any(marker in lowered for marker in direct_markers)):
        return "easy"
    if mystery_score >= 0.72 or specificity_score >= 0.8:
        return "hard"
    return "medium"


def pairwise_similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left).lower()
    right_norm = normalize_text(right).lower()
    if not left_norm or not right_norm:
        return 0.0
    ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split(" "))
    right_tokens = set(right_norm.split(" "))
    jaccard = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return round(max(ratio, jaccard), 3)


def detect_canon_claims(text: str) -> dict[str, str]:
    lowered = normalize_text(text).lower()
    claims: dict[str, str] = {}

    generation_match = re.search(r"\bgen(?:eration)?\s*([ivx]+)\b", lowered)
    if generation_match:
        claims["generation"] = generation_match.group(1).upper()

    for token in TYPE_TOKENS:
        if re.search(rf"\b{token.lower()}\b", lowered):
            claims["type"] = token
            break

    for token in REGION_TOKENS:
        if re.search(rf"\b{token.lower()}\b", lowered):
            claims["region"] = token
            break

    evolves_match = re.search(r"\bevolves from\s+([a-z][a-z' -]+)", lowered)
    if evolves_match:
        claims["evolves_from"] = normalize_token_text(evolves_match.group(1))

    return claims


def validate_answer_fit(answer_display: str, text: str) -> tuple[float, list[str]]:
    flags: list[str] = []
    normalized_answer = normalize_text(answer_display).upper()
    normalized_text = normalize_text(text).lower()

    plural_markers = ("many ", "several ", "group of ", "pair of ")
    if any(marker in normalized_text for marker in plural_markers) and not normalized_answer.endswith("S"):
        flags.append("grammar_answer_mismatch")

    if normalized_text.startswith("abbr") and len(normalize_token_text(normalized_answer)) > 5:
        flags.append("answer_fit_mismatch")

    score = 1.0
    if "grammar_answer_mismatch" in flags:
        score -= 0.4
    if "answer_fit_mismatch" in flags:
        score -= 0.3
    return round(max(score, 0.0), 3), flags
