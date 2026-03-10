from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
OUTPUT_CSV_PATH = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
UNRESOLVED_REPORT_CSV_PATH = ROOT_DIR / "data" / "crossword_clue_unresolved_report.csv"
UNRESOLVED_REPORT_JSON_PATH = ROOT_DIR / "data" / "crossword_clue_unresolved_report.json"
POKEAPI_CACHE_DIR = ROOT_DIR / "services" / "data" / "pokeapi"

SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")

GENERATION_LABELS = {
    "generation-i": "Gen I",
    "generation-ii": "Gen II",
    "generation-iii": "Gen III",
    "generation-iv": "Gen IV",
    "generation-v": "Gen V",
    "generation-vi": "Gen VI",
    "generation-vii": "Gen VII",
    "generation-viii": "Gen VIII",
    "generation-ix": "Gen IX",
}
GENERATION_ORDER = {
    "Gen I": 1,
    "Gen II": 2,
    "Gen III": 3,
    "Gen IV": 4,
    "Gen V": 5,
    "Gen VI": 6,
    "Gen VII": 7,
    "Gen VIII": 8,
    "Gen IX": 9,
}

DISALLOWED_CLUE_PATTERNS = (
    re.compile(r"(?i)\bpok[eé]api\b"),
    re.compile(r"(?i)\bjapanese\b"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\b(clue|record)\s+token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bfallback clue\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\bxxx\b"),
    re.compile(r"(?i)\bnew effect for this (move|item|ability|location|type)\b"),
    re.compile(r"(?i)\b(todo|tbd|lorem ipsum)\b"),
    re.compile(r"\*{3,}"),
    re.compile(r"(?i)\bpok[eé]mon term from the csv lexicon\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
    re.compile(r"(?i)^location:\s*region\b"),
    re.compile(r"(?i)\b(type|ability|location) entry\b"),
    re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"),
)
GENERIC_CLUE_PATTERNS = (
    re.compile(r"(?i)^core[- ]series pok[eé]mon .*answer uses \d+ word"),
    re.compile(r"(?i)^pok[eé]mon .* clue with initials [A-Z]+ and \d+ total letters"),
    re.compile(r"(?i)^pok[eé]mon .* clue: ending letters"),
    re.compile(r"(?i)^pok[eé]mon .* entry with enumeration"),
    re.compile(r"(?i)^answer uses \d+ words? with lengths"),
)
LOW_QUALITY_PATTERNS = (
    re.compile(r"(?i)redirects here"),
    re.compile(r"(?i)this article is about"),
    re.compile(r"(?i)may refer to"),
    re.compile(r"(?i)disambiguation"),
    re.compile(r"(?i)^for the"),
    re.compile(r"(?i)if you were looking for"),
    re.compile(r"(?i)for a list of"),
    re.compile(r"(?i)\bsee this (location|item|pokemon|move|ability|type)\b"),
    re.compile(r"(?i)\bprominent locations found within the pok[eé]mon world\b"),
)


def _parse_source_ref(source_ref: str) -> tuple[str | None, int | None]:
    match = SOURCE_REF_RE.search(source_ref)
    if not match:
        return None, None
    resource = match.group(1)
    try:
        resource_id = int(match.group(2))
    except ValueError:
        return resource, None
    return resource, resource_id


def _english_value(rows: list[dict[str, Any]], key: str = "name") -> str | None:
    for row in rows:
        if row.get("language", {}).get("name") == "en":
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _clean_text(text: str) -> str:
    out = " ".join(text.replace("\n", " ").replace("\f", " ").split())
    out = re.sub(r"(?i)pok[ée]mon", "Pokémon", out)
    out = out.replace("’", "’").replace("'", "’")
    return out.strip()


def _as_sentence(text: str) -> str:
    if not text:
        return ""
    text = _clean_text(text)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _slug_to_words(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").strip()


def _generation_label_from_name(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None
    label = GENERATION_LABELS.get(name.strip().lower())
    if label:
        return label
    cleaned = _slug_to_words(name).title()
    return cleaned or None


def _generation_label(payload: dict[str, Any]) -> str | None:
    generation = payload.get("generation")
    if isinstance(generation, dict):
        return _generation_label_from_name(str(generation.get("name") or ""))
    return None


def _game_generation_labels(payload: dict[str, Any]) -> list[str]:
    labels: set[str] = set()
    game_indices = payload.get("game_indices")
    if not isinstance(game_indices, list):
        return []
    for row in game_indices:
        if not isinstance(row, dict):
            continue
        generation = row.get("generation")
        if not isinstance(generation, dict):
            continue
        label = _generation_label_from_name(str(generation.get("name") or ""))
        if label:
            labels.add(label)
    return sorted(labels, key=lambda value: GENERATION_ORDER.get(value, 99))


def _generation_span_text(labels: list[str]) -> str | None:
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]} to {labels[-1]}"


def _relation_labels(
    relation_rows: list[dict[str, Any]],
    *,
    exclude_names: set[str] | None = None,
    limit: int = 3,
) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    exclusions = {name.strip().lower() for name in (exclude_names or set()) if name.strip()}
    for row in relation_rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("name") or "").strip()
        if not raw:
            continue
        if raw.lower() in exclusions:
            continue
        label = _slug_to_words(raw).title()
        if not label:
            continue
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _source_label(source_type: str) -> str:
    mapping = {
        "pokemon-species": "Pokémon species",
        "move": "move",
        "ability": "ability",
        "item": "item",
        "location": "location",
        "location-area": "location",
        "type": "type",
    }
    return mapping.get(source_type, source_type.replace("-", " ").strip() or "entry")


def _replacement_for_source(source_type: str) -> str:
    mapping = {
        "pokemon-species": "this Pokémon",
        "move": "this move",
        "ability": "this ability",
        "item": "this item",
        "location": "this location",
        "location-area": "this location",
        "type": "this type",
    }
    return mapping.get(source_type, "this entry")


def _answer_parts(display_answer: str) -> list[str]:
    return [part for part in display_answer.upper().split(" ") if part]


def _answer_word_lengths(display_answer: str) -> str:
    parts = _answer_parts(display_answer)
    return ",".join(str(len(part)) for part in parts)


def _answer_fragments(display_answer: str) -> list[str]:
    parts = _answer_parts(display_answer)
    fragments = set()
    for part in parts:
        if len(part) >= 2:
            fragments.add(part)
    joined = "".join(parts)
    spaced = " ".join(parts)
    hyphenated = "-".join(parts)
    for value in (joined, spaced, hyphenated):
        if len(value.replace(" ", "").replace("-", "")) >= 2:
            fragments.add(value)
    return sorted(fragments, key=len, reverse=True)


def _strip_answer_fragments(clue: str, display_answer: str, source_type: str) -> str:
    out = clue
    replacement = _replacement_for_source(source_type)
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = out.replace("this Pokémon Pokémon", "this Pokémon")
    out = out.replace("this item item", "this item")
    out = out.replace("this move move", "this move")
    out = out.replace("this ability ability", "this ability")
    out = out.replace("this location location", "this location")
    out = out.replace("this type type", "this type")
    return _as_sentence(out.strip())


def _clue_contains_answer_fragment(clue: str, display_answer: str) -> bool:
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            return True
    return False


def _clue_quality_reasons(clue: str, display_answer: str) -> list[str]:
    text = _clean_text(clue)
    if not text:
        return ["empty_clue"]

    reasons: list[str] = []
    if any(pattern.search(text) for pattern in DISALLOWED_CLUE_PATTERNS):
        reasons.append("disallowed_pattern")
    if any(pattern.search(text) for pattern in GENERIC_CLUE_PATTERNS):
        reasons.append("generic_template")
    if any(pattern.search(text) for pattern in LOW_QUALITY_PATTERNS):
        reasons.append("low_quality_surface")
    if len(text) < 24:
        reasons.append("clue_too_short")
    if _clue_contains_answer_fragment(text, display_answer):
        reasons.append("answer_fragment_leak")
    return reasons


def _write_unresolved_reports(
    *,
    rows: list[dict[str, str]],
    csv_path: Path = UNRESOLVED_REPORT_CSV_PATH,
    json_path: Path = UNRESOLVED_REPORT_JSON_PATH,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "answer",
        "candidate_clue",
        "source_type",
        "source_id",
        "source_ref",
        "reasons",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    reason_counts: Counter[str] = Counter()
    for row in rows:
        for reason in str(row.get("reasons", "")).split("|"):
            reason = reason.strip()
            if reason:
                reason_counts[reason] += 1

    payload = {
        "totalUnresolved": len(rows),
        "reasonCounts": dict(sorted(reason_counts.items())),
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_payload_index(cache_dir: Path) -> dict[tuple[str, int], dict[str, Any]]:
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted(cache_dir.glob("*.json")):
        resource = path.name.split("_", 1)[0]
        if resource not in {"pokemon-species", "move", "item", "location", "location-area", "ability", "type"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        resource_id = payload.get("id")
        if not isinstance(resource_id, int):
            continue
        index[(resource, resource_id)] = payload
    return index


def _replace_effect_chance(text: str, payload: dict[str, Any]) -> str:
    effect_chance = payload.get("effect_chance")
    if effect_chance is None:
        return text.replace("$effect_chance", "X")
    return text.replace("$effect_chance", str(effect_chance))


def _short_effect(payload: dict[str, Any]) -> str | None:
    effect_entries = payload.get("effect_entries")
    if isinstance(effect_entries, list) and effect_entries:
        for row in effect_entries:
            if row.get("language", {}).get("name") == "en":
                short_effect = row.get("short_effect") or row.get("effect")
                if isinstance(short_effect, str) and short_effect.strip():
                    return _replace_effect_chance(short_effect, payload)
    flavor_entries = payload.get("flavor_text_entries")
    if isinstance(flavor_entries, list):
        for row in flavor_entries:
            if row.get("language", {}).get("name") == "en":
                flavor = row.get("flavor_text")
                if isinstance(flavor, str) and flavor.strip():
                    return flavor
    return None


def _build_species_clue(payload: dict[str, Any]) -> str:
    genus = None
    genera = payload.get("genera")
    if isinstance(genera, list):
        genus = _english_value(genera, key="genus")
        if genus:
            genus = genus.replace("Pokemon", "Pokémon")

    flavor = None
    flavor_entries = payload.get("flavor_text_entries")
    if isinstance(flavor_entries, list):
        for row in flavor_entries:
            if row.get("language", {}).get("name") == "en":
                raw = row.get("flavor_text")
                if isinstance(raw, str) and raw.strip():
                    flavor = raw
                    break

    generation = _generation_label(payload)
    color = payload.get("color", {}).get("name") if isinstance(payload.get("color"), dict) else None
    shape = payload.get("shape", {}).get("name") if isinstance(payload.get("shape"), dict) else None
    egg_groups = [
        _slug_to_words(str(group.get("name") or "")).lower()
        for group in payload.get("egg_groups", [])
        if isinstance(group, dict) and group.get("name")
    ]
    capture_rate = payload.get("capture_rate")

    traits: list[str] = []
    if generation:
        traits.append(generation)
    if isinstance(color, str) and color:
        traits.append(f"{_slug_to_words(color).lower()} color")
    if isinstance(shape, str) and shape:
        traits.append(f"{_slug_to_words(shape).lower()} body shape")
    if egg_groups:
        traits.append(f"egg group {'/'.join(egg_groups[:2])}")
    if isinstance(capture_rate, int):
        traits.append(f"capture rate {capture_rate}")

    parts: list[str] = []
    if genus:
        parts.append(_as_sentence(genus))
    if flavor:
        parts.append(_as_sentence(flavor))
    if traits:
        parts.append(_as_sentence("Traits: " + "; ".join(traits)))
    if not parts:
        parts.append(f"Pokémon species. National Pokédex #{payload.get('id', '?')}.")
    return " ".join(part for part in parts if part).strip()


def _build_move_clue(payload: dict[str, Any]) -> str:
    effect = _short_effect(payload) or "Move from the core battle system."
    generation = _generation_label(payload)
    move_class = payload.get("damage_class", {}).get("name")
    class_label = _slug_to_words(str(move_class)).lower() if move_class else "battle"
    power = payload.get("power")
    accuracy = payload.get("accuracy")
    pp = payload.get("pp")
    priority = payload.get("priority")
    target = payload.get("target", {}).get("name") if isinstance(payload.get("target"), dict) else None

    extra: list[str] = []
    if isinstance(power, int):
        extra.append(f"Power {power}")
    if isinstance(accuracy, int):
        extra.append(f"Accuracy {accuracy}")
    if isinstance(pp, int):
        extra.append(f"PP {pp}")
    if isinstance(priority, int):
        extra.append(f"Priority {priority}")
    if isinstance(target, str) and target:
        extra.append(f"Target {_slug_to_words(target).lower()}")

    intro_parts: list[str] = []
    if generation:
        intro_parts.append(generation)
    intro_parts.append(f"{class_label} move")
    intro = " ".join(part for part in intro_parts if part).strip()
    suffix = f" ({', '.join(extra)})" if extra else ""
    return _as_sentence(f"{intro}: {_clean_text(effect)}{suffix}")


def _build_ability_clue(payload: dict[str, Any]) -> str:
    effect = _short_effect(payload) or "Battle ability from the core games."
    generation = _generation_label(payload)
    main_series = payload.get("is_main_series")
    qualifier = " (side-series data)" if main_series is False else ""
    if generation:
        return _as_sentence(f"{generation} ability{qualifier}: {_clean_text(effect)}")
    return _as_sentence(f"Ability{qualifier}: {_clean_text(effect)}")


def _build_item_clue(payload: dict[str, Any]) -> str:
    effect = _short_effect(payload)
    category = payload.get("category", {}).get("name")
    category_label = _slug_to_words(str(category)).title() if category else "Item"
    generations = _game_generation_labels(payload)
    generation_span = _generation_span_text(generations)

    details: list[str] = []
    if generation_span:
        details.append(f"seen in {generation_span}")

    cost = payload.get("cost")
    fling_power = payload.get("fling_power")
    fling_effect = payload.get("fling_effect") if isinstance(payload.get("fling_effect"), dict) else {}
    fling_effect_name = str(fling_effect.get("name") or "").strip()

    if isinstance(cost, int) and cost > 0:
        details.append(f"shop cost {cost}")
    if isinstance(fling_power, int) and fling_power > 0:
        details.append(f"fling power {fling_power}")
    if fling_effect_name:
        details.append(f"fling effect {_slug_to_words(fling_effect_name).lower()}")

    attributes = payload.get("attributes") if isinstance(payload.get("attributes"), list) else []
    attr_labels = [
        _slug_to_words(str(attr.get("name") or "")).lower()
        for attr in attributes
        if isinstance(attr, dict) and attr.get("name")
    ]
    if attr_labels:
        details.append(f"attributes {', '.join(attr_labels[:2])}")

    held_by = payload.get("held_by_pokemon") if isinstance(payload.get("held_by_pokemon"), list) else []
    if held_by:
        details.append(f"held by {len(held_by)} species")

    if effect:
        suffix = f" ({'; '.join(details[:4])})" if details else ""
        return _as_sentence(f"{category_label} item: {_clean_text(effect)}{suffix}")

    if details:
        return _as_sentence(f"{category_label} item ({'; '.join(details[:5])})")

    item_id = payload.get("id")
    if isinstance(item_id, int):
        return _as_sentence(f"{category_label} item index #{item_id} from core game data")
    return _as_sentence(f"{category_label} item from core game data")


def _build_location_clue(payload: dict[str, Any]) -> str:
    region_payload = payload.get("region") if isinstance(payload.get("region"), dict) else {}
    region = region_payload.get("name")
    region_label = _slug_to_words(str(region)).title() if region else "the Pokémon world"
    areas = payload.get("areas") if isinstance(payload.get("areas"), list) else []
    area_count = len(areas)
    generations = _game_generation_labels(payload)
    generation_span = _generation_span_text(generations)
    location_id = payload.get("id")

    details: list[str] = [f"region {region_label}"]
    if generation_span:
        details.append(f"listed in {generation_span}")
    details.append(f"{area_count} named area{'s' if area_count != 1 else ''}")
    if isinstance(location_id, int):
        details.append(f"location index #{location_id}")
    return _as_sentence("Location: " + "; ".join(details))


def _build_type_clue(payload: dict[str, Any]) -> str:
    rel = payload.get("damage_relations", {}) if isinstance(payload.get("damage_relations"), dict) else {}
    type_name = str(payload.get("name") or "").strip().lower()
    exclude = {type_name} if type_name else set()

    strong = _relation_labels(rel.get("double_damage_to", []), exclude_names=exclude)
    weak = _relation_labels(rel.get("double_damage_from", []), exclude_names=exclude)
    resist = _relation_labels(rel.get("half_damage_from", []), exclude_names=exclude)
    immune_to = _relation_labels(rel.get("no_damage_from", []), exclude_names=exclude, limit=2)
    no_effect_on = _relation_labels(rel.get("no_damage_to", []), exclude_names=exclude, limit=2)

    details: list[str] = []
    if strong:
        details.append(f"double damage to {', '.join(strong)}")
    if weak:
        details.append(f"double damage from {', '.join(weak)}")
    if resist:
        details.append(f"resists {', '.join(resist)}")
    if immune_to:
        details.append(f"immune to {', '.join(immune_to)}")
    if no_effect_on:
        details.append(f"no effect on {', '.join(no_effect_on)}")

    generation = _generation_label(payload)
    intro = f"{generation} elemental type" if generation else "Elemental type"
    if details:
        return _as_sentence(f"{intro}: {'; '.join(details)}")

    type_id = payload.get("id")
    if isinstance(type_id, int):
        return _as_sentence(f"{intro} with type index {type_id}")
    return _as_sentence(f"{intro} from core game data")


def _dedupe_hint(row: dict[str, Any]) -> str:
    source_type = str(row.get("sourceType") or "entry")
    source_id = row.get("sourceId")
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else None
    generation = _generation_label(payload) if payload else None

    details: list[str] = []
    if generation:
        details.append(generation)
    if source_id is not None:
        details.append(f"{source_type} #{source_id}")
    if details:
        return "; ".join(details)

    lengths = _answer_word_lengths(str(row.get("answer") or ""))
    if lengths:
        return f"Word lengths {lengths}"
    return "Distinct crossword entry"


def _build_clue(
    *,
    source_type: str,
    payload: dict[str, Any] | None,
    display_answer: str,
    source_id: int | None,
) -> str:
    if payload is None:
        return ""

    if source_type == "pokemon-species":
        return _build_species_clue(payload)
    if source_type == "move":
        return _build_move_clue(payload)
    if source_type == "ability":
        return _build_ability_clue(payload)
    if source_type == "item":
        return _build_item_clue(payload)
    if source_type in {"location", "location-area"}:
        return _build_location_clue(payload)
    if source_type == "type":
        return _build_type_clue(payload)
    return ""


def main() -> None:
    entries = json.loads(WORDLIST_PATH.read_text(encoding="utf-8"))
    payload_index = _load_payload_index(POKEAPI_CACHE_DIR)

    rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, str]] = []

    def mark_unresolved(
        *,
        answer: str,
        clue: str,
        source_type: str,
        source_id: int | None,
        source_ref: str,
        reasons: list[str],
    ) -> None:
        unresolved_rows.append(
            {
                "answer": answer,
                "candidate_clue": _clean_text(clue),
                "source_type": source_type,
                "source_id": str(source_id) if isinstance(source_id, int) else "",
                "source_ref": source_ref,
                "reasons": "|".join(reasons),
            }
        )

    for row in entries:
        parts = row.get("parts") or [row["word"]]
        display_answer = " ".join(str(part).strip() for part in parts if str(part).strip())
        display_answer = _clean_text(display_answer.upper())

        source_ref = str(row.get("sourceRef", ""))
        source_type = str(row.get("sourceType", ""))
        parsed_type, source_id = _parse_source_ref(source_ref)
        key_type = parsed_type or source_type
        payload = payload_index.get((key_type, source_id)) if source_id is not None else None
        final_source_type = source_type or (parsed_type or "pokemon")

        clue = _build_clue(
            source_type=final_source_type,
            payload=payload,
            display_answer=display_answer,
            source_id=source_id,
        )
        if not clue:
            mark_unresolved(
                answer=display_answer,
                clue=clue,
                source_type=final_source_type,
                source_id=source_id,
                source_ref=source_ref,
                reasons=["missing_payload_or_builder_output"],
            )
            continue

        clue = _strip_answer_fragments(clue, display_answer, final_source_type)
        initial_reasons = _clue_quality_reasons(clue, display_answer)
        if initial_reasons:
            mark_unresolved(
                answer=display_answer,
                clue=clue,
                source_type=final_source_type,
                source_id=source_id,
                source_ref=source_ref,
                reasons=initial_reasons,
            )
            continue

        rows.append(
            {
                "answer": display_answer,
                "clue": clue,
                "sourceType": final_source_type,
                "sourceId": source_id,
                "sourceRef": source_ref,
                "payload": payload,
            }
        )

    # Ensure no exact-duplicate clues remain.
    buckets: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        buckets[row["clue"]].append(idx)

    for clue, idxs in buckets.items():
        if len(idxs) <= 1:
            continue
        for pos in idxs:
            hint = _dedupe_hint(rows[pos])
            rows[pos]["clue"] = _as_sentence(f"{clue} ({hint})")

    # Ensure no answer fragments or low-quality surfaces leak after dedupe edits.
    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        reasons = _clue_quality_reasons(str(row["clue"]), str(row["answer"]))
        if reasons:
            mark_unresolved(
                answer=str(row["answer"]),
                clue=str(row["clue"]),
                source_type=str(row.get("sourceType") or ""),
                source_id=row.get("sourceId") if isinstance(row.get("sourceId"), int) else None,
                source_ref=str(row.get("sourceRef") or ""),
                reasons=[f"post_dedupe_{reason}" for reason in reasons],
            )
            continue
        filtered_rows.append(row)
    rows = filtered_rows

    # Guarantee clue uniqueness without disallowed fallback content.
    post_buckets: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        post_buckets[row["clue"]].append(idx)
    for clue, idxs in post_buckets.items():
        if len(idxs) <= 1:
            continue
        for offset, pos in enumerate(idxs, start=1):
            hint = _dedupe_hint(rows[pos])
            rows[pos]["clue"] = _as_sentence(f"{clue} ({hint}; variant {offset})")

    final_rows: list[dict[str, Any]] = []
    for row in rows:
        reasons = _clue_quality_reasons(str(row["clue"]), str(row["answer"]))
        if reasons:
            mark_unresolved(
                answer=str(row["answer"]),
                clue=str(row["clue"]),
                source_type=str(row.get("sourceType") or ""),
                source_id=row.get("sourceId") if isinstance(row.get("sourceId"), int) else None,
                source_ref=str(row.get("sourceRef") or ""),
                reasons=[f"post_unique_{reason}" for reason in reasons],
            )
            continue
        final_rows.append(row)

    output_rows = sorted(((row["answer"], row["clue"]) for row in final_rows), key=lambda x: x[0].replace(" ", ""))
    with OUTPUT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(output_rows)
    _write_unresolved_reports(rows=unresolved_rows)

    clue_counts = Counter(clue for _, clue in output_rows)
    duplicate_clues = sum(1 for count in clue_counts.values() if count > 1)
    print(f"Wrote {OUTPUT_CSV_PATH} ({len(output_rows)} rows)")
    print(f"Duplicate clue strings remaining: {duplicate_clues}")
    print(f"Unresolved clue rows: {len(unresolved_rows)}")
    if unresolved_rows:
        reason_counts: Counter[str] = Counter()
        for unresolved in unresolved_rows:
            for reason in unresolved["reasons"].split("|"):
                if reason:
                    reason_counts[reason] += 1
        print(f"Unresolved reason counts: {dict(sorted(reason_counts.items()))}")
    print(f"Unresolved report CSV: {UNRESOLVED_REPORT_CSV_PATH}")
    print(f"Unresolved report JSON: {UNRESOLVED_REPORT_JSON_PATH}")


if __name__ == "__main__":
    main()
