from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from typing import Any, Callable

FetchJson = Callable[[str], dict[str, Any] | None]

NAME_CLEAN_RE = re.compile(r"[^A-Z0-9]")
SPLIT_RE = re.compile(r"[-_\s]+")
RESOURCE_ID_RE = re.compile(r"/([0-9]+)/?$")

LOCATION_SUFFIXES = {"CITY", "TOWN", "VILLAGE", "AREA"}
SPECIES_HONORIFICS = {"MR", "MRS", "JR", "SR"}

SOURCE_PRIORITY = {
    "pokemon-species": 0,
    "move": 1,
    "item": 2,
    "location": 3,
    "location-area": 4,
    "ability": 5,
    "type": 6,
}

SOURCE_DEFINITIONS = {
    "pokemon-species": "creature",
    "move": "battle technique",
    "item": "held object",
    "location": "regional area",
    "location-area": "regional area",
    "ability": "innate trait",
    "type": "elemental affinity",
}

CRYPTIC_SOURCES = (
    "pokemon-species",
    "move",
    "item",
    "location",
    "location-area",
    "ability",
    "type",
)

ALLOW_HIDDEN_MECHANISM = False
BOILERPLATE_CLUE_PATTERNS = (
    re.compile(r"(?i)\bpok[eé]mon (species|move|item|location|ability|type)\b"),
    re.compile(r"(?i)\bgame term\b"),
    re.compile(r"(?i)\bfallback clue\b"),
    re.compile(r"(?i)\b(clue|record)\s+token\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\b(todo|tbd|lorem ipsum)\b"),
    re.compile(r"\*{3,}"),
)
FORMULAIC_SURFACE_PATTERNS = (
    re.compile(r"(?i)\bletters in [A-Z0-9 ]+ produce\b"),
    re.compile(r"(?i)\bfragments [A-Z0-9\.\+\s]+ (from|via|using)\b"),
    re.compile(r"(?i)\bby (dropping|losing|removing) [A-Z0-9]+ from [A-Z0-9]+\b"),
)
WORD_RE = re.compile(r"[A-Za-z0-9']+")
ENUM_RE = re.compile(r"\([0-9,\-\s]+\)")
UPPER_TOKEN_RE = re.compile(r"\b[A-Z0-9\.]{2,}\b")
LOW_VARIETY_MIN_WORDS = 7
LOW_VARIETY_RATIO_THRESHOLD = 0.62
STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _clean_token(token: str) -> str:
    return NAME_CLEAN_RE.sub("", token.upper())


def _split_slug(slug: str) -> list[str]:
    return [t for t in (_clean_token(tok) for tok in SPLIT_RE.split(slug)) if t]


def _normalize_text(value: str) -> str:
    return NAME_CLEAN_RE.sub("", value.upper())


def _is_noisy(source_type: str, tokens: list[str]) -> bool:
    if not tokens:
        return True

    if source_type == "item" and len(tokens) >= 2 and tokens[0] == "DYNAMAX" and tokens[1] == "CRYSTAL":
        return True

    if source_type == "item" and any(any(ch.isdigit() for ch in t) for t in tokens):
        return True

    if len("".join(tokens)) < 4:
        return True

    return False


def _canonicalize(source_type: str, source_slug: str) -> tuple[list[str], str] | None:
    tokens = _split_slug(source_slug)
    if _is_noisy(source_type, tokens):
        return None

    rule = "identity"

    if source_type in {"location", "location-area"}:
        trimmed = list(tokens)
        while len(trimmed) > 1 and trimmed[-1] in LOCATION_SUFFIXES:
            trimmed.pop()
            rule = "drop_location_suffix"
        tokens = trimmed

    if source_type == "pokemon-species" and len(tokens) > 1 and tokens[0] in SPECIES_HONORIFICS:
        rule = "preserve_species_honorific"

    answer_key = "".join(tokens)
    if not tokens or len(answer_key) < 4 or len(answer_key) > 15:
        return None

    return tokens, rule


def _extract_resource_id(url: str) -> str | None:
    match = RESOURCE_ID_RE.search(url)
    if not match:
        return None
    return match.group(1)


def _list_endpoint(fetch_json: FetchJson, base_url: str, resource: str, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    url = f"{base_url}/{resource}?limit=200"

    while url and len(out) < limit:
        payload = fetch_json(url)
        if payload is None:
            break
        results = payload.get("results", [])
        if not isinstance(results, list):
            break

        for item in results:
            name = item.get("name")
            item_url = item.get("url")
            if not isinstance(name, str) or not isinstance(item_url, str):
                continue
            out.append({"name": name, "url": item_url})
            if len(out) >= limit:
                break

        next_url = payload.get("next")
        url = next_url if isinstance(next_url, str) else ""

    return out


def _score_source(source_type: str, token_count: int, answer_len: int) -> tuple[int, int, int]:
    return (
        SOURCE_PRIORITY.get(source_type, 99),
        token_count,
        answer_len,
    )


def build_cryptic_lexicon(
    fetch_json: FetchJson,
    base_url: str,
    per_source_limit: int = 500,
) -> list[dict[str, Any]]:
    best_by_answer: dict[str, dict[str, Any]] = {}

    for source in CRYPTIC_SOURCES:
        rows = _list_endpoint(fetch_json=fetch_json, base_url=base_url, resource=source, limit=per_source_limit)
        for item in rows:
            source_slug = item["name"]
            source_url = item["url"]
            canonical = _canonicalize(source_type=source, source_slug=source_slug)
            if not canonical:
                continue

            tokens, rule = canonical
            answer_key = "".join(tokens)
            enumeration = ",".join(str(len(t)) for t in tokens)
            source_id = _extract_resource_id(source_url)
            source_ref = f"{source}/{source_id}" if source_id else source_url

            candidate = {
                "answer": " ".join(tokens),
                "answer_key": answer_key,
                "answer_tokens": tokens,
                "enumeration": enumeration,
                "source_type": source,
                "source_ref": source_ref,
                "source_slug": source_slug,
                "normalization_rule": rule,
                "is_multiword": len(tokens) > 1,
            }

            existing = best_by_answer.get(answer_key)
            if not existing:
                best_by_answer[answer_key] = candidate
                continue

            existing_score = _score_source(
                source_type=existing["source_type"],
                token_count=len(existing["answer_tokens"]),
                answer_len=len(existing["answer_key"]),
            )
            candidate_score = _score_source(
                source_type=candidate["source_type"],
                token_count=len(candidate["answer_tokens"]),
                answer_len=len(candidate["answer_key"]),
            )
            if candidate_score < existing_score:
                best_by_answer[answer_key] = candidate

    return sorted(best_by_answer.values(), key=lambda r: (len(r["answer_key"]), r["answer"]))


def dumps_lexicon(entries: list[dict[str, Any]]) -> str:
    return json.dumps(entries)


def loads_lexicon(payload: str) -> list[dict[str, Any]]:
    data = json.loads(payload)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _seed(answer_key: str, mechanism: str) -> int:
    digest = hashlib.sha256(f"{answer_key}:{mechanism}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _pick(values: tuple[str, ...], seed: int, offset: int = 0) -> str:
    return values[(seed + offset) % len(values)]


def _rotate_templates(templates: tuple[tuple[str, str], ...], seed: int) -> tuple[tuple[str, str], ...]:
    if not templates:
        return templates
    shift = seed % len(templates)
    if shift == 0:
        return templates
    return templates[shift:] + templates[:shift]


def _scrambled_letters(answer_key: str, seed: int) -> str:
    letters = list(answer_key)
    rng = random.Random(seed)
    original = "".join(letters)
    for _ in range(8):
        rng.shuffle(letters)
        candidate = "".join(letters)
        if candidate != original:
            return candidate
    return original[1:] + original[:1]


def _deletion_fodder(answer_key: str, seed: int) -> tuple[str, str]:
    if len(answer_key) < 3:
        return answer_key, ""
    remove_index = seed % len(answer_key)
    remove_letter = answer_key[remove_index]
    insert_at = max(1, min(len(answer_key) - 1, len(answer_key) // 2))
    fodder = answer_key[:insert_at] + remove_letter + answer_key[insert_at:]
    return fodder, remove_letter


def _chunk_answer(answer_key: str) -> str:
    if len(answer_key) <= 4:
        return answer_key
    step = 2 if len(answer_key) <= 8 else 3
    return " ".join(answer_key[i : i + step] for i in range(0, len(answer_key), step))


def _mask_component(token: str) -> str:
    cleaned = _normalize_text(token)
    if len(cleaned) <= 1:
        return cleaned
    if len(cleaned) == 2:
        return f"{cleaned[0]}.{cleaned[1]}"
    return f"{cleaned[0]}{'.' * (len(cleaned) - 2)}{cleaned[-1]}"


def _definition(entry: dict[str, Any]) -> str:
    return SOURCE_DEFINITIONS.get(str(entry.get("source_type", "")), "game term")


def _enum(entry: dict[str, Any]) -> str:
    return str(entry.get("enumeration", ""))


def _contains_standalone_answer_token(answer_key: str, clue: str) -> bool:
    if not answer_key or not clue:
        return False
    return bool(re.search(rf"(?i)(?<![A-Z0-9]){re.escape(answer_key)}(?![A-Z0-9])", clue))


def _is_boilerplate_clue(clue: str) -> bool:
    text = str(clue).strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in BOILERPLATE_CLUE_PATTERNS)


def _is_formulaic_surface(clue: str) -> bool:
    text = str(clue).strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in FORMULAIC_SURFACE_PATTERNS)


def _surface_skeleton(clue: str) -> str:
    text = str(clue).lower().strip()
    text = ENUM_RE.sub("(enum)", text)
    text = UPPER_TOKEN_RE.sub("token", text)
    for definition in SOURCE_DEFINITIONS.values():
        text = text.replace(definition.lower(), "definition")
    text = re.sub(r"\s+", " ", text)
    return text


def _surface_quality_warnings(clue: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    text = str(clue).strip()
    if not text:
        return issues

    if _is_formulaic_surface(text):
        issues.append(
            {
                "code": "clue_surface_formulaic",
                "severity": "warning",
                "message": "Clue resembles a repetitive template.",
            }
        )

    words = [w.lower() for w in WORD_RE.findall(text)]
    content_words = [w for w in words if len(w) > 2 and w not in STOPWORDS]
    if len(content_words) >= LOW_VARIETY_MIN_WORDS:
        unique_ratio = len(set(content_words)) / len(content_words)
        if unique_ratio < LOW_VARIETY_RATIO_THRESHOLD:
            issues.append(
                {
                    "code": "clue_surface_low_variety",
                    "severity": "warning",
                    "message": "Clue surface has low lexical variety.",
                }
            )

    if any(words[idx] == words[idx + 1] for idx in range(len(words) - 1)):
        issues.append(
            {
                "code": "clue_surface_repetition",
                "severity": "warning",
                "message": "Clue surface has repeated adjacent words.",
            }
        )
    return issues


def is_ranked_candidate_publishable(row: dict[str, Any]) -> bool:
    if not bool(row.get("validator_passed", False)):
        return False
    clue = str(row.get("clue", "")).strip()
    if not clue:
        return False
    return not _is_boilerplate_clue(clue)


def _candidate_row(
    *,
    mechanism: str,
    clue: str,
    base_score: float,
    wordplay_plan: str,
    metadata: dict[str, Any],
    surface_variant: str,
) -> dict[str, Any]:
    return {
        "mechanism": mechanism,
        "clue": clue,
        "base_score": base_score,
        "wordplay_plan": wordplay_plan,
        "metadata": {
            **metadata,
            "surface_variant": surface_variant,
        },
    }


def _candidate_charade(entry: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = list(entry.get("answer_tokens", []))
    if len(tokens) < 2:
        return []
    seed = _seed(str(entry.get("answer_key", "")), "charade")
    indicator = _pick(("from", "via", "using", "after"), seed)
    definition = _definition(entry)
    def_lead = definition[:1].upper() + definition[1:]
    masked_components = [_mask_component(token) for token in tokens]
    enum = _enum(entry)
    component_text = " + ".join(masked_components)
    def_text = definition.lower()

    templates = (
        ("charade_join", f"Join {component_text} {indicator} for {def_text} ({enum})"),
        ("charade_parts", f"{def_lead} from parts {component_text} ({enum})"),
        ("charade_build", f"Build {def_text} using {component_text} ({enum})"),
        ("charade_formed", f"{def_text.capitalize()} formed by {indicator} joining {component_text} ({enum})"),
        ("charade_assembled", f"Assembled {component_text} gives {def_text} ({enum})"),
    )
    templates = _rotate_templates(templates, seed)
    metadata = {"indicator": indicator, "components": "|".join(tokens), "masked_components": masked_components}
    return [
        _candidate_row(
            mechanism="charade",
            clue=clue,
            base_score=9.0 - (idx * 0.15),
            wordplay_plan=f"charade components: {' + '.join(tokens)}",
            metadata=metadata,
            surface_variant=variant,
        )
        for idx, (variant, clue) in enumerate(templates)
    ]


def _candidate_anagram(entry: dict[str, Any]) -> list[dict[str, Any]]:
    answer_key = str(entry.get("answer_key", ""))
    if len(answer_key) < 6 or len(answer_key) > 12:
        return []
    seed = _seed(answer_key, "anagram")
    indicator = _pick(("mixed", "scrambled", "reordered", "shuffled"), seed)
    fodder = _scrambled_letters(answer_key, seed)
    definition = _definition(entry)
    def_lead = definition[:1].upper() + definition[1:]
    enum = _enum(entry)
    def_text = definition.lower()

    templates = (
        ("anagram_when", f"{def_lead} when {fodder} is {indicator} ({enum})"),
        ("anagram_from", f"{def_lead} from {fodder} {indicator} ({enum})"),
        ("anagram_work", f"Work {fodder} {indicator} for {def_text} ({enum})"),
        ("anagram_yields", f"{fodder} {indicator} yields {def_text} ({enum})"),
        ("anagram_after", f"{def_text.capitalize()} after {fodder} gets {indicator} ({enum})"),
    )
    templates = _rotate_templates(templates, seed)
    metadata = {"indicator": indicator, "fodder": fodder}
    return [
        _candidate_row(
            mechanism="anagram",
            clue=clue,
            base_score=8.0 - (idx * 0.1),
            wordplay_plan=f"anagram fodder: {fodder}",
            metadata=metadata,
            surface_variant=variant,
        )
        for idx, (variant, clue) in enumerate(templates)
    ]


def _candidate_hidden(entry: dict[str, Any]) -> list[dict[str, Any]]:
    if not ALLOW_HIDDEN_MECHANISM:
        return []
    answer_key = str(entry.get("answer_key", ""))
    if len(answer_key) < 4 or len(answer_key) > 10:
        return []
    seed = _seed(answer_key, "hidden")
    indicator = _pick(("inside", "hidden in", "concealed in", "found in"), seed)
    surface_prefix = _pick(("brief", "odd", "rapid", "casual", "strange"), seed)
    surface = f"{surface_prefix} {_chunk_answer(answer_key)} line"
    definition = _definition(entry)
    def_lead = definition[:1].upper() + definition[1:]
    enum = _enum(entry)
    def_text = definition.lower()

    templates = (
        ("hidden_found", f"{def_lead} found {indicator} {surface} ({enum})"),
        ("hidden_gives", f"{indicator.capitalize()} {surface} gives {def_text} ({enum})"),
        ("hidden_sits", f"In {surface} sits {def_text} ({enum})"),
        ("hidden_conceals", f"{surface.capitalize()} conceals {def_text} ({enum})"),
        ("hidden_located", f"{def_lead} located {indicator} {surface} ({enum})"),
    )
    templates = _rotate_templates(templates, seed)
    metadata = {"indicator": indicator, "surface": surface}
    return [
        _candidate_row(
            mechanism="hidden",
            clue=clue,
            base_score=5.0 - (idx * 0.1),
            wordplay_plan=f"hidden sequence in: {surface}",
            metadata=metadata,
            surface_variant=variant,
        )
        for idx, (variant, clue) in enumerate(templates)
    ]


def _candidate_deletion(entry: dict[str, Any]) -> list[dict[str, Any]]:
    answer_key = str(entry.get("answer_key", ""))
    if len(answer_key) < 6:
        return []
    seed = _seed(answer_key, "deletion")
    indicator = _pick(("dropping", "losing", "removing", "taking out"), seed)
    fodder, remove = _deletion_fodder(answer_key, seed)
    if not remove:
        return []

    definition = _definition(entry)
    def_lead = definition[:1].upper() + definition[1:]
    enum = _enum(entry)
    def_text = definition.lower()
    templates = (
        ("deletion_take", f"Take {remove} from {fodder} for {def_text} ({enum})"),
        ("deletion_after", f"{def_lead} after {indicator} {remove} from {fodder} ({enum})"),
        ("deletion_with_removed", f"{fodder} with {remove} {indicator} gives {def_text} ({enum})"),
        ("deletion_becomes", f"If {remove} is {indicator} from {fodder}, you get {def_text} ({enum})"),
        ("deletion_reveals", f"{indicator.capitalize()} {remove} in {fodder} yields {def_text} ({enum})"),
    )
    templates = _rotate_templates(templates, seed)
    metadata = {"indicator": indicator, "fodder": fodder, "remove": remove}
    return [
        _candidate_row(
            mechanism="deletion",
            clue=clue,
            base_score=7.0 - (idx * 0.1),
            wordplay_plan=f"delete '{remove}' from {fodder}",
            metadata=metadata,
            surface_variant=variant,
        )
        for idx, (variant, clue) in enumerate(templates)
    ]


def _deletion_derives_answer(fodder: str, remove: str, answer_key: str) -> bool:
    if not remove:
        return False
    remaining = Counter(fodder)
    removed = Counter(remove)
    for char, count in removed.items():
        if remaining[char] < count:
            return False
        remaining[char] -= count
    rebuilt = Counter({char: count for char, count in remaining.items() if count > 0})
    return rebuilt == Counter(answer_key)


def _validate_candidate(entry: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    mechanism = str(candidate.get("mechanism", ""))
    clue = str(candidate.get("clue", ""))
    metadata = candidate.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    if _is_boilerplate_clue(clue):
        issues.append(
            {
                "code": "clue_surface_disallowed",
                "severity": "error",
                "message": "Clue contains placeholder or boilerplate surface text.",
            }
        )
    if len(clue.strip()) < 18:
        issues.append(
            {
                "code": "clue_too_short",
                "severity": "error",
                "message": "Clue surface is too short to be publishable.",
            }
        )
    issues.extend(_surface_quality_warnings(clue))

    expected_enum = _enum(entry)
    if f"({expected_enum})" not in clue:
        issues.append({"code": "enum_missing", "severity": "error", "message": "Clue missing enumeration"})

    answer_key = str(entry.get("answer_key", ""))
    if answer_key and _contains_standalone_answer_token(answer_key, clue):
        issues.append(
            {
                "code": "answer_leak_standalone",
                "severity": "error",
                "message": "Clue contains answer as a standalone token",
            }
        )
    normalized_clue = _normalize_text(clue)
    if mechanism != "hidden" and answer_key and answer_key in normalized_clue:
        issues.append({"code": "answer_leak", "severity": "error", "message": "Clue contains full answer"})

    indicator = str(metadata.get("indicator", "")).lower()
    if indicator and indicator not in clue.lower():
        issues.append(
            {
                "code": "indicator_missing",
                "severity": "warning",
                "message": f"Indicator '{indicator}' missing in clue surface",
            }
        )

    if mechanism == "charade":
        components_raw = str(metadata.get("components", ""))
        if len([c for c in components_raw.split("|") if c]) < 2:
            issues.append(
                {
                    "code": "charade_components",
                    "severity": "error",
                    "message": "Charade candidate missing components",
                }
            )
        if "." not in clue:
            issues.append(
                {
                    "code": "charade_surface_generic",
                    "severity": "error",
                    "message": "Charade clue lacks component hints",
                }
            )

    if mechanism == "anagram":
        fodder = _normalize_text(str(metadata.get("fodder", "")))
        if not fodder:
            issues.append(
                {
                    "code": "anagram_fodder",
                    "severity": "error",
                    "message": "Anagram candidate missing fodder",
                }
            )
        elif Counter(fodder) != Counter(answer_key):
            issues.append(
                {
                    "code": "anagram_invalid",
                    "severity": "error",
                    "message": "Anagram fodder does not map to answer",
                }
            )

    if mechanism == "hidden":
        surface = _normalize_text(str(metadata.get("surface", "")))
        if not surface:
            issues.append(
                {
                    "code": "hidden_surface",
                    "severity": "error",
                    "message": "Hidden candidate missing surface",
                }
            )
        elif answer_key not in surface:
            issues.append(
                {
                    "code": "hidden_invalid",
                    "severity": "error",
                    "message": "Hidden surface does not contain answer",
                }
            )

    if mechanism == "deletion":
        fodder = _normalize_text(str(metadata.get("fodder", "")))
        remove = _normalize_text(str(metadata.get("remove", "")))
        if not fodder or not remove:
            issues.append(
                {
                    "code": "deletion_metadata",
                    "severity": "error",
                    "message": "Deletion candidate missing fodder/remove metadata",
                }
            )
        elif not _deletion_derives_answer(fodder=fodder, remove=remove, answer_key=answer_key):
            issues.append(
                {
                    "code": "deletion_invalid",
                    "severity": "error",
                    "message": "Deletion fodder/remove cannot derive answer",
                }
            )

    hard_errors = [issue for issue in issues if issue["severity"] == "error"]
    return (len(hard_errors) == 0), issues


def _score_config_value(config: dict[str, Any] | None, key: str, default: float) -> float:
    if not config:
        return default
    value = config.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _mechanism_score(config: dict[str, Any] | None, mechanism: str, default: float) -> float:
    if not config:
        return default
    scores = config.get("mechanism_base_scores")
    if not isinstance(scores, dict):
        return default
    value = scores.get(mechanism)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def build_ranked_candidates(entry: dict[str, Any], scoring_config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw_lists = (
        _candidate_charade(entry),
        _candidate_anagram(entry),
        _candidate_deletion(entry),
        _candidate_hidden(entry),
    )
    candidates: list[dict[str, Any]] = []
    seen_normalized_clues: set[str] = set()
    for rows in raw_lists:
        for row in rows:
            clue_key = _normalize_text(str(row.get("clue", "")))
            if not clue_key or clue_key in seen_normalized_clues:
                continue
            seen_normalized_clues.add(clue_key)
            candidates.append(row)

    if not candidates:
        return []

    evaluated: list[dict[str, Any]] = []
    skeleton_counts: dict[str, int] = {}
    for row in candidates:
        passed, issues = _validate_candidate(entry, row)
        warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
        error_count = sum(1 for issue in issues if issue["severity"] == "error")
        formulaic_count = sum(1 for issue in issues if issue.get("code") == "clue_surface_formulaic")
        low_variety_count = sum(1 for issue in issues if issue.get("code") == "clue_surface_low_variety")
        mechanism = str(row.get("mechanism", "fallback"))
        rank_score = _mechanism_score(scoring_config, mechanism, float(row.get("base_score", 0.0)))
        rank_score += _score_config_value(scoring_config, "validity_bonus", 12.0) if passed else -_score_config_value(
            scoring_config, "invalid_penalty", 35.0
        )
        rank_score -= warning_count * _score_config_value(scoring_config, "warning_penalty", 3.0)
        rank_score -= error_count * _score_config_value(scoring_config, "error_penalty", 12.0)
        rank_score -= formulaic_count * _score_config_value(scoring_config, "formulaic_warning_penalty", 4.0)
        rank_score -= low_variety_count * _score_config_value(scoring_config, "low_variety_penalty", 2.5)
        if row.get("mechanism") == "hidden":
            rank_score -= _score_config_value(scoring_config, "hidden_penalty", 2.0)
        if row.get("mechanism") == "charade":
            rank_score -= _score_config_value(scoring_config, "charade_penalty", 4.0)

        skeleton = _surface_skeleton(str(row.get("clue", "")))
        repeat_count = skeleton_counts.get(skeleton, 0)
        if repeat_count > 0:
            issues.append(
                {
                    "code": "surface_pattern_repetition",
                    "severity": "warning",
                    "message": "Candidate repeats an already-seen clue surface structure.",
                }
            )
            rank_score -= repeat_count * _score_config_value(scoring_config, "surface_repeat_penalty", 2.0)
        skeleton_counts[skeleton] = repeat_count + 1

        out = dict(row)
        out["validator_passed"] = passed
        out["validator_issues"] = issues
        out["rank_score"] = round(rank_score, 2)
        out["score"] = out["rank_score"]
        evaluated.append(out)

    evaluated.sort(
        key=lambda c: (
            bool(c.get("validator_passed", False)),
            float(c.get("rank_score", 0.0)),
            -len(c.get("validator_issues", [])),
        ),
        reverse=True,
    )
    for idx, item in enumerate(evaluated, start=1):
        item["rank_position"] = idx
    return evaluated


def select_ranked_candidate(ranked_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in ranked_candidates:
        if is_ranked_candidate_publishable(row):
            return row
    return None


def select_best_clue(entry: dict[str, Any]) -> dict[str, Any]:
    ranked = build_ranked_candidates(entry)
    selected = select_ranked_candidate(ranked)
    if selected is not None:
        return selected
    if not ranked:
        return {
            "mechanism": "fallback",
            "clue": "",
            "score": 0.0,
            "rank_score": 0.0,
            "validator_passed": False,
            "validator_issues": [
                {
                    "code": "no_candidates",
                    "severity": "error",
                    "message": "No candidates generated",
                }
            ],
        }
    return ranked[0]
