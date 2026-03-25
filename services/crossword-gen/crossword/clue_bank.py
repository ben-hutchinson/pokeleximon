from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crossword.clue_candidate_qa import score_candidate


SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")
TOKEN_RE = re.compile(r"[^A-Z0-9]")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")

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

SOURCE_LABELS = {
    "pokemon-species": "species",
    "move": "move",
    "ability": "ability",
    "item": "item",
    "location": "location",
    "location-area": "encounter area",
    "type": "type",
}

GENERIC_CONNECTION_TITLES = {
    "pokemon species",
    "pokemon moves",
    "pokemon abilities",
    "pokemon items",
    "pokemon locations",
    "pokemon types",
    "species",
    "moves",
    "abilities",
    "items",
    "locations",
    "types",
}

GENERIC_DEFINITION_SEEDS = {
    "battle move",
    "battle ability",
    "battle element",
    "game item",
    "core-series species",
    "core-games item",
    "inventory item",
    "species",
    "move",
    "ability",
    "item",
    "location",
    "type",
}

DISALLOWED_CLUE_PATTERNS = (
    re.compile(r"(?i)\bpokeapi\b"),
    re.compile(r"(?i)\bjapanese\b"),
    re.compile(r"(?i)\bfallback clue\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\bxxx\b"),
    re.compile(r"(?i)\b(todo|tbd|lorem ipsum)\b"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"\*{3,}"),
)

STYLE_PRIORITY = {
    "manual_override": 0,
    "editorial_seed": 1,
    "signature": 2,
    "semantic": 3,
    "taxonomy": 4,
    "descriptor": 5,
    "fallback": 6,
}

GENERIC_PRUNE_TEXTS = {
    "boosting trait",
    "protective trait",
    "priority trait",
    "switching trait",
    "debuffing trait",
    "critical-hit trait",
    "weather-linked trait",
    "held battle item",
    "species-specific item",
    "plot advancement",
    "collectibles",
    "loot",
    "z crystals",
    "tm crafting material",
}

GENERIC_PRUNE_PATTERNS = (
    re.compile(r"^gen [ivx]+ (ability|item|location|species|move)$", re.IGNORECASE),
    re.compile(r"^gen [ivx]+ [a-z]+ move$", re.IGNORECASE),
    re.compile(r"^(battle|held|inventory|core-games|regional|adventure|generic) (ability|item|location|species|move)$", re.IGNORECASE),
    re.compile(r"^[a-z]+ landmark$", re.IGNORECASE),
    re.compile(r"^[a-z]+ route$", re.IGNORECASE),
    re.compile(r"^route in [a-z]+$", re.IGNORECASE),
    re.compile(r"^[a-z]+ (status|physical|special) move$", re.IGNORECASE),
    re.compile(r"^regional (town|city|village|landmark|location)$", re.IGNORECASE),
)

TYPE_BASE_DESCRIPTORS = {
    "BUG": ("insectoid element", "plant-hitting type"),
    "DARK": ("sneaky element", "psychic-hitting type"),
    "DRAGON": ("draconic element", "dragon-resistant type"),
    "ELECTRIC": ("shock element", "flying-hitting type"),
    "FAIRY": ("charming element", "dragon-resistant type"),
    "FIGHTING": ("combat element", "rock-hitting type"),
    "FIRE": ("burning element", "ice-resistant type"),
    "FLYING": ("airborne element", "ground-immune type"),
    "GHOST": ("spectral element", "normal-immune type"),
    "GRASS": ("leafy element", "water-hitting type"),
    "GROUND": ("earthbound element", "electric-immune type"),
    "ICE": ("frozen element", "dragon-hitting type"),
    "NORMAL": ("baseline element", "ghost-vulnerable type"),
    "POISON": ("toxic element", "grass-hitting type"),
    "PSYCHIC": ("mind-based element", "fighting-hitting type"),
    "ROCK": ("stony element", "flying-hitting type"),
    "STEEL": ("metallic element", "poison-immune type"),
    "WATER": ("aquatic element", "fire-hitting type"),
}

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


@dataclass(frozen=True)
class Candidate:
    text: str
    style: str
    provenance: str


def _clean_text(value: str) -> str:
    out = str(value or "").replace("\n", " ").replace("\f", " ")
    out = out.replace("Pokemon", "Pokemon").replace("Pokémon", "Pokemon")
    out = NON_ASCII_RE.sub("", out)
    return WHITESPACE_RE.sub(" ", out).strip()


def _normalize_answer(value: str) -> str:
    return TOKEN_RE.sub("", str(value or "").upper())


def _parse_source_ref(source_ref: str) -> tuple[str | None, int | None]:
    match = SOURCE_REF_RE.search(str(source_ref or "").strip())
    if not match:
        return None, None
    source_type = match.group(1)
    try:
        source_id = int(match.group(2))
    except ValueError:
        return source_type, None
    return source_type, source_id


def _slug_to_words(value: str) -> str:
    return " ".join(part for part in str(value or "").replace("_", "-").split("-") if part).strip()


def _titleize_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in _slug_to_words(value).split())


def _english_value(rows: list[Any], key: str = "name") -> str | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("language", {}).get("name") != "en":
            continue
        raw = row.get(key)
        if isinstance(raw, str):
            cleaned = _clean_text(raw)
            if cleaned:
                return cleaned
    return None


def _answer_parts(display_answer: str) -> list[str]:
    return [part for part in str(display_answer or "").upper().replace("-", " ").split() if part]


def _answer_fragments(display_answer: str) -> list[str]:
    parts = _answer_parts(display_answer)
    fragments: set[str] = set()
    for part in parts:
        if len(part) >= 2:
            fragments.add(part)
    for joined in ("".join(parts), " ".join(parts), "-".join(parts)):
        token_count = len(joined.replace(" ", "").replace("-", ""))
        if token_count >= 2:
            fragments.add(joined)
    return sorted(fragments, key=len, reverse=True)


def _contains_answer_fragment(clue: str, display_answer: str) -> bool:
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            return True
    return False


def _answer_fragment_flags(clue: str, display_answer: str) -> tuple[bool, bool]:
    hits: list[str] = []
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            hits.append(fragment.upper())
    if not hits:
        return False, False
    return True, all(hit in GENERIC_ANSWER_FRAGMENTS for hit in hits)


def _word_count(text: str) -> int:
    return len([part for part in re.split(r"\s+", str(text).strip()) if part])


def _normalize_clue(text: str) -> str:
    out = _clean_text(text)
    out = out.strip(" .;,:!?")
    out = re.sub(r"\s{2,}", " ", out)
    return out


def _generation_label_from_name(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    return GENERATION_LABELS.get(value.strip().lower())


def _generation_label(payload: dict[str, Any]) -> str | None:
    generation = payload.get("generation")
    if isinstance(generation, dict):
        return _generation_label_from_name(str(generation.get("name") or ""))
    return None


def _game_generation_labels(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    game_indices = payload.get("game_indices")
    if not isinstance(game_indices, list):
        return labels
    for row in game_indices:
        if not isinstance(row, dict):
            continue
        generation = row.get("generation")
        if not isinstance(generation, dict):
            continue
        label = _generation_label_from_name(str(generation.get("name") or ""))
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _first_sentence(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    return _clean_text(SENTENCE_SPLIT_RE.split(cleaned)[0])


def _effect_text(payload: dict[str, Any]) -> str:
    effect_entries = payload.get("effect_entries")
    if isinstance(effect_entries, list):
        for row in effect_entries:
            if not isinstance(row, dict):
                continue
            if row.get("language", {}).get("name") != "en":
                continue
            for key in ("short_effect", "effect"):
                raw = row.get(key)
                if isinstance(raw, str):
                    cleaned = _first_sentence(raw.replace("$effect_chance", "X"))
                    if cleaned:
                        return cleaned
    flavor_entries = payload.get("flavor_text_entries")
    if isinstance(flavor_entries, list):
        for row in flavor_entries:
            if not isinstance(row, dict):
                continue
            if row.get("language", {}).get("name") != "en":
                continue
            raw = row.get("flavor_text") or row.get("text")
            if isinstance(raw, str):
                cleaned = _first_sentence(raw)
                if cleaned:
                    return cleaned
    return ""


def _effect_tags(text: str) -> list[str]:
    lowered = str(text or "").lower()
    tags: list[str] = []
    checks = (
        ("priority", "priority"),
        ("heal", "healing"),
        ("restore", "healing"),
        ("drain", "draining"),
        ("burn", "burning"),
        ("paraly", "paralyzing"),
        ("poison", "poisoning"),
        ("sleep", "sleep-inducing"),
        ("freeze", "freezing"),
        ("confus", "confusing"),
        ("switch", "switching"),
        ("critical hit", "crit-boosting"),
        ("recoil", "recoil"),
        ("weather", "weather-setting"),
        ("trap", "trapping"),
        ("protect", "protective"),
        ("speed", "speed-raising"),
        ("attack", "attack-shifting"),
        ("defense", "defense-shifting"),
        ("special attack", "special-attack-shifting"),
        ("special defense", "special-defense-shifting"),
        ("accuracy", "accuracy-shifting"),
        ("evasion", "evasion-shifting"),
        ("intimidate", "intimidation-related"),
        ("immune", "immunity"),
        ("prevents", "preventive"),
        ("flinch", "flinch-causing"),
    )
    for needle, tag in checks:
        if needle in lowered and tag not in tags:
            tags.append(tag)
    return tags[:4]


def _compact_category_label(source_type: str, payload: dict[str, Any]) -> str:
    if source_type == "item":
        category = payload.get("category")
        name = str(category.get("name") or "") if isinstance(category, dict) else ""
        raw = _slug_to_words(name).lower()
        mapping = {
            "mega stones": "mega stone",
            "species specific": "species-specific item",
            "held items": "held item",
            "healing": "healing item",
            "choice scarves": "choice item",
            "choice bands": "choice item",
            "choice specs": "choice item",
            "stat boost": "battle item",
            "vitamins": "vitamin item",
            "medicine": "medicine item",
            "mulch": "field item",
            "baking only": "sandwich item",
            "pick ingredients": "picnic item",
            "berries": "berry",
            "evolution": "evolution item",
            "plot advancement": "key item",
        }
        if raw in mapping:
            return mapping[raw]
        if raw.endswith(" items"):
            return raw[:-1]
        if raw:
            if "item" not in raw and "berry" not in raw and "stone" not in raw:
                return f"{raw} item"
            return raw
    return SOURCE_LABELS.get(source_type, "entry")


def load_payload_index(cache_dir: Path) -> dict[tuple[str, int], dict[str, Any]]:
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted(cache_dir.glob("*.json")):
        prefix = path.name.split("_", 1)[0]
        if prefix not in {"pokemon-species", "move", "item", "location", "location-area", "ability", "type"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        source_id = payload.get("id")
        if isinstance(source_id, int):
            index[(prefix, source_id)] = payload
    return index


def load_answer_rows(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def load_overrides(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            answer = _normalize_answer(str(row.get("answer") or ""))
            clue = _normalize_clue(str(row.get("clue") or ""))
            enabled = str(row.get("enabled") or "").strip().lower()
            if not answer or not clue or enabled not in {"1", "true", "yes", "y"}:
                continue
            out.setdefault(answer, []).append(clue)
    return out


def load_editorial_seeds(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        answer_key = _normalize_answer(str(key or ""))
        if not answer_key or not isinstance(value, dict):
            continue
        out[answer_key] = value
    return out


def _species_candidates(payload: dict[str, Any], facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []

    genus = _english_value(payload.get("genera", []), key="genus")
    if genus:
        genus = _normalize_clue(genus.replace("Pokémon", "Pokemon"))
        facts["genus"] = genus
        candidates.append(Candidate(genus, "signature", "species:genus"))

    generation = _generation_label(payload)
    if generation:
        facts["generation"] = generation
        descriptors.append(f"{generation} species")
        if genus:
            candidates.append(Candidate(f"{generation} {genus}", "taxonomy", "species:generation+genus"))

    color = payload.get("color")
    color_name = _titleize_slug(str(color.get("name") or "")) if isinstance(color, dict) else ""
    if color_name:
        facts["color"] = color_name
        descriptors.append(f"{color_name} species")
        if genus:
            candidates.append(Candidate(f"{color_name} {genus}", "descriptor", "species:color+genus"))

    habitat = payload.get("habitat")
    habitat_name = _titleize_slug(str(habitat.get("name") or "")) if isinstance(habitat, dict) else ""
    if habitat_name:
        facts["habitat"] = habitat_name
        descriptors.append(f"{habitat_name} species")
        if genus:
            candidates.append(Candidate(f"{habitat_name} {genus}", "descriptor", "species:habitat+genus"))

    egg_groups = payload.get("egg_groups")
    if isinstance(egg_groups, list):
        labels = [
            f"{_titleize_slug(str(group.get('name') or ''))} egg-group species"
            for group in egg_groups
            if isinstance(group, dict) and str(group.get("name") or "").strip()
        ]
        if labels:
            facts["eggGroups"] = labels[:3]
            descriptors.extend(labels[:2])
            candidates.append(Candidate(labels[0], "semantic", "species:egg-group"))

    if not candidates and generation:
        candidates.append(Candidate(f"{generation} species", "fallback", "species:generation-only"))
    if not candidates:
        candidates.append(Candidate("core-series species", "fallback", "species:generic"))
    return candidates, descriptors


def _move_candidates(payload: dict[str, Any], facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []

    generation = _generation_label(payload)
    move_type = payload.get("type")
    move_type_name = _titleize_slug(str(move_type.get("name") or "")) if isinstance(move_type, dict) else ""
    damage_class = payload.get("damage_class")
    damage_class_name = _titleize_slug(str(damage_class.get("name") or "")) if isinstance(damage_class, dict) else ""
    effect = _effect_text(payload)
    tags = _effect_tags(effect)

    if generation:
        facts["generation"] = generation
        descriptors.append(f"{generation} moves")
    if move_type_name:
        facts["moveType"] = move_type_name
        descriptors.append(f"{move_type_name} moves")
    if damage_class_name:
        facts["damageClass"] = damage_class_name
        descriptors.append(f"{damage_class_name} moves")

    for tag in tags:
        phrase = f"{tag} move"
        candidates.append(Candidate(phrase, "semantic", f"move:{tag}"))
        if tag.endswith("ing"):
            descriptors.append(f"{tag.capitalize()} moves")
    priority = payload.get("priority")
    if isinstance(priority, int) and priority > 0:
        candidates.append(Candidate("priority move", "semantic", "move:priority"))
        descriptors.append("Priority moves")

    if move_type_name and damage_class_name:
        candidates.append(Candidate(f"{move_type_name} {damage_class_name.lower()} move", "signature", "move:type+class"))
    if generation and damage_class_name:
        candidates.append(Candidate(f"{generation} {damage_class_name.lower()} move", "taxonomy", "move:generation+class"))
    if generation and move_type_name:
        candidates.append(Candidate(f"{generation} {move_type_name.lower()} move", "taxonomy", "move:generation+type"))
    if damage_class_name and not any(c.text == f"{damage_class_name.lower()} move" for c in candidates):
        candidates.append(Candidate(f"{damage_class_name.lower()} move", "descriptor", "move:class-only"))

    if not candidates:
        candidates.append(Candidate("battle move", "fallback", "move:generic"))
    return candidates, descriptors


def _ability_candidates(payload: dict[str, Any], facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []

    generation = _generation_label(payload)
    effect = _effect_text(payload)
    tags = _effect_tags(effect)
    if generation:
        facts["generation"] = generation
        descriptors.append(f"{generation} abilities")
    for tag in tags:
        candidates.append(Candidate(f"{tag} ability", "semantic", f"ability:{tag}"))
        descriptors.append(f"{tag.capitalize()} abilities")
    if payload.get("is_main_series") is False:
        candidates.append(Candidate("side-series ability", "descriptor", "ability:side-series"))
    else:
        candidates.append(Candidate("battle ability", "descriptor", "ability:battle"))
        descriptors.append("Battle abilities")
    candidates.append(Candidate("passive trait", "descriptor", "ability:passive-trait"))
    candidates.append(Candidate("battle trait", "descriptor", "ability:battle-trait"))
    if generation:
        candidates.append(Candidate(f"{generation} ability", "taxonomy", "ability:generation"))
    if not candidates:
        candidates.append(Candidate("battle ability", "fallback", "ability:generic"))
    return candidates, descriptors


def _item_candidates(payload: dict[str, Any], facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []

    generation_labels = _game_generation_labels(payload)
    category_label = _compact_category_label("item", payload)
    effect = _effect_text(payload)
    tags = _effect_tags(effect)
    facts["category"] = category_label
    candidates.append(Candidate(category_label, "signature", "item:category"))
    descriptors.append(f"{category_label.title()}s" if not category_label.endswith("y") else f"{category_label[:-1].title()}ies")
    if generation_labels:
        facts["generations"] = generation_labels
        candidates.append(Candidate(f"{generation_labels[0]} {category_label}", "taxonomy", "item:generation+category"))
        descriptors.append(f"{generation_labels[0]} items")
    candidates.append(Candidate("inventory item", "descriptor", "item:inventory"))
    for tag in tags:
        candidates.append(Candidate(f"{tag} item", "semantic", f"item:{tag}"))
        descriptors.append(f"{tag.capitalize()} items")

    attributes = payload.get("attributes")
    if isinstance(attributes, list):
        attr_names = [
            _titleize_slug(str(attr.get("name") or ""))
            for attr in attributes
            if isinstance(attr, dict) and str(attr.get("name") or "").strip()
        ]
        if attr_names:
            facts["attributes"] = attr_names[:3]
            if "Holdable" in attr_names and not any(c.text == "held item" for c in candidates):
                candidates.append(Candidate("held item", "descriptor", "item:holdable"))
                descriptors.append("Held items")

    if "mega stone" in category_label:
        candidates.append(Candidate("mega-evolution item", "semantic", "item:mega"))
        descriptors.append("Mega evolution items")
    if "berry" in category_label:
        candidates.append(Candidate("battle berry", "descriptor", "item:berry"))
        descriptors.append("Battle berries")
    if "held item" not in category_label:
        candidates.append(Candidate("core-games item", "descriptor", "item:core-games"))
    if not candidates:
        candidates.append(Candidate("game item", "fallback", "item:generic"))
    return candidates, descriptors


def _location_candidates(source_type: str, payload: dict[str, Any], facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []

    region = payload.get("region")
    region_label = _titleize_slug(str(region.get("name") or "")) if isinstance(region, dict) else ""
    generations = _game_generation_labels(payload)
    label = "encounter area" if source_type == "location-area" else "location"
    if region_label:
        facts["region"] = region_label
        candidates.append(Candidate(f"{region_label} {label}", "signature", f"{source_type}:region"))
        candidates.append(Candidate(f"{region_label} map {label}", "descriptor", f"{source_type}:region+map"))
        descriptors.append(f"{region_label} {label}s")
    if generations:
        facts["generations"] = generations
        candidates.append(Candidate(f"{generations[0]} {label}", "taxonomy", f"{source_type}:generation"))
        descriptors.append(f"{generations[0]} {label}s")
    if source_type == "location-area":
        candidates.append(Candidate("named encounter area", "descriptor", "location-area:named"))
        descriptors.append("Encounter areas")
    else:
        candidates.append(Candidate("regional map location", "descriptor", "location:regional"))
    return candidates, descriptors


def _type_candidates(payload: dict[str, Any], facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []

    type_name = str(payload.get("name") or "").strip().upper()
    base = TYPE_BASE_DESCRIPTORS.get(type_name, ("battle element", "combat type"))
    candidates.append(Candidate(base[0], "signature", "type:base"))
    candidates.append(Candidate(base[1], "descriptor", "type:base-secondary"))

    relations = payload.get("damage_relations")
    if isinstance(relations, dict):
        def first_relation(key: str, suffix: str) -> str | None:
            rows = relations.get(key)
            if not isinstance(rows, list):
                return None
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                return f"{_titleize_slug(name)}-{suffix}"
            return None

        for key, suffix in (
            ("double_damage_to", "hitting type"),
            ("double_damage_from", "weak type"),
            ("half_damage_from", "resistant type"),
            ("no_damage_from", "immune type"),
        ):
            relation = first_relation(key, suffix)
            if relation:
                candidates.append(Candidate(relation.lower(), "semantic", f"type:{key}"))
                descriptors.append(f"{relation}s")
                break

    candidates.append(Candidate("battle element", "descriptor", "type:generic"))
    return candidates, descriptors


def _type_candidates_from_answer(answer_key: str, facts: dict[str, Any]) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    descriptors: list[str] = []
    base = TYPE_BASE_DESCRIPTORS.get(answer_key, ("battle element", "combat type"))
    candidates.append(Candidate(base[0], "signature", "type:answer-base"))
    candidates.append(Candidate(base[1], "descriptor", "type:answer-secondary"))
    candidates.append(Candidate("battle element", "descriptor", "type:generic"))
    descriptors.append(f"{_titleize_slug(answer_key)}-linked types")
    return candidates, descriptors


def _fallback_candidates(source_type: str) -> tuple[list[Candidate], list[str]]:
    label = SOURCE_LABELS.get(source_type, "entry")
    return [Candidate(f"core-series {label}", "fallback", f"{source_type}:fallback")], []


def _quality_score(text: str, display_answer: str, style: str) -> tuple[float, list[str]]:
    score = 100.0
    flags: list[str] = []
    normalized = _normalize_clue(text)
    if not normalized:
        return 0.0, ["empty_clue"]
    if any(pattern.search(normalized) for pattern in DISALLOWED_CLUE_PATTERNS):
        flags.append("disallowed_pattern")
        score -= 100.0
    has_fragment, generic_only_fragment = _answer_fragment_flags(normalized, display_answer)
    if has_fragment:
        flags.append("answer_fragment_leak")
        score -= 18.0 if generic_only_fragment else 80.0

    word_count = _word_count(normalized)
    if word_count < 2:
        flags.append("too_short")
        score -= 20.0
    elif word_count > 8:
        flags.append("long_form")
        score -= (word_count - 8) * 4.0
    if word_count > 14:
        flags.append("too_long")
        score -= 50.0

    if any(ch.isdigit() for ch in normalized):
        flags.append("numeric_dump")
        score -= 12.0
    if any(token in normalized for token in (";", ":", "(", ")")):
        flags.append("punctuation_heavy")
        score -= 10.0

    score -= STYLE_PRIORITY.get(style, 6) * 2.0
    return max(score, 0.0), sorted(set(flags))


def _is_generic_candidate_row(row: dict[str, Any]) -> bool:
    text = _normalize_clue(str(row.get("text") or "")).lower()
    style = str(row.get("style") or "")
    if not text:
        return False
    if text in GENERIC_PRUNE_TEXTS or text in GENERIC_DEFINITION_SEEDS or text in GENERIC_CONNECTION_TITLES:
        return True
    if any(pattern.match(text) for pattern in GENERIC_PRUNE_PATTERNS):
        return True
    if style in {"fallback", "category"} and _word_count(text) <= 4:
        return True
    if style in {"descriptor", "taxonomy"} and float(row.get("qualityScore", 0.0)) < 72.0 and _word_count(text) <= 4:
        return True
    return False


def _dedupe_candidates(display_answer: str, raw_candidates: list[Candidate]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        text = _normalize_clue(candidate.text)
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        score, flags = _quality_score(text, display_answer, candidate.style)
        _, generic_only_fragment = _answer_fragment_flags(text, display_answer)
        approved = "disallowed_pattern" not in flags and "too_long" not in flags and (
            "answer_fragment_leak" not in flags or generic_only_fragment
        )
        out.append(
            {
                "text": text,
                "style": candidate.style,
                "provenance": candidate.provenance,
                "qualityScore": round(score, 2),
                "qualityFlags": flags,
                "approved": approved,
            }
        )
    out.sort(key=lambda row: (-float(row["qualityScore"]), STYLE_PRIORITY.get(str(row["style"]), 6), row["text"]))
    return out


def _seed_rows(
    *,
    answer_display: str,
    seed_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(seed_payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, clue in enumerate(seed_payload.get("standard_clue_stems", []), start=1):
        text = _normalize_clue(str(clue or ""))
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        score, flags = _quality_score(text, answer_display, "editorial_seed")
        _, generic_only_fragment = _answer_fragment_flags(text, answer_display)
        approved = "disallowed_pattern" not in flags and "too_long" not in flags and (
            "answer_fragment_leak" not in flags or generic_only_fragment
        )
        rows.append(
            {
                "text": text,
                "style": "editorial_seed",
                "provenance": f"editorial_seed:{idx}",
                "qualityScore": round(score + 6.0, 2),
                "qualityFlags": flags,
                "approved": approved,
            }
        )
    rows.sort(key=lambda row: (-float(row["qualityScore"]), row["text"]))
    return rows


def _prune_generic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved_specific = sum(1 for row in rows if bool(row.get("approved")) and not _is_generic_candidate_row(row))
    if approved_specific < 3:
        return rows
    for row in rows:
        if not bool(row.get("approved")) or not _is_generic_candidate_row(row):
            continue
        row["approved"] = False
        flags = list(row.get("qualityFlags") or [])
        if "pruned_generic_fallback" not in flags:
            flags.append("pruned_generic_fallback")
        row["qualityFlags"] = sorted(set(flags))
    return rows


def _cryptic_definition_seeds(standard_clues: list[dict[str, Any]]) -> tuple[list[str], bool]:
    seeds: list[str] = []
    generic_hits = 0
    for row in standard_clues:
        if not bool(row.get("approved", False)):
            continue
        text = _normalize_clue(str(row.get("text") or "")).lower()
        if not text:
            continue
        if text.startswith("gen "):
            parts = text.split(" ", 2)
            if len(parts) == 3:
                text = parts[2]
        if text in {"battle move", "battle ability", "battle element", "game item", "core-series species", "location"}:
            generic_hits += 1
        if text not in seeds:
            seeds.append(text)
    trimmed = seeds[:4]
    generic_fallback = bool(trimmed) and generic_hits >= len(trimmed)
    return trimmed, generic_fallback


def _curated_crossword_candidates(
    *,
    answer_display: str,
    evidence: dict[str, Any] | None,
    curated: dict[str, Any] | None,
    fallback_used: bool,
) -> list[dict[str, Any]]:
    if not isinstance(curated, dict):
        return []
    response = curated.get("response")
    if not isinstance(response, dict):
        return []
    curator_mode = str(curated.get("mode") or "agent").strip().lower()
    source_label = "local_curator" if curator_mode == "local" else "agent"
    provenance_label = "bulbapedia_local" if curator_mode == "local" else "bulbapedia_agent"
    confidence_raw = response.get("confidence", 0.0)
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, row in enumerate(response.get("crossword_candidates", []), start=1):
        if not isinstance(row, dict):
            continue
        text = _normalize_clue(str(row.get("text") or ""))
        if not text:
            continue
        key = text.upper()
        if key in seen:
            continue
        seen.add(key)
        mystery_score = float(row.get("mystery_score", 0.0)) if isinstance(row.get("mystery_score"), (int, float)) else 0.0
        specificity_score = (
            float(row.get("specificity_score", 0.0))
            if isinstance(row.get("specificity_score"), (int, float))
            else 0.0
        )
        score, flags, approved = score_candidate(
            text=text,
            answer_display=answer_display,
            evidence=evidence,
            evidence_ref=str(row.get("evidence_ref") or ""),
            style="agent_curated_fallback" if fallback_used else "agent_curated",
            agent_confidence=confidence,
            mystery_score=mystery_score,
            specificity_score=specificity_score,
        )
        rows.append(
            {
                "text": text,
                "style": "agent_curated",
                "provenance": provenance_label,
                "qualityScore": score,
                "qualityFlags": flags,
                "approved": approved,
                "evidenceRef": str(row.get("evidence_ref") or ""),
                "agentScores": {
                    "confidence": round(confidence, 3),
                    "mystery": round(mystery_score, 3),
                    "specificity": round(specificity_score, 3),
                },
                "source": source_label,
                "rankPosition": idx,
            }
        )
    _prune_generic_rows(rows)
    rows.sort(key=lambda row: (-float(row["qualityScore"]), row["text"]))
    return rows


def _curated_fact_nuggets(curated: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(curated, dict):
        return []
    response = curated.get("response")
    if not isinstance(response, dict):
        return []
    rows: list[dict[str, Any]] = []
    for row in response.get("fact_nuggets", []):
        if not isinstance(row, dict):
            continue
        text = _normalize_clue(str(row.get("text") or ""))
        evidence_ref = str(row.get("evidence_ref") or "").strip()
        specificity = row.get("specificity")
        if not text or not evidence_ref or not isinstance(specificity, (int, float)):
            continue
        rows.append(
            {
                "text": text,
                "evidenceRef": evidence_ref,
                "specificity": round(float(specificity), 3),
            }
        )
    return rows[:12]


def _curated_definition_seeds(curated: dict[str, Any] | None) -> list[str]:
    if not isinstance(curated, dict):
        return []
    response = curated.get("response")
    if not isinstance(response, dict):
        return []
    out: list[str] = []
    for value in response.get("cryptic_definition_seeds", []):
        text = _normalize_clue(str(value or "")).lower()
        if not text or text in GENERIC_DEFINITION_SEEDS:
            continue
        if text not in out:
            out.append(text)
    return out[:4]


def _curated_connections_descriptors(curated: dict[str, Any] | None) -> list[str]:
    if not isinstance(curated, dict):
        return []
    response = curated.get("response")
    if not isinstance(response, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in response.get("connections_descriptors", []):
        text = _normalize_clue(str(value or ""))
        if not text:
            continue
        if _word_count(text) < 2 or _word_count(text) > 6:
            continue
        key = text.lower()
        if key in GENERIC_CONNECTION_TITLES:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out[:6]


def _product_owner_selected_clues(product_owner_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(product_owner_result, dict):
        return []
    rows = product_owner_result.get("selectedCandidates")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _normalize_clue(str(row.get("text") or ""))
        if not text:
            continue
        out.append(
            {
                "text": text,
                "style": str(row.get("style") or "agent_curated"),
                "provenance": str(row.get("provenance") or f"provider:{row.get('provider') or row.get('source') or 'external'}"),
                "qualityScore": round(float(row.get("qualityScore") or 0.0), 2),
                "qualityFlags": sorted(set(row.get("qualityFlags") or [])),
                "approved": bool(row.get("approved", False)),
                "evidenceRef": str(row.get("evidenceRef") or "lead"),
                "agentScores": dict(row.get("agentScores") or {}),
                "source": str(row.get("source") or row.get("provider") or ""),
                "rankPosition": int(row.get("rankPosition", len(out) + 1) or len(out) + 1),
                "difficulty": str(row.get("difficulty") or "medium"),
                "checklistScores": dict(row.get("checklistScores") or {}),
            }
        )
    return out


def _editorial_definition_seeds(seed_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(seed_payload, dict):
        return []
    out: list[str] = []
    for value in seed_payload.get("cryptic_definition_seeds", []):
        text = _normalize_clue(str(value or "")).lower()
        if not text or text in GENERIC_DEFINITION_SEEDS or text in out:
            continue
        out.append(text)
    return out[:4]


def _editorial_connections_descriptors(seed_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(seed_payload, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in seed_payload.get("connections_descriptors", []):
        text = _normalize_clue(str(value or ""))
        if not text:
            continue
        key = text.lower()
        if key in GENERIC_CONNECTION_TITLES or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out[:6]


def _prune_generic_definition_seeds(seeds: list[str]) -> list[str]:
    specifics = [seed for seed in seeds if seed not in GENERIC_DEFINITION_SEEDS and not seed.startswith("gen ")]
    if len(specifics) >= 2:
        return specifics[:4]
    return seeds[:4]


def _prune_generic_descriptors(descriptors: list[str]) -> list[str]:
    specifics = [value for value in descriptors if value.strip().lower() not in GENERIC_CONNECTION_TITLES]
    return (specifics or descriptors)[:6]


def _build_entry(
    answer_row: dict[str, Any],
    payload_index: dict[tuple[str, int], dict[str, Any]],
    overrides: dict[str, list[str]],
    editorial_seed: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
    curated: dict[str, Any] | None = None,
    product_owner_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer_key = _normalize_answer(str(answer_row.get("answerKey") or ""))
    answer_display = _clean_text(str(answer_row.get("answerDisplay") or "")).upper()
    source_ref = str(answer_row.get("sourceRef") or "").strip()
    source_type = str(answer_row.get("sourceType") or "").strip()
    parsed_type, source_id = _parse_source_ref(source_ref)
    final_source_type = parsed_type or source_type
    payload = payload_index.get((final_source_type, source_id)) if isinstance(source_id, int) else None
    facts: dict[str, Any] = {}

    raw_candidates: list[Candidate] = []
    descriptor_list: list[str] = []
    if answer_key in overrides:
        for idx, clue in enumerate(overrides[answer_key], start=1):
            raw_candidates.append(Candidate(clue, "manual_override", f"override:{idx}"))
    fallback_used = False

    if isinstance(payload, dict):
        builder = {
            "pokemon-species": _species_candidates,
            "move": _move_candidates,
            "ability": _ability_candidates,
            "item": _item_candidates,
            "location": lambda row, info: _location_candidates("location", row, info),
            "location-area": lambda row, info: _location_candidates("location-area", row, info),
            "type": _type_candidates,
        }.get(final_source_type)
        if builder is not None:
            generated_candidates, descriptors = builder(payload, facts)
            raw_candidates.extend(generated_candidates)
            descriptor_list.extend(descriptors)
    elif final_source_type == "type":
        generated_candidates, descriptors = _type_candidates_from_answer(answer_key, facts)
        raw_candidates.extend(generated_candidates)
        descriptor_list.extend(descriptors)
    if not raw_candidates:
        generated_candidates, descriptors = _fallback_candidates(final_source_type)
        raw_candidates.extend(generated_candidates)
        descriptor_list.extend(descriptors)
        fallback_used = True

    heuristic_clues = _dedupe_candidates(answer_display, raw_candidates)
    curated_clues = _curated_crossword_candidates(
        answer_display=answer_display,
        evidence=evidence,
        curated=curated,
        fallback_used=fallback_used,
    )
    product_owner_clues = _product_owner_selected_clues(product_owner_result)
    editorial_rows = _seed_rows(answer_display=answer_display, seed_payload=editorial_seed)
    standard_clues = product_owner_clues or curated_clues or heuristic_clues
    if editorial_rows:
        merged = editorial_rows + standard_clues
        seen_texts: set[str] = set()
        standard_clues = []
        for row in merged:
            text = str(row.get("text") or "")
            key = text.upper()
            if not text or key in seen_texts:
                continue
            seen_texts.add(key)
            standard_clues.append(row)
    if answer_key in overrides:
        override_clues = [row for row in heuristic_clues if str(row.get("style")) == "manual_override"]
        merged = override_clues + [row for row in standard_clues if str(row.get("style")) != "manual_override"]
        seen_texts: set[str] = set()
        standard_clues = []
        for row in merged:
            text = str(row.get("text") or "")
            key = text.upper()
            if not text or key in seen_texts:
                continue
            seen_texts.add(key)
            standard_clues.append(row)
    _prune_generic_rows(standard_clues)
    approved_clues = [row for row in standard_clues if bool(row.get("approved", False))]
    editorial_definition_seeds = _editorial_definition_seeds(editorial_seed)
    curated_definition_seeds = _curated_definition_seeds(curated)
    derived_definition_seeds, generic_seed_fallback = _cryptic_definition_seeds(standard_clues)
    cryptic_seeds = _prune_generic_definition_seeds(editorial_definition_seeds or curated_definition_seeds or derived_definition_seeds)

    normalized_descriptors: list[str] = _editorial_connections_descriptors(editorial_seed) or _curated_connections_descriptors(curated)
    seen_descriptors: set[str] = set()
    if not normalized_descriptors:
        for descriptor in descriptor_list:
            cleaned = _normalize_clue(descriptor)
            if not cleaned:
                continue
            word_count = _word_count(cleaned)
            if word_count < 2 or word_count > 6:
                continue
            key = cleaned.lower()
            if key in seen_descriptors:
                continue
            seen_descriptors.add(key)
            normalized_descriptors.append(cleaned)
    normalized_descriptors = _prune_generic_descriptors(normalized_descriptors)

    quality_flags: list[str] = []
    if len(approved_clues) < 3:
        quality_flags.append("needs_more_crossword_clues")
    if generic_seed_fallback or not cryptic_seeds:
        quality_flags.append("generic_cryptic_definition_fallback")
    if not normalized_descriptors:
        quality_flags.append("weak_connections_descriptors")
    if not curated_clues:
        quality_flags.append("fallback_only")
    elif curated and not bool(curated.get("schemaValid", False)):
        quality_flags.append("agent_schema_invalid")
    if isinstance(product_owner_result, dict):
        quality_flags.extend(str(flag) for flag in product_owner_result.get("entryFlags", []) if str(flag).strip())
    if answer_key in overrides:
        quality_flags.append("manual_override_used")
    if editorial_rows:
        quality_flags.append("editorial_seed_used")

    review_status = str(product_owner_result.get("reviewStatus") or "").strip() if isinstance(product_owner_result, dict) else ""
    if not review_status:
        review_status = "approved" if not quality_flags else "needs_review"
    quality_score = round(
        sum(float(row.get("qualityScore", 0.0)) for row in approved_clues[:3]) / max(len(approved_clues[:3]), 1), 2
    )

    standard_entries: list[dict[str, Any]] = []
    for idx, row in enumerate(standard_clues, start=1):
        standard_entries.append(
            {
                "clueId": f"{answer_key}-{idx}",
                **row,
            }
        )

    fact_nuggets = _curated_fact_nuggets(curated)
    evidence_source = None
    if isinstance(evidence, dict):
        evidence_source = {
            "status": evidence.get("status"),
            "pageTitle": evidence.get("pageTitle"),
            "pageUrl": evidence.get("pageUrl"),
            "pageRevisionId": evidence.get("pageRevisionId"),
        }

    return {
        "answerKey": answer_key,
        "answerDisplay": answer_display,
        "sourceType": final_source_type,
        "sourceRef": source_ref,
        "evidenceSource": evidence_source,
        "factNuggets": fact_nuggets,
        "facts": facts,
        "crosswordCandidates": standard_entries,
        "standardClues": standard_entries,
        "crypticDefinitionSeeds": cryptic_seeds,
        "connectionsDescriptors": normalized_descriptors,
        "qualityScore": quality_score,
        "qaFlags": quality_flags,
        "qualityFlags": quality_flags,
        "reviewStatus": review_status,
        "provenance": {
            "builderVersion": "clue-bank-v2",
            "overrideApplied": answer_key in overrides,
            "editorialSeedApplied": bool(editorial_rows),
            "agentStatus": curated.get("status") if isinstance(curated, dict) else "not_run",
            "curatorMode": curated.get("mode") if isinstance(curated, dict) else None,
        },
        "riskFlags": list(curated.get("response", {}).get("risk_flags", [])) if isinstance(curated, dict) else [],
        "productOwner": {
            "reviewStatus": review_status,
            "entryFlags": sorted(set(str(flag) for flag in (product_owner_result or {}).get("entryFlags", []) if str(flag).strip())),
            "selectionRationale": str((product_owner_result or {}).get("selectionRationale") or ""),
        },
        "checklistScores": dict((product_owner_result or {}).get("checklistScores") or {}),
        "selectionNotes": str((product_owner_result or {}).get("selectionRationale") or ""),
    }


def build_clue_bank(
    answer_rows: list[dict[str, Any]],
    payload_index: dict[tuple[str, int], dict[str, Any]],
    overrides: dict[str, list[str]] | None = None,
    editorial_seeds: dict[str, dict[str, Any]] | None = None,
    evidence_by_answer: dict[str, dict[str, Any]] | None = None,
    curated_by_answer: dict[str, dict[str, Any]] | None = None,
    product_owner_by_answer: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    overrides = overrides or {}
    editorial_seeds = editorial_seeds or {}
    evidence_by_answer = evidence_by_answer or {}
    curated_by_answer = curated_by_answer or {}
    product_owner_by_answer = product_owner_by_answer or {}
    coverage_by_source: dict[str, Counter[str]] = defaultdict(Counter)
    under_min_answers: list[str] = []
    generic_cryptic_answers: list[str] = []
    weak_connections_answers: list[str] = []
    fallback_only_answers: list[str] = []
    agent_invalid_answers: list[str] = []

    for row in answer_rows:
        answer_key = _normalize_answer(str(row.get("answerKey") or ""))
        entry = _build_entry(
            row,
            payload_index,
            overrides,
            editorial_seed=editorial_seeds.get(answer_key),
            evidence=evidence_by_answer.get(answer_key),
            curated=curated_by_answer.get(answer_key),
            product_owner_result=product_owner_by_answer.get(answer_key),
        )
        entries.append(entry)
        source_type = str(entry["sourceType"])
        approved_count = sum(1 for clue in entry["standardClues"] if bool(clue.get("approved", False)))
        coverage_by_source[source_type]["total"] += 1
        if approved_count >= 3:
            coverage_by_source[source_type]["atLeast3Approved"] += 1
        if approved_count > 0:
            coverage_by_source[source_type]["withAnyApproved"] += 1
        if "needs_more_crossword_clues" in entry["qualityFlags"]:
            under_min_answers.append(str(entry["answerDisplay"]))
        if "generic_cryptic_definition_fallback" in entry["qualityFlags"]:
            generic_cryptic_answers.append(str(entry["answerDisplay"]))
        if "weak_connections_descriptors" in entry["qualityFlags"]:
            weak_connections_answers.append(str(entry["answerDisplay"]))
        if "fallback_only" in entry["qualityFlags"]:
            fallback_only_answers.append(str(entry["answerDisplay"]))
        if "agent_schema_invalid" in entry["qualityFlags"]:
            agent_invalid_answers.append(str(entry["answerDisplay"]))

    total_answers = len(entries)
    at_least_three = sum(
        1 for entry in entries if sum(1 for clue in entry["standardClues"] if bool(clue.get("approved", False))) >= 3
    )
    report = {
        "totalAnswers": total_answers,
        "answersWithAtLeast3ApprovedClues": at_least_three,
        "approvedCoveragePct": round((at_least_three / total_answers) * 100.0, 2) if total_answers else 0.0,
        "coverageBySourceType": {
            source: {
                "total": int(counts.get("total", 0)),
                "withAnyApproved": int(counts.get("withAnyApproved", 0)),
                "atLeast3Approved": int(counts.get("atLeast3Approved", 0)),
            }
            for source, counts in sorted(coverage_by_source.items())
        },
        "underMinApprovedAnswers": under_min_answers[:200],
        "genericCrypticFallbackAnswers": generic_cryptic_answers[:200],
        "weakConnectionsDescriptorAnswers": weak_connections_answers[:200],
        "fallbackOnlyAnswers": fallback_only_answers[:200],
        "agentSchemaInvalidAnswers": agent_invalid_answers[:200],
        "unresolvedCount": len([entry for entry in entries if entry["reviewStatus"] != "approved"]),
    }
    entries.sort(key=lambda row: row["answerKey"])
    return entries, report


def project_crossword_rows(entries: list[dict[str, Any]], max_per_answer: int = 3) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for entry in entries:
        approved = [row for row in entry["standardClues"] if bool(row.get("approved", False))]
        for row in approved[: max(1, max_per_answer)]:
            rows.append((str(entry["answerDisplay"]), str(row["text"])))
    rows.sort(key=lambda row: (row[0].replace(" ", ""), row[1]))
    return rows


def project_crossword_wide_rows(entries: list[dict[str, Any]], max_per_answer: int = 3) -> list[tuple[str, ...]]:
    rows: list[tuple[str, ...]] = [("answer", "clue 1", "clue 2", "clue 3")]
    for entry in sorted(entries, key=lambda row: str(row.get("answerDisplay") or "").replace(" ", "")):
        answer_display = str(entry.get("answerDisplay") or "")
        approved = [row for row in entry.get("standardClues", []) if bool(row.get("approved", False))]
        selected = [str(row.get("text") or "") for row in approved[: max(1, max_per_answer)]]
        while len(selected) < max_per_answer:
            selected.append("")
        rows.append((answer_display, *selected[:max_per_answer]))
    return rows


def build_connections_rules(
    entries: list[dict[str, Any]],
    min_group_size: int = 4,
    max_group_size: int = 12,
    max_rules: int = 256,
) -> list[dict[str, Any]]:
    buckets: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        label = _clean_text(str(entry.get("answerDisplay") or "")).upper()
        if not label:
            continue
        for descriptor in entry.get("connectionsDescriptors", []):
            cleaned = _normalize_clue(str(descriptor))
            if cleaned:
                buckets[cleaned].add(label)

    rules: list[dict[str, Any]] = []
    for title, labels in buckets.items():
        normalized_title = title.strip().lower()
        if normalized_title in GENERIC_CONNECTION_TITLES:
            continue
        if len(labels) < min_group_size or len(labels) > max_group_size:
            continue
        if _word_count(title) < 2 or _word_count(title) > 6:
            continue
        label_list = sorted(labels)
        rule_id = re.sub(r"[^a-z0-9]+", "-", normalized_title).strip("-")
        if not rule_id:
            continue
        rules.append(
            {
                "id": rule_id,
                "title": title,
                "labels": label_list,
                "minLength": 4,
                "maxLength": 14,
            }
        )

    def rule_score(rule: dict[str, Any]) -> tuple[int, int, int, str]:
        label_count = len(rule["labels"])
        title_word_count = _word_count(str(rule["title"]))
        return (abs(label_count - 4), -title_word_count, -label_count, str(rule["title"]).lower())

    rules.sort(key=rule_score)
    return rules[:max_rules]


def build_override_candidates(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in entries:
        approved = [row for row in entry["standardClues"] if bool(row.get("approved", False))]
        rejected = [row for row in entry["standardClues"] if not bool(row.get("approved", False))]
        current = approved[0]["text"] if approved else ""
        reasons = "|".join(entry.get("qualityFlags", []))
        if not reasons:
            continue
        rows.append(
            {
                "answer": str(entry["answerDisplay"]),
                "current_clue": current,
                "source_type": str(entry["sourceType"]),
                "source_id": str(_parse_source_ref(str(entry["sourceRef"]))[1] or ""),
                "canonical_slug": "",
                "source_ref": str(entry["sourceRef"]),
                "evidence_page_url": str(((entry.get("evidenceSource") or {}).get("pageUrl") or "")),
                "approved_count": str(len(approved)),
                "fallback_used": "true" if "fallback_only" in entry.get("qualityFlags", []) else "false",
                "rejected_candidates": " || ".join(str(row.get("text") or "") for row in rejected[:3]),
                "rejected_reason_codes": " || ".join(
                    ",".join(str(flag) for flag in row.get("qualityFlags", [])) for row in rejected[:3]
                ),
                "manual_clue": "",
                "reason_codes": reasons,
                "reason_details": reasons.replace("|", ", "),
                "status": str(entry["reviewStatus"]),
            }
        )
    rows.sort(key=lambda row: row["answer"])
    return rows


def write_csv_rows(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_override_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "answer",
            "current_clue",
            "source_type",
            "source_id",
            "canonical_slug",
            "source_ref",
            "evidence_page_url",
            "approved_count",
            "fallback_used",
            "rejected_candidates",
            "rejected_reason_codes",
            "manual_clue",
            "reason_codes",
            "reason_details",
            "status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
