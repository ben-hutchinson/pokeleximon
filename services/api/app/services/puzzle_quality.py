from __future__ import annotations

import math
import re
from typing import Any


NORMALIZE_RE = re.compile(r"[^A-Z0-9]")
DISALLOWED_CLUE_PATTERNS = (
    re.compile(r"(?i)\bpok[eé]api\b"),
    re.compile(r"(?i)\bjapanese\b"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\b(clue|record)\s+token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bfallback clue\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\b(todo|tbd|lorem ipsum)\b"),
    re.compile(r"\*{3,}"),
    re.compile(r"(?i)\bpok[eé]mon term from the csv lexicon\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
    re.compile(r"(?i)^location:\s*region\b"),
    re.compile(r"(?i)\b(type|ability|location) entry\b"),
    re.compile(r"(?i)^core[- ]series pok[eé]mon .*answer uses \d+ word"),
    re.compile(r"(?i)^pok[eé]mon .* clue with initials [A-Z]+ and \d+ total letters"),
    re.compile(r"(?i)^pok[eé]mon .* clue: ending letters"),
    re.compile(r"(?i)^pok[eé]mon .* entry with enumeration"),
    re.compile(r"(?i)\bvowels\s+\d+\s*,\s*consonants\s+\d+\b"),
    re.compile(r"(?i)\b\d+\s+total letters\b"),
    re.compile(r"(?i)\bwith \d+ words? and \d+ letters\b"),
    re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"),
)

MIN_ENTRY_COUNT = 12
MIN_FILL_RATIO = 0.45
MAX_FILL_RATIO = 0.82
MIN_INTERSECTION_RATIO = 0.12
MIN_DIRECTION_BALANCE = 0.30
MIN_UNIQUE_CLUE_RATIO = 0.85
MAX_SHORT_ANSWER_RATIO = 0.50
MIN_WORD_LENGTH_STDDEV = 0.75


def _normalize(value: str) -> str:
    return NORMALIZE_RE.sub("", value.upper())


def _stddev(values: list[int]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _clue_has_disallowed_content(clue: str) -> bool:
    text = str(clue).strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in DISALLOWED_CLUE_PATTERNS)


def evaluate_crossword_publishability(
    *,
    grid: dict[str, Any],
    entries: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    hard_failures: list[str] = []
    warnings: list[str] = []

    total_cells = max(1, len(grid.get("cells", [])))
    open_cells = 0
    for cell in grid.get("cells", []):
        if not bool(cell.get("isBlock", False)):
            open_cells += 1
    fill_ratio = open_cells / total_cells

    entry_count = len(entries)
    across_count = sum(1 for entry in entries if entry.get("direction") == "across")
    down_count = sum(1 for entry in entries if entry.get("direction") == "down")
    direction_balance = (
        min(across_count, down_count) / max(across_count, down_count)
        if max(across_count, down_count) > 0
        else 0.0
    )

    answers = [str(entry.get("answer", "")) for entry in entries]
    clues = [str(entry.get("clue", "")) for entry in entries]
    normalized_answers = [_normalize(answer) for answer in answers if answer]
    normalized_clues = [_normalize(clue) for clue in clues if clue]
    unique_answer_ratio = len(set(normalized_answers)) / max(1, len(normalized_answers))
    unique_clue_ratio = len(set(normalized_clues)) / max(1, len(normalized_clues))

    answer_lengths: list[int] = []
    for entry in entries:
        length = entry.get("length")
        if isinstance(length, int):
            answer_lengths.append(length)
            continue
        answer_lengths.append(len(str(entry.get("answer", ""))))
    short_answer_ratio = sum(1 for length in answer_lengths if length <= 4) / max(1, len(answer_lengths))
    word_length_stddev = _stddev(answer_lengths)

    cell_usage: dict[tuple[int, int], int] = {}
    for entry in entries:
        for coord in entry.get("cells", []):
            if not isinstance(coord, (list, tuple)) or len(coord) != 2:
                continue
            try:
                x = int(coord[0])
                y = int(coord[1])
            except (TypeError, ValueError):
                continue
            key = (x, y)
            cell_usage[key] = cell_usage.get(key, 0) + 1
    intersection_cells = sum(1 for count in cell_usage.values() if count >= 2)
    intersection_ratio = intersection_cells / max(1, open_cells)

    clue_leak_count = 0
    disallowed_clue_count = 0
    for entry in entries:
        answer_norm = _normalize(str(entry.get("answer", "")))
        clue_text = str(entry.get("clue", ""))
        clue_norm = _normalize(clue_text)
        if len(answer_norm) >= 4 and answer_norm and answer_norm in clue_norm:
            clue_leak_count += 1
        if _clue_has_disallowed_content(clue_text):
            disallowed_clue_count += 1

    theme_tags = {str(tag).strip().lower() for tag in metadata.get("themeTags", [])}
    has_pokemon_theme = "pokemon" in theme_tags

    if entry_count < MIN_ENTRY_COUNT:
        hard_failures.append("entry_count_below_minimum")
    if fill_ratio < MIN_FILL_RATIO or fill_ratio > MAX_FILL_RATIO:
        hard_failures.append("fill_ratio_out_of_range")
    if intersection_ratio < MIN_INTERSECTION_RATIO:
        hard_failures.append("intersection_ratio_too_low")
    if direction_balance < MIN_DIRECTION_BALANCE:
        hard_failures.append("direction_balance_too_low")
    if unique_answer_ratio < 1.0:
        hard_failures.append("duplicate_answers_detected")
    if unique_clue_ratio < MIN_UNIQUE_CLUE_RATIO:
        hard_failures.append("duplicate_clues_detected")
    if short_answer_ratio > MAX_SHORT_ANSWER_RATIO:
        hard_failures.append("short_answer_ratio_too_high")
    if word_length_stddev < MIN_WORD_LENGTH_STDDEV:
        hard_failures.append("word_length_balance_too_flat")
    if clue_leak_count > 0:
        hard_failures.append("clue_leaks_answer_text")
    if disallowed_clue_count > 0:
        hard_failures.append("clue_contains_disallowed_content")
    if not has_pokemon_theme:
        if str(metadata.get("source", "")).strip().lower() == "curated":
            hard_failures.append("missing_pokemon_theme_tag")
        else:
            warnings.append("missing_pokemon_theme_tag")

    if metadata.get("source") != "curated":
        warnings.append("metadata_source_not_curated")
    if word_length_stddev > 4.5:
        warnings.append("word_length_spread_high")
    if fill_ratio < 0.52:
        warnings.append("fill_ratio_sparse")
    if fill_ratio > 0.75:
        warnings.append("fill_ratio_dense")

    score = 100.0
    score -= abs(fill_ratio - 0.62) * 120.0
    score -= abs(intersection_ratio - 0.28) * 90.0
    score -= (1.0 - min(1.0, direction_balance)) * 25.0
    score -= (1.0 - min(1.0, unique_clue_ratio)) * 45.0
    score -= max(0.0, short_answer_ratio - 0.35) * 60.0
    score -= clue_leak_count * 20.0
    score -= disallowed_clue_count * 25.0
    score -= len(hard_failures) * 8.0
    score = max(0.0, min(100.0, score))

    return {
        "isPublishable": len(hard_failures) == 0,
        "score": round(score, 2),
        "hardFailures": hard_failures,
        "warnings": warnings,
        "metrics": {
            "entryCount": entry_count,
            "acrossCount": across_count,
            "downCount": down_count,
            "fillRatio": round(fill_ratio, 4),
            "intersectionRatio": round(intersection_ratio, 4),
            "directionBalance": round(direction_balance, 4),
            "uniqueAnswerRatio": round(unique_answer_ratio, 4),
            "uniqueClueRatio": round(unique_clue_ratio, 4),
            "shortAnswerRatio": round(short_answer_ratio, 4),
            "wordLengthStdDev": round(word_length_stddev, 4),
            "clueLeakCount": clue_leak_count,
            "disallowedClueCount": disallowed_clue_count,
            "hasPokemonTheme": has_pokemon_theme,
        },
        "thresholds": {
            "minEntryCount": MIN_ENTRY_COUNT,
            "fillRatioMin": MIN_FILL_RATIO,
            "fillRatioMax": MAX_FILL_RATIO,
            "minIntersectionRatio": MIN_INTERSECTION_RATIO,
            "minDirectionBalance": MIN_DIRECTION_BALANCE,
            "minUniqueClueRatio": MIN_UNIQUE_CLUE_RATIO,
            "maxShortAnswerRatio": MAX_SHORT_ANSWER_RATIO,
            "minWordLengthStdDev": MIN_WORD_LENGTH_STDDEV,
        },
    }
