from __future__ import annotations

from typing import Any


def _candidate(
    text: str,
    evidence_ref: str,
    mystery_score: float,
    specificity_score: float,
    style: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "evidence_ref": evidence_ref,
        "mystery_score": round(mystery_score, 3),
        "specificity_score": round(specificity_score, 3),
        "style": style,
    }


def _unique_strings(values: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def _fact_map(facts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        out.setdefault(str(fact.get("kind") or ""), []).append(fact)
    return out


def _pretty_stat(value: str) -> str:
    lowered = " ".join(str(value or "").replace(".", "").split()).lower()
    mapping = {
        "sp atk": "Special Attack",
        "special atk": "Special Attack",
        "special attack": "Special Attack",
        "sp def": "Special Defense",
        "special def": "Special Defense",
        "special defense": "Special Defense",
        "atk": "Attack",
        "attack": "Attack",
        "def": "Defense",
        "defense": "Defense",
        "speed": "Speed",
    }
    return mapping.get(lowered, str(value or "").strip().title())


def _compact_stat(value: str) -> str:
    pretty = _pretty_stat(value)
    mapping = {
        "Special Attack": "Sp. Atk",
        "Special Defense": "Sp. Def",
    }
    return mapping.get(pretty, pretty)


def _species_payload(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = _fact_map(facts)
    candidates: list[dict[str, Any]] = []
    cryptic: list[str] = []
    descriptors: list[str] = []
    risk_flags: list[str] = []

    typing_generation = by_kind.get("typing_generation", [])
    visual = by_kind.get("visual_color", [])
    archetype = by_kind.get("archetype", [])
    solitary = by_kind.get("solitary_lore", [])
    aggressive = by_kind.get("aggressive_lore", []) + by_kind.get("temperament", [])
    carrying = by_kind.get("carry_strength", [])
    crest = by_kind.get("crest_trait", [])
    mega_typing = by_kind.get("mega_typing", [])
    statline = by_kind.get("statline", [])
    evolves_from = by_kind.get("evolves_from", [])
    final_form = by_kind.get("final_form", [])
    mega_available = by_kind.get("mega_available", [])
    genus_signature = by_kind.get("genus_signature", [])
    generation_genus = by_kind.get("generation_genus", [])
    color_genus = by_kind.get("color_genus", [])
    egg_group = by_kind.get("egg_group", [])

    if visual and archetype:
        candidates.append(
            _candidate(
                f"{visual[0]['color'].title()} {archetype[0]['text']}",
                "Biology",
                0.78,
                0.86,
                "visual",
            )
        )
        cryptic.append(archetype[0]["text"])
    if solitary:
        candidates.append(_candidate("Leaves its flock behind", solitary[0]["evidence_ref"], 0.84, 0.9, "lore"))
        candidates.append(_candidate("Lives apart from its flock", solitary[0]["evidence_ref"], 0.76, 0.88, "lore"))
        cryptic.append("flock loner")
    if carrying:
        candidates.append(_candidate("Carries other Pokemon aloft", carrying[0]["evidence_ref"], 0.72, 0.82, "lore"))
        cryptic.append("powerful flier")
    if aggressive:
        candidates.append(_candidate("Savage flier that challenges giants", aggressive[0]["evidence_ref"], 0.73, 0.82, "temperament"))
        candidates.append(_candidate("Large-foe challenger", aggressive[0]["evidence_ref"], 0.79, 0.78, "temperament"))
        cryptic.append("savage flier")
    if crest:
        candidates.append(_candidate("Comb-fussy intimidating bird", crest[0]["evidence_ref"], 0.7, 0.77, "trait"))
    if statline:
        attack = statline[0].get("attack")
        speed = statline[0].get("speed")
        if isinstance(attack, int) and isinstance(speed, int):
            candidates.append(_candidate(f"{attack} Attack, {speed} Speed species", statline[0]["evidence_ref"], 0.66, 0.9, "stats"))
            risk_flags.append("stat_specific")
    if mega_typing:
        mega_types = mega_typing[0].get("mega_types") or []
        if len(mega_types) == 2:
            candidates.append(_candidate(f"Mega form turns {mega_types[0]}/{mega_types[1]}", mega_typing[0]["evidence_ref"], 0.74, 0.88, "mega"))
            descriptors.append(f"Mega {mega_types[0]}/{mega_types[1]} forms")
    if typing_generation:
        types = typing_generation[0].get("types") or []
        generation = str(typing_generation[0].get("generation") or "")
        if len(types) == 2 and generation:
            candidates.append(_candidate(f"{generation} {'/'.join(types)} species", typing_generation[0]["evidence_ref"], 0.58, 0.7, "taxonomy"))
            descriptors.append(f"{generation} {'/'.join(types)} species")
            cryptic.append(f"{'/'.join(types).lower()} species")
        elif len(types) == 1 and generation:
            candidates.append(_candidate(f"{generation} {types[0]} species", typing_generation[0]["evidence_ref"], 0.54, 0.66, "taxonomy"))
            descriptors.append(f"{generation} {types[0]} species")
            cryptic.append(f"{types[0].lower()} species")
    if evolves_from:
        base = str(evolves_from[0].get("evolves_from") or evolves_from[0]["text"])
        candidates.append(_candidate(f"Evolves from {base}", evolves_from[0]["evidence_ref"], 0.52, 0.72, "evolution"))
    if final_form:
        base = str(final_form[0].get("final_form_of") or final_form[0]["text"])
        candidates.append(_candidate(f"Final form of {base}", final_form[0]["evidence_ref"], 0.5, 0.7, "evolution"))
    if genus_signature:
        genus = str(genus_signature[0].get("genus") or genus_signature[0]["text"])
        candidates.append(_candidate(genus, genus_signature[0]["evidence_ref"], 0.48, 0.72, "signature"))
        cryptic.append(genus.lower())
        descriptors.append(genus)
    if generation_genus:
        candidates.append(_candidate(str(generation_genus[0]["text"]), generation_genus[0]["evidence_ref"], 0.44, 0.66, "signature"))
    if color_genus:
        candidates.append(_candidate(str(color_genus[0]["text"]), color_genus[0]["evidence_ref"], 0.42, 0.64, "signature"))
    if egg_group:
        candidates.append(_candidate(str(egg_group[0]["text"]), egg_group[0]["evidence_ref"], 0.38, 0.54, "taxonomy"))
    if mega_available and not mega_typing:
        candidates.append(_candidate("Mega-evolving species", mega_available[0]["evidence_ref"], 0.5, 0.66, "mega"))
    if visual and typing_generation:
        generation = str(typing_generation[0].get("generation") or "")
        types = typing_generation[0].get("types") or []
        if generation and types:
            candidates.append(
                _candidate(
                    f"{visual[0]['color'].title()} {generation} {'/'.join(types)} species",
                    visual[0]["evidence_ref"],
                    0.5,
                    0.8,
                    "visual_taxonomy",
                )
            )

    if archetype:
        descriptors.append("Aggressive bird species" if aggressive else f"{archetype[0]['text'].title()} species")
    if typing_generation:
        generation = str(typing_generation[0].get("generation") or "")
        if generation:
            descriptors.append(f"{generation} species")
    fact_nuggets = [
        {
            "text": str(fact["text"]),
            "evidence_ref": str(fact["evidence_ref"]),
            "specificity": float(fact["specificity"]),
        }
        for fact in facts[:12]
    ]

    default_cryptic = cryptic or [str(genus_signature[0]["text"]).lower()] if genus_signature else cryptic
    default_descriptors = descriptors or [str(genus_signature[0]["text"])] if genus_signature else descriptors

    return {
        "fact_nuggets": fact_nuggets,
        "crossword_candidates": candidates[:12],
        "cryptic_definition_seeds": _unique_strings(default_cryptic or ["core-series species"], 4),
        "connections_descriptors": _unique_strings(default_descriptors or ["Pokemon species"], 6),
        "risk_flags": _unique_strings(risk_flags, 4),
        "confidence": 0.82 if candidates else 0.35,
    }


def _keyword_effect(effect: str) -> list[str]:
    lowered = str(effect or "").lower()
    labels: list[str] = []
    checks = (
        ("critical hit", "critical-hit"),
        ("drain", "draining"),
        ("recover", "healing"),
        ("restore", "healing"),
        ("burn", "burning"),
        ("paraly", "paralyzing"),
        ("poison", "poisoning"),
        ("switch", "switching"),
        ("flinch", "flinch-causing"),
        ("priority", "priority"),
        ("act next", "turn-ordering"),
        ("next this turn", "turn-ordering"),
        ("raise", "boosting"),
        ("lower", "debuffing"),
        ("protect", "protective"),
    )
    for needle, label in checks:
        if needle in lowered:
            labels.append(label)
    return labels


def _generic_payload(facts: list[dict[str, Any]], source_type: str) -> dict[str, Any]:
    by_kind = _fact_map(facts)
    candidates: list[dict[str, Any]] = []
    cryptic: list[str] = []
    descriptors: list[str] = []
    risk_flags: list[str] = []

    for fact in facts:
        effect = str(fact.get("effect") or fact.get("text") or "")
        for label in _keyword_effect(effect):
            if source_type == "move":
                candidates.append(_candidate(f"{label} move", str(fact.get("evidence_ref") or "lead"), 0.55, 0.64, "effect"))
                descriptors.append(f"{label.title()} moves")
            elif source_type == "item":
                candidates.append(_candidate(f"{label} item", str(fact.get("evidence_ref") or "lead"), 0.5, 0.62, "effect"))
                descriptors.append(f"{label.title()} items")
            elif source_type == "ability":
                candidates.append(_candidate(f"{label} ability", str(fact.get("evidence_ref") or "lead"), 0.5, 0.62, "effect"))
                descriptors.append(f"{label.title()} abilities")

    for fact in by_kind.get("move_profile", []):
        move_type = str(fact.get("move_type") or "")
        damage_class = str(fact.get("damage_class") or "").lower()
        if move_type and damage_class:
            candidates.append(_candidate(f"{move_type} {damage_class} move", str(fact.get("evidence_ref") or "lead"), 0.42, 0.58, "taxonomy"))
            cryptic.append(f"{move_type.lower()} {damage_class} move")
            descriptors.append(f"{move_type} {damage_class.title()} moves")
    for fact in by_kind.get("move_taxonomy", []):
        text = str(fact.get("text") or "")
        if text:
            candidates.append(_candidate(text, str(fact.get("evidence_ref") or "lead"), 0.34, 0.54, "taxonomy"))
    for fact in by_kind.get("sleep_inflict", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Sleep-inducing move", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Move that puts foes to sleep", ref, 0.68, 0.84, "effect"))
    for fact in by_kind.get("fixed_damage", []):
        ref = str(fact.get("evidence_ref") or "lead")
        damage = int(fact.get("damage") or 0)
        if damage:
            candidates.append(_candidate(f"Always deals {damage} damage", ref, 0.76, 0.9, "effect"))
    for fact in by_kind.get("weight_damage", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Stronger against heavier targets", ref, 0.76, 0.88, "effect"))
        max_power = fact.get("max_power")
        if isinstance(max_power, int):
            candidates.append(_candidate(f"Can reach {max_power} power on heavy foes", ref, 0.68, 0.84, "effect"))
    for fact in by_kind.get("mirror_copy", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Copies the foe's last move", ref, 0.78, 0.9, "effect"))
    for fact in by_kind.get("field_hp_halve", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Halves everyone's HP", ref, 0.78, 0.9, "effect"))
    for fact in by_kind.get("battle_trap", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Prevents foes from leaving battle", ref, 0.74, 0.88, "effect"))
    for fact in by_kind.get("confuse_inflict", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Confusion-causing move", ref, 0.72, 0.84, "effect"))
    for fact in by_kind.get("screen_clear", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Removes Light Screen and Reflect", ref, 0.76, 0.9, "effect"))
    for fact in by_kind.get("fire_weaken", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Halves Fire damage", ref, 0.78, 0.9, "effect"))
    for fact in by_kind.get("weather_move", []):
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Battlefield weather move", ref, 0.62, 0.76, "effect"))
    for fact in by_kind.get("effect_text", []):
        effect = str(fact.get("effect") or fact.get("text") or "")
        ref = str(fact.get("evidence_ref") or "lead")
        lowered = effect.lower()
        if source_type == "move":
            if "cannot use held items" in lowered or ("cannot use" in lowered and "held item" in lowered):
                candidates.append(_candidate("Target cannot use held items", ref, 0.76, 0.88, "effect"))
                candidates.append(_candidate("Shuts off held items", ref, 0.7, 0.82, "effect"))
                candidates.append(_candidate("Held-item-locking move", ref, 0.66, 0.8, "effect"))
                cryptic.append("held-item lock")
                descriptors.append("Held-item-blocking moves")
            if "drain" in lowered:
                candidates.append(_candidate("Draining move", ref, 0.6, 0.72, "effect"))
            if "heal the user" in lowered:
                candidates.append(_candidate("Self-healing move", ref, 0.56, 0.7, "effect"))
            if "target act next" in lowered or "act next this turn" in lowered:
                candidates.append(_candidate("Turn-ordering move", ref, 0.62, 0.78, "effect"))
            if "target's" in lowered and "lower" in lowered:
                candidates.append(_candidate("Stat-lowering move", ref, 0.5, 0.66, "effect"))
    for fact in by_kind.get("priority", []):
        candidates.append(_candidate("priority move", str(fact.get("evidence_ref") or "lead"), 0.5, 0.66, "mechanic"))
    for fact in by_kind.get("power", []):
        power = fact.get("power")
        if isinstance(power, int):
            candidates.append(_candidate(f"{power}-power move", str(fact.get("evidence_ref") or "lead"), 0.36, 0.65, "stats"))
            risk_flags.append("stat_specific")
    for fact in by_kind.get("item_category", []):
        category = str(fact.get("category") or fact.get("text") or "")
        candidates.append(_candidate(category, str(fact.get("evidence_ref") or "lead"), 0.35, 0.52, "category"))
        cryptic.append(category)
        descriptors.append(category.title())
    for fact in by_kind.get("item_taxonomy", []):
        candidates.append(_candidate(str(fact.get("text") or ""), str(fact.get("evidence_ref") or "lead"), 0.34, 0.54, "taxonomy"))
    for fact in by_kind.get("ability_generation", []):
        candidates.append(_candidate(str(fact.get("text") or ""), str(fact.get("evidence_ref") or "lead"), 0.3, 0.42, "taxonomy"))
    for fact in by_kind.get("region", []):
        candidates.append(_candidate(str(fact.get("text") or ""), str(fact.get("evidence_ref") or "lead"), 0.32, 0.46, "taxonomy"))
        descriptors.append(str(fact.get("text") or ""))
        cryptic.append(str(fact.get("text") or ""))

    fact_nuggets = [
        {
            "text": str(fact["text"]),
            "evidence_ref": str(fact["evidence_ref"]),
            "specificity": float(fact["specificity"]),
        }
        for fact in facts[:12]
    ]
    return {
        "fact_nuggets": fact_nuggets,
        "crossword_candidates": candidates[:12],
        "cryptic_definition_seeds": _unique_strings(cryptic, 4),
        "connections_descriptors": _unique_strings(descriptors, 6),
        "risk_flags": _unique_strings(risk_flags, 4),
        "confidence": 0.68 if candidates else 0.25,
    }


def generate_curated_payload(*, source_type: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    if source_type == "pokemon-species":
        return _species_payload(facts)
    if source_type == "item":
        return _item_payload(facts)
    if source_type in {"location", "location-area"}:
        return _location_payload(facts)
    if source_type == "ability":
        return _ability_payload(facts)
    return _generic_payload(facts, source_type)


def _item_payload(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = _fact_map(facts)
    candidates: list[dict[str, Any]] = []
    cryptic: list[str] = []
    descriptors: list[str] = []
    risk_flags: list[str] = []

    if by_kind.get("ability_protection"):
        ref = str(by_kind["ability_protection"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Holder keeps its trait", ref, 0.82, 0.92, "effect"))
        candidates.append(_candidate("Blocks trait tampering", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Suppression-proof held item", ref, 0.72, 0.9, "effect"))
        cryptic.extend(["trait guard", "held protector", "trait keeper"])
        descriptors.extend(["Ability-protecting items", "Held battle items"])
    if by_kind.get("hidden_ability_swap"):
        ref = str(by_kind["hidden_ability_swap"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Unlocks a hidden trait", ref, 0.78, 0.94, "effect"))
        candidates.append(_candidate("Turns a standard trait rare", ref, 0.76, 0.88, "effect"))
        cryptic.extend(["hidden-trait changer", "trait-altering item"])
        descriptors.extend(["Hidden Ability items", "Ability-changing items"])
    if by_kind.get("rare_ability_swap"):
        ref = str(by_kind["rare_ability_swap"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Makes a regular trait rarer", ref, 0.72, 0.86, "effect"))
    if by_kind.get("hidden_ability_restriction"):
        ref = str(by_kind["hidden_ability_restriction"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Only for species with hidden traits", ref, 0.64, 0.82, "restriction"))
    if by_kind.get("berry_family"):
        ref = str(by_kind["berry_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Battle berry", ref, 0.58, 0.74, "family"))
        candidates.append(_candidate("Consumable held berry", ref, 0.54, 0.72, "family"))
        descriptors.append("Battle berries")
    if by_kind.get("berry_cooking"):
        fact = by_kind["berry_cooking"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        mediums = list(fact.get("recipe_mediums") or [])
        if "PokBlocks" in mediums and "Poffins" in mediums:
            candidates.append(_candidate("PokBlock and Poffin berry", ref, 0.76, 0.88, "family"))
        elif "PokBlocks" in mediums:
            candidates.append(_candidate("PokBlock-making berry", ref, 0.74, 0.86, "family"))
        elif "Poffins" in mediums:
            candidates.append(_candidate("Poffin-making berry", ref, 0.74, 0.86, "family"))
        candidates.append(_candidate("Berry-blending ingredient", ref, 0.68, 0.82, "family"))
        cryptic.append("berry ingredient")
    if by_kind.get("berry_gardening"):
        ref = str(by_kind["berry_gardening"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Loamy-soil berry crop", ref, 0.66, 0.78, "family"))
    if by_kind.get("berry_heal"):
        ref = str(by_kind["berry_heal"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Pinch-healing berry", ref, 0.74, 0.88, "effect"))
        candidates.append(_candidate("Half-HP recovery berry", ref, 0.7, 0.84, "effect"))
        cryptic.append("healing berry")
    if by_kind.get("berry_confusion"):
        ref = str(by_kind["berry_confusion"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Berry that may confuse", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate("Confusion-risk berry", ref, 0.62, 0.78, "effect"))
        cryptic.append("confusing berry")
    if by_kind.get("berry_pinch"):
        ref = str(by_kind["berry_pinch"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Low-HP trigger berry", ref, 0.66, 0.8, "effect"))
    if by_kind.get("tm_materials"):
        ref = str(by_kind["tm_materials"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("TM crafting material", ref, 0.56, 0.72, "family"))
        candidates.append(_candidate("Move-machine crafting item", ref, 0.52, 0.7, "family"))
        candidates.append(_candidate("Crafting drop for TMs", ref, 0.48, 0.68, "family"))
        cryptic.extend(["tm material", "crafting drop"])
        descriptors.append("TM crafting items")
    if by_kind.get("z_crystal") and not by_kind.get("signature_z_crystal") and not by_kind.get("type_z_crystal"):
        ref = str(by_kind["z_crystal"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Z-Move crystal", ref, 0.66, 0.8, "family"))
        candidates.append(_candidate("Held crystal for a Z-Move", ref, 0.62, 0.78, "family"))
        candidates.append(_candidate("Attack-upgrade crystal", ref, 0.56, 0.74, "family"))
        cryptic.append("z crystal")
        descriptors.append("Z crystals")
    if by_kind.get("signature_z_crystal"):
        fact = by_kind["signature_z_crystal"][0]
        holder = str(fact.get("holder_species") or "a species")
        base_move = str(fact.get("base_move") or "a move")
        z_move = str(fact.get("z_move") or "a signature Z-Move")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"{holder}-exclusive Z crystal", ref, 0.8, 0.92, "effect"))
        candidates.append(_candidate(f"{base_move} upgrade crystal", ref, 0.76, 0.9, "effect"))
        candidates.append(_candidate(f"Crystal for {z_move}", ref, 0.72, 0.88, "effect"))
        cryptic.extend(["signature z crystal", f"{holder.lower()} crystal"])
        descriptors.extend(["Signature Z crystals", "Species-specific Z crystals"])
    if by_kind.get("type_z_crystal"):
        fact = by_kind["type_z_crystal"][0]
        z_type = str(fact.get("z_move_type") or "typed")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"{z_type}-move Z crystal", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate(f"Crystal for {z_type} Z-Moves", ref, 0.68, 0.82, "effect"))
        cryptic.append(f"{z_type.lower()} z crystal")
        descriptors.append(f"{z_type} Z crystals")
    if by_kind.get("picnic_item"):
        ref = str(by_kind["picnic_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Picnic item", ref, 0.5, 0.66, "family"))
        candidates.append(_candidate("Picnic-kit item", ref, 0.46, 0.64, "family"))
        descriptors.append("Picnic items")
    if by_kind.get("picnic_play"):
        ref = str(by_kind["picnic_play"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Kickabout for picnics", ref, 0.74, 0.84, "effect"))
        candidates.append(_candidate("Picnic plaything", ref, 0.66, 0.78, "effect"))
    if by_kind.get("standard_issue_item"):
        fact = by_kind["standard_issue_item"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        scope = str(fact.get("issue_scope") or "official").lower()
        if scope == "academy":
            candidates.append(_candidate("Academy standard-issue gear", ref, 0.72, 0.84, "family"))
            candidates.append(_candidate("School-issued picnic gear", ref, 0.68, 0.8, "family"))
        else:
            candidates.append(_candidate("Standard-issue gear", ref, 0.62, 0.74, "family"))
    if by_kind.get("mint_family"):
        ref = str(by_kind["mint_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Nature-changing mint", ref, 0.72, 0.82, "family"))
        candidates.append(_candidate("Stat-nature mint", ref, 0.66, 0.78, "family"))
        candidates.append(_candidate("Mint that changes natures", ref, 0.62, 0.76, "family"))
        cryptic.append("nature mint")
        descriptors.append("Nature mints")
    if by_kind.get("mint_stat_profile"):
        fact = by_kind["mint_stat_profile"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        up_stat = _compact_stat(str(fact.get("up_stat") or "Attack"))
        down_stat = _compact_stat(str(fact.get("down_stat") or "Defense"))
        candidates.append(_candidate(f"{up_stat}-up, {down_stat}-down item", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate(f"{up_stat}-favoring nature changer", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate(f"{down_stat}-lowering nature item", ref, 0.68, 0.82, "effect"))
        cryptic.append(f"{up_stat.lower()} nature")
    if by_kind.get("fossil_family") and not by_kind.get("fossil_revival"):
        ref = str(by_kind["fossil_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Prehistoric revival item", ref, 0.66, 0.78, "family"))
        candidates.append(_candidate("Revival fossil item", ref, 0.62, 0.76, "family"))
        cryptic.append("fossil item")
    if by_kind.get("signature_family_item") and not by_kind.get("species_type_boost"):
        ref = str(by_kind["signature_family_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Species-linked power item", ref, 0.6, 0.74, "family"))
        candidates.append(_candidate("Signature battle item", ref, 0.58, 0.72, "family"))
        descriptors.append("Species-linked items")
    if by_kind.get("material_family"):
        ref = str(by_kind["material_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Crafting or exchange material", ref, 0.6, 0.74, "family"))
        candidates.append(_candidate("Collectible crafting item", ref, 0.56, 0.7, "family"))
        descriptors.append("Crafting materials")
    if by_kind.get("collectible_exchange"):
        ref = str(by_kind["collectible_exchange"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Tradable exchange item", ref, 0.66, 0.8, "family"))
        candidates.append(_candidate("Exchangeable collectible", ref, 0.62, 0.78, "family"))
        cryptic.append("exchange item")
    if by_kind.get("ore_family"):
        ref = str(by_kind["ore_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Valuable exchange ore", ref, 0.68, 0.82, "family"))
        candidates.append(_candidate("Tradable ore item", ref, 0.62, 0.78, "family"))
        cryptic.append("valuable ore")
    if by_kind.get("key_family"):
        ref = str(by_kind["key_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Story or event key item", ref, 0.62, 0.76, "family"))
        candidates.append(_candidate("Unlocking key item", ref, 0.58, 0.72, "family"))
        descriptors.append("Key items")
    if by_kind.get("unlock_item"):
        ref = str(by_kind["unlock_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Unlocks progression content", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate("Progress-gating key item", ref, 0.64, 0.8, "effect"))
        cryptic.append("unlocking item")
    if by_kind.get("event_gate_item"):
        ref = str(by_kind["event_gate_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Event-only distribution item", ref, 0.7, 0.84, "effect"))
        candidates.append(_candidate("Limited event key item", ref, 0.64, 0.8, "effect"))
        cryptic.append("event item")
    if by_kind.get("trial_collection"):
        ref = str(by_kind["trial_collection"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("One of seven trial finds", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate("Mina's trial collectible", ref, 0.74, 0.86, "effect"))
    if by_kind.get("rainbow_flower_piece"):
        ref = str(by_kind["rainbow_flower_piece"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Part of the Rainbow Flower", ref, 0.82, 0.92, "effect"))
        candidates.append(_candidate("Needed for Mina's Rainbow Flower", ref, 0.78, 0.9, "effect"))
    if by_kind.get("trial_giver"):
        fact = by_kind["trial_giver"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        giver = str(fact.get("giver") or "a trial captain")
        candidates.append(_candidate(f"Gift from {giver} during Mina's trial", ref, 0.76, 0.9, "effect"))
    if by_kind.get("opens_target"):
        fact = by_kind["opens_target"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        target = str(fact.get("target") or "")
        if target:
            candidates.append(_candidate(f"Opens {target}", ref, 0.78, 0.9, "effect"))
            candidates.append(_candidate(f"Key for {target}", ref, 0.7, 0.84, "effect"))
    for fact in by_kind.get("item_category", []):
        category = str(fact.get("category") or fact.get("text") or "").lower()
        ref = str(fact.get("evidence_ref") or "lead")
        if category == "nature mints":
            candidates.append(_candidate("Nature-changing mint", ref, 0.7, 0.8, "family"))
            candidates.append(_candidate("Stat-nature mint", ref, 0.64, 0.76, "family"))
            candidates.append(_candidate("Mint that changes natures", ref, 0.6, 0.74, "family"))
        elif category == "event items":
            candidates.append(_candidate("Event-only key item", ref, 0.68, 0.78, "family"))
            candidates.append(_candidate("Mythic event item", ref, 0.62, 0.74, "family"))
        elif category == "plot advancement":
            candidates.append(_candidate("Story-progress key item", ref, 0.62, 0.74, "family"))
            candidates.append(_candidate("Plot-critical key", ref, 0.58, 0.72, "family"))
        elif category == "loot":
            candidates.append(_candidate("Valuable sellable loot", ref, 0.64, 0.74, "family"))
            candidates.append(_candidate("Vendor treasure", ref, 0.58, 0.7, "family"))
        elif category == "collectibles":
            candidates.append(_candidate("Tradable collectible", ref, 0.56, 0.68, "family"))
            candidates.append(_candidate("Collectible item", ref, 0.48, 0.64, "family"))
        elif category == "status cures item":
            candidates.append(_candidate("Status-curing medicine", ref, 0.62, 0.76, "family"))
            candidates.append(_candidate("Battle status remedy", ref, 0.56, 0.72, "family"))
        elif category == "species-specific item":
            candidates.append(_candidate("Species-specific item", ref, 0.56, 0.7, "family"))
            candidates.append(_candidate("Signature held item", ref, 0.58, 0.72, "family"))
        elif category == "in a pinch":
            candidates.append(_candidate("Low-HP held berry", ref, 0.62, 0.76, "family"))
            candidates.append(_candidate("Pinch-activated berry", ref, 0.58, 0.74, "family"))
    if by_kind.get("candies_family"):
        ref = str(by_kind["candies_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Species candy item", ref, 0.5, 0.68, "family"))
        candidates.append(_candidate("Pokemon candy", ref, 0.48, 0.66, "family"))
        candidates.append(_candidate("Candy named for a species", ref, 0.46, 0.66, "family"))
        cryptic.extend(["species candy", "pokemon candy"])
        descriptors.append("Species candies")
    if by_kind.get("species_candy_boost"):
        ref = str(by_kind["species_candy_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Packed-energy stat booster", ref, 0.74, 0.84, "effect"))
        candidates.append(_candidate("All-stats boosting sweet", ref, 0.72, 0.82, "effect"))
        candidates.append(_candidate("Specific-species stat treat", ref, 0.68, 0.8, "effect"))
    if by_kind.get("mail_family"):
        ref = str(by_kind["mail_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Mail stationery", ref, 0.58, 0.7, "family"))
        candidates.append(_candidate("Message-holding stationery", ref, 0.54, 0.72, "family"))
        candidates.append(_candidate("Trainer letter paper", ref, 0.48, 0.68, "family"))
        cryptic.extend(["trainer mail", "stationery item"])
        descriptors.append("Mail items")
    if by_kind.get("ball_family"):
        ref = str(by_kind["ball_family"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Special Poke Ball", ref, 0.52, 0.68, "family"))
        candidates.append(_candidate("Special capture ball", ref, 0.5, 0.66, "family"))
        cryptic.append("special ball")
        descriptors.append("Special Poke Balls")
    if by_kind.get("crafted_item"):
        fact = by_kind["crafted_item"][0]
        crafted_item = str(fact.get("crafted_item") or "special gear")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"{crafted_item} ingredient", ref, 0.76, 0.9, "effect"))
    if by_kind.get("dream_world_capture"):
        ref = str(by_kind["dream_world_capture"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Otherworld catcher", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Dream World catcher", ref, 0.8, 0.9, "effect"))
    if by_kind.get("airborne_capture_tool"):
        ref = str(by_kind["airborne_capture_tool"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Long-range catcher for flying targets", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Catcher for high-flying targets", ref, 0.78, 0.88, "effect"))
    if by_kind.get("stealth_capture_tool"):
        ref = str(by_kind["stealth_capture_tool"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Best on unwary targets", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate("Stealth capture tool", ref, 0.72, 0.84, "effect"))
    if by_kind.get("guaranteed_capture"):
        ref = str(by_kind["guaranteed_capture"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Never-fails capture tool", ref, 0.8, 0.9, "effect"))
    if by_kind.get("pal_park_capture"):
        ref = str(by_kind["pal_park_capture"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Never-fails catcher in Pal Park", ref, 0.8, 0.9, "effect"))
    if by_kind.get("safari_capture"):
        ref = str(by_kind["safari_capture"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Safari Zone catcher", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Great Marsh capture tool", ref, 0.72, 0.86, "effect"))
    if by_kind.get("hisui_capture_tool"):
        ref = str(by_kind["hisui_capture_tool"][0].get("evidence_ref") or "title")
        candidates.append(_candidate("Hisui capture tool", ref, 0.68, 0.76, "family"))
        candidates.append(_candidate("Legends Arceus catcher", ref, 0.66, 0.74, "family"))
    if by_kind.get("contest_ball"):
        ref = str(by_kind["contest_ball"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Bug-Catching Contest ball", ref, 0.76, 0.9, "family"))
        candidates.append(_candidate("National Park contest ball", ref, 0.72, 0.88, "family"))
        cryptic.append("contest ball")
    if by_kind.get("mega_stone"):
        ref = str(by_kind["mega_stone"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Mega Evolution stone", ref, 0.72, 0.84, "family"))
        candidates.append(_candidate("Held Mega stone", ref, 0.66, 0.8, "family"))
        candidates.append(_candidate("Mega trigger stone", ref, 0.62, 0.76, "family"))
        cryptic.append("mega stone")
        descriptors.append("Mega Evolution stones")
    if by_kind.get("mega_target"):
        fact = by_kind["mega_target"][0]
        target = str(fact.get("mega_target") or "Mega form")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"{target} Mega stone", ref, 0.68, 0.9, "target"))
        candidates.append(_candidate(f"Held stone for {target}", ref, 0.62, 0.86, "target"))
        cryptic.append(f"{target.lower()} stone")
    if by_kind.get("evolution_item"):
        ref = str(by_kind["evolution_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Evolution item", ref, 0.5, 0.76, "family"))
        candidates.append(_candidate("Evolution-trigger item", ref, 0.54, 0.8, "family"))
        cryptic.append("evolution item")
        descriptors.append("Evolution items")
    if by_kind.get("specific_evolution_item"):
        fact = by_kind["specific_evolution_item"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        evolves_from = str(fact.get("evolves_from") or "a Pokemon")
        evolves_to = str(fact.get("evolves_to") or "an evolution")
        candidates.append(_candidate(f"Evolves {evolves_from} into {evolves_to}", ref, 0.8, 0.92, "effect"))
        candidates.append(_candidate(f"{evolves_from} evolution item", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate(f"Held item for {evolves_to}", ref, 0.68, 0.82, "effect"))
        cryptic.extend([f"{evolves_from.lower()} evolution", f"{evolves_to.lower()} item"])
    if by_kind.get("spin_evolution"):
        ref = str(by_kind["spin_evolution"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Requires a spin while held", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Spin-to-evolve held item", ref, 0.7, 0.82, "effect"))
    if by_kind.get("sweet_shape"):
        ref = str(by_kind["sweet_shape"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Berry-shaped sweet", ref, 0.72, 0.82, "theme"))
    if by_kind.get("secondary_effect_block"):
        ref = str(by_kind["secondary_effect_block"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Blocks extra move effects", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Ignores secondary effects", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Fake Out flinch blocker", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["secondary-effect shield", "covert protection"])
    if by_kind.get("weather_extension"):
        fact = by_kind["weather_extension"][0]
        weather = str(fact.get("weather") or "weather")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Extends {weather.lower()}", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate(f"{weather} lengthener", ref, 0.72, 0.84, "effect"))
        cryptic.append(f"{weather.lower()} extender")
    if by_kind.get("switch_out_on_hit"):
        ref = str(by_kind["switch_out_on_hit"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Switches the holder out after a hit", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Hit-triggered pivot item", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["pivot button", "forced switch item"])
    if by_kind.get("switch_out_on_stat_drop"):
        ref = str(by_kind["switch_out_on_stat_drop"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Switches out after stat drops", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Stat-drop escape item", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["escape pack", "stat-drop pivot"])
    if by_kind.get("evasion_item"):
        ref = str(by_kind["evasion_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Makes the holder harder to hit", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Evasiveness-boosting held item", ref, 0.7, 0.82, "effect"))
        cryptic.append("evasion item")
    if by_kind.get("fusion_item"):
        ref = str(by_kind["fusion_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Used for Kyurem fusion", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Reshiram/Zekrom fusion item", ref, 0.74, 0.86, "effect"))
        cryptic.append("fusion item")
    if by_kind.get("triggered_stat_boost"):
        fact = by_kind["triggered_stat_boost"][0]
        stat = _pretty_stat(str(fact.get("stat") or "a stat"))
        trigger = str(fact.get("trigger") or "a trigger")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Boosts {stat} after {trigger}", ref, 0.72, 0.88, "effect"))
        candidates.append(_candidate(f"{stat} boost on trigger", ref, 0.62, 0.8, "effect"))
        cryptic.append(f"{stat.lower()} booster")
    if by_kind.get("passive_stat_boost"):
        fact = by_kind["passive_stat_boost"][0]
        stat = _pretty_stat(str(fact.get("stat") or "a stat"))
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Raises {stat}", ref, 0.62, 0.82, "effect"))
        cryptic.append(f"{stat.lower()} booster")
    if by_kind.get("status_move_restriction"):
        ref = str(by_kind["status_move_restriction"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Forbids status moves", ref, 0.74, 0.88, "restriction"))
        candidates.append(_candidate("No-status-move held item", ref, 0.66, 0.82, "restriction"))
    if by_kind.get("type_immunity_item"):
        fact = by_kind["type_immunity_item"][0]
        immune_type = str(fact.get("immune_type") or "typed")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Blocks {immune_type}-type moves", ref, 0.74, 0.88, "effect"))
        candidates.append(_candidate(f"{immune_type}-immunity held item", ref, 0.68, 0.84, "effect"))
    if by_kind.get("airborne_item"):
        ref = str(by_kind["airborne_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Makes the holder float", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate("Ungrounding held item", ref, 0.7, 0.82, "effect"))
        cryptic.append("floating item")
    if by_kind.get("breaks_on_hit"):
        ref = str(by_kind["breaks_on_hit"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Pops after taking a hit", ref, 0.72, 0.8, "restriction"))
        cryptic.append("breakable held item")
    if by_kind.get("ultra_beast_ball"):
        ref = str(by_kind["ultra_beast_ball"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Best used on Ultra Beasts", ref, 0.8, 0.9, "target"))
        candidates.append(_candidate("Ultra Beast capture ball", ref, 0.76, 0.9, "target"))
        cryptic.append("Ultra Beast ball")
    if by_kind.get("niche_capture"):
        ref = str(by_kind["niche_capture"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Poor on most other targets", ref, 0.68, 0.82, "restriction"))
    if by_kind.get("transport_item"):
        ref = str(by_kind["transport_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Two-wheeled travel item", ref, 0.66, 0.78, "utility"))
        candidates.append(_candidate("Ride for quick travel", ref, 0.6, 0.74, "utility"))
        cryptic.append("travel gear")
    if by_kind.get("fast_travel"):
        ref = str(by_kind["fast_travel"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Speeds up travel", ref, 0.58, 0.76, "utility"))
    if by_kind.get("miracle_shooter"):
        ref = str(by_kind["miracle_shooter"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Miracle Shooter item", ref, 0.56, 0.74, "family"))
        candidates.append(_candidate("Wonder Launcher item", ref, 0.52, 0.72, "family"))
        candidates.append(_candidate("Launcher-only battle item", ref, 0.5, 0.7, "family"))
        descriptors.append("Miracle Shooter items")
    if by_kind.get("friendly_ability_trigger"):
        ref = str(by_kind["friendly_ability_trigger"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Forcibly triggers an ally's Ability", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Ally Ability activator", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate("Friendly Ability trigger item", ref, 0.64, 0.8, "effect"))
        cryptic.append("ally ability trigger")
    if by_kind.get("money_double"):
        ref = str(by_kind["money_double"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Doubles prize money", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate("Battle-payout doubler", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate("Money-boosting held item", ref, 0.66, 0.78, "effect"))
        cryptic.append("money doubler")
    if by_kind.get("sleep_cure"):
        ref = str(by_kind["sleep_cure"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Wakes a sleeping Pokemon", ref, 0.74, 0.84, "effect"))
        candidates.append(_candidate("Sleep remedy", ref, 0.7, 0.8, "effect"))
        candidates.append(_candidate("Sleep-curing item", ref, 0.66, 0.8, "effect"))
        cryptic.append("sleep cure")
    if by_kind.get("crit_boost_item"):
        ref = str(by_kind["crit_boost_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Critical-hit booster", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Raises crit odds in battle", ref, 0.72, 0.84, "effect"))
    if by_kind.get("flat_hp_restore"):
        fact = by_kind["flat_hp_restore"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        hp = int(fact.get("hp") or 0)
        if hp:
            candidates.append(_candidate(f"Restores {hp} HP", ref, 0.72, 0.84, "effect"))
            candidates.append(_candidate(f"{hp}-HP restorative", ref, 0.68, 0.82, "effect"))
    if by_kind.get("typed_move_boost_item"):
        fact = by_kind["typed_move_boost_item"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        move_type = str(fact.get("move_type") or "typed")
        one_use = bool(fact.get("one_use"))
        if one_use:
            candidates.append(_candidate(f"Boosts the first {move_type}-type move", ref, 0.82, 0.9, "effect"))
            candidates.append(_candidate(f"One-use {move_type} booster", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate(f"{move_type}-move booster", ref, 0.72, 0.84, "effect"))
        cryptic.append(f"{move_type.lower()} booster")
    if by_kind.get("accuracy_drop_item"):
        ref = str(by_kind["accuracy_drop_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Lowers the foe's accuracy", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Accuracy-cutting held item", ref, 0.72, 0.84, "effect"))
        cryptic.append("accuracy reducer")
    if by_kind.get("choice_lock_item"):
        fact = by_kind["choice_lock_item"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        stat = _compact_stat(str(fact.get("stat") or "a stat"))
        candidates.append(_candidate(f"Boosts {stat} but locks one move", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate(f"{stat}-boosting Choice item", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Single-move-locking held item", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["choice item", "move-locking gear"])
    if by_kind.get("wild_encounter_reduce"):
        ref = str(by_kind["wild_encounter_reduce"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Repels wild Pokemon", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Cuts wild encounter rate", ref, 0.74, 0.86, "effect"))
        cryptic.append("encounter repellent")
    if by_kind.get("status_cure_all"):
        ref = str(by_kind["status_cure_all"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Cures all major status conditions", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Full status remedy", ref, 0.74, 0.86, "effect"))
        if by_kind.get("status_cure_confusion"):
            candidates.append(_candidate("Also cures confusion", ref, 0.7, 0.84, "effect"))
        cryptic.append("status panacea")
    if by_kind.get("item_stat_drop_protection"):
        ref = str(by_kind["item_stat_drop_protection"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Prevents the holder's stats from being lowered", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Blocks enemy stat drops", ref, 0.74, 0.86, "effect"))
        cryptic.append("stat-drop shield")
    if by_kind.get("infatuation_share_item"):
        ref = str(by_kind["infatuation_share_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Passes infatuation back", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Shares attraction with the infatuator", ref, 0.74, 0.86, "effect"))
        cryptic.append("love-link item")
    if by_kind.get("breeding_iv_item"):
        ref = str(by_kind["breeding_iv_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Passes down five IVs in breeding", ref, 0.84, 0.92, "effect"))
        candidates.append(_candidate("Breeding IV-transfer item", ref, 0.74, 0.86, "effect"))
        cryptic.append("breeding item")
    if by_kind.get("fossil_revival"):
        fact = by_kind["fossil_revival"][0]
        revived = str(fact.get("revived_species") or "a fossil Pokemon")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Revives into {revived}", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Fossil revival item", ref, 0.68, 0.82, "family"))
        candidates.append(_candidate("Prehistoric revival item", ref, 0.64, 0.78, "family"))
        generation_rows = by_kind.get("item_generation") or []
        if generation_rows:
            generation = str(generation_rows[0].get("generation") or generation_rows[0].get("text") or "")
            if generation:
                candidates.append(_candidate(f"{generation} relic for {revived}", ref, 0.72, 0.86, "family"))
        cryptic.append("fossil item")
    if by_kind.get("species_stat_boost"):
        fact = by_kind["species_stat_boost"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        holder = str(fact.get("holder_species") or "a species")
        stats = [_compact_stat(str(value)) for value in list(fact.get("boost_stats") or []) if str(value).strip()]
        if stats:
            candidates.append(_candidate(f"{holder} { '/'.join(stats) } boost item", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate(f"Power item for {holder}", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate(f"{holder}-only held item", ref, 0.72, 0.84, "effect"))
        cryptic.append(f"{holder.lower()} item")
    if by_kind.get("species_type_boost"):
        fact = by_kind["species_type_boost"][0]
        holder = str(fact.get("holder_species") or "a legendary")
        types = list(fact.get("boost_types") or [])
        ref = str(fact.get("evidence_ref") or "lead")
        if types:
            candidates.append(_candidate(f"Boosts {'/'.join(types)} moves for {holder}", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("Species-specific power orb", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate(f"Signature orb for {holder}", ref, 0.7, 0.84, "effect"))
        cryptic.append("signature orb")
    if by_kind.get("drain_heal_boost"):
        ref = str(by_kind["drain_heal_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Boosts recovery from draining moves", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Drain-healing boost item", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate("Increases Ingrain and Aqua Ring recovery", ref, 0.62, 0.8, "effect"))
        cryptic.append("recovery booster")
    if by_kind.get("trapping_move_boost"):
        ref = str(by_kind["trapping_move_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Boosts trapping-move damage", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Held item for binding damage", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate("Strengthens multi-turn traps", ref, 0.64, 0.8, "effect"))
        cryptic.append("trap booster")
    if by_kind.get("trainer_cosmetic"):
        ref = str(by_kind["trainer_cosmetic"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Lipstick-changing bag", ref, 0.82, 0.9, "utility"))
        candidates.append(_candidate("Trainer cosmetic case", ref, 0.7, 0.8, "utility"))
        cryptic.append("cosmetic bag")
        descriptors.append("Trainer cosmetic items")
    if by_kind.get("soil_dry_time"):
        fact = by_kind["soil_dry_time"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        hours = int(fact.get("hours") or 0)
        if hours:
            candidates.append(_candidate(f"Dries soil in {hours} hours", ref, 0.78, 0.88, "effect"))
    if by_kind.get("berry_yield_boost"):
        fact = by_kind["berry_yield_boost"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        added_berries = int(fact.get("added_berries") or 0)
        if added_berries:
            candidates.append(_candidate(f"Adds {added_berries} more berries", ref, 0.74, 0.86, "effect"))
    if by_kind.get("berry_mutation_boost"):
        ref = str(by_kind["berry_mutation_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Raises berry mutation odds", ref, 0.74, 0.86, "effect"))
    if by_kind.get("berry_regrow_boost"):
        ref = str(by_kind["berry_regrow_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Keeps dead berry plants productive", ref, 0.76, 0.88, "effect"))
    if by_kind.get("berry_growth_speed"):
        ref = str(by_kind["berry_growth_speed"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Speeds berry growth", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Quickens berry ripening", ref, 0.7, 0.84, "effect"))
    if by_kind.get("berry_retention"):
        ref = str(by_kind["berry_retention"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Keeps berries on the plant longer", ref, 0.74, 0.86, "effect"))
    if by_kind.get("neutral_mint_profile"):
        ref = str(by_kind["neutral_mint_profile"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Even-stat nature changer", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Makes every stat grow evenly", ref, 0.72, 0.86, "effect"))
    if by_kind.get("camp_meal_pack"):
        ref = str(by_kind["camp_meal_pack"][0].get("evidence_ref") or "title")
        candidates.append(_candidate("Camping meal packet", ref, 0.7, 0.8, "utility"))
    if by_kind.get("picnic_kit"):
        ref = str(by_kind["picnic_kit"][0].get("evidence_ref") or "title")
        candidates.append(_candidate("Outdoor meal kit", ref, 0.74, 0.84, "utility"))
    if by_kind.get("utility_item"):
        ref = str(by_kind["utility_item"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Adventure utility item", ref, 0.4, 0.58, "utility"))

    for fact in by_kind.get("held_item", []):
        candidates.append(_candidate("Held battle item", str(fact.get("evidence_ref") or "lead"), 0.46, 0.68, "category"))
        descriptors.append("Held battle items")
    for fact in by_kind.get("item_generation", []):
        generation = str(fact.get("generation") or "")
        if generation:
            descriptors.append(f"{generation} items")
    if not candidates:
        return _generic_payload(facts, "item")

    fact_nuggets = [
        {
            "text": str(fact["text"]),
            "evidence_ref": str(fact["evidence_ref"]),
            "specificity": float(fact["specificity"]),
        }
        for fact in facts[:12]
    ]
    return {
        "fact_nuggets": fact_nuggets,
        "crossword_candidates": candidates[:12],
        "cryptic_definition_seeds": _unique_strings(cryptic or ["battle item"], 4),
        "connections_descriptors": _unique_strings(descriptors or ["Battle items"], 6),
        "risk_flags": _unique_strings(risk_flags, 4),
        "confidence": 0.78,
    }


def _location_payload(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = _fact_map(facts)
    candidates: list[dict[str, Any]] = []
    cryptic: list[str] = []
    descriptors: list[str] = []
    location_kind = by_kind.get("location_kind", [])

    if by_kind.get("shipwreck"):
        ref = str(by_kind["shipwreck"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Hoenn shipwreck", ref, 0.82, 0.88, "theme"))
        cryptic.append("wrecked ship")
        descriptors.append("Shipwreck locations")
    if by_kind.get("route_location"):
        fact = by_kind["route_location"][0]
        route = str(fact.get("route") or "")
        ref = str(fact.get("evidence_ref") or "lead")
        if route and by_kind.get("shipwreck") and by_kind.get("region"):
            region = str(by_kind["region"][0].get("region") or "")
            candidates.append(_candidate(f"{route} wreck in {region}", ref, 0.74, 0.86, "taxonomy"))
            descriptors.append(f"{region} route locations")
        elif route and by_kind.get("tower_site"):
            candidates.append(_candidate(f"{route} tower", ref, 0.72, 0.86, "taxonomy"))
        elif route and by_kind.get("beach_house"):
            candidates.append(_candidate(f"{route} beach house", ref, 0.74, 0.88, "taxonomy"))
        elif route:
            candidates.append(_candidate(f"Site on {route}", ref, 0.54, 0.72, "taxonomy"))
    if by_kind.get("battle_facility"):
        fact = by_kind["battle_facility"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        facility_name = str(fact.get("facility_name") or "").strip()
        if facility_name:
            candidates.append(_candidate(f"Battle Frontier's {facility_name}", ref, 0.78, 0.9, "theme"))
            candidates.append(_candidate(f"Gen IV battle {facility_name.lower()}", ref, 0.72, 0.84, "theme"))
        candidates.append(_candidate("Battle Frontier facility", ref, 0.74, 0.88, "theme"))
        cryptic.append("battle facility")
        descriptors.append("Battle Frontier facilities")
    if by_kind.get("frontier_corner"):
        fact = by_kind["frontier_corner"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        corner = str(fact.get("corner") or "").strip()
        if corner:
            candidates.append(_candidate(f"{corner} Battle Frontier site", ref, 0.76, 0.9, "theme"))
    if by_kind.get("regional_wonder"):
        ref = str(by_kind["regional_wonder"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("One of Kitakami's Six Wonders", ref, 0.82, 0.92, "theme"))
        candidates.append(_candidate("Kitakami wonder site", ref, 0.72, 0.84, "theme"))
        cryptic.append("regional wonder")
        descriptors.append("Kitakami wonders")
    if by_kind.get("orchard_site"):
        ref = str(by_kind["orchard_site"][0].get("evidence_ref") or "lead")
        if by_kind.get("region"):
            region = str(by_kind["region"][0].get("region") or "").title()
            candidates.append(_candidate(f"{region} apple orchard", ref, 0.8, 0.9, "theme"))
        candidates.append(_candidate("Large apple orchard", ref, 0.74, 0.86, "theme"))
        cryptic.append("apple orchard")
        descriptors.append("Orchard locations")
    if by_kind.get("summit_pool"):
        fact = by_kind["summit_pool"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        summit = str(fact.get("summit") or "").strip()
        if summit:
            candidates.append(_candidate(f"Pool atop {summit}", ref, 0.82, 0.9, "theme"))
        candidates.append(_candidate("Mountain-summit pool", ref, 0.72, 0.84, "theme"))
        cryptic.append("summit pool")
    if by_kind.get("subregion_site"):
        fact = by_kind["subregion_site"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        area = str(fact.get("area") or "").strip()
        if area:
            candidates.append(_candidate(f"Located in {area}", ref, 0.68, 0.82, "theme"))
    if by_kind.get("battle_venue"):
        ref = str(by_kind["battle_venue"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Battle venue in the Survival Area", ref, 0.82, 0.9, "theme"))
        candidates.append(_candidate("Buck's battle spot", ref, 0.72, 0.84, "theme"))
        cryptic.append("battle venue")
    if by_kind.get("wild_area_zone"):
        ref = str(by_kind["wild_area_zone"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Part of the Wild Area", ref, 0.76, 0.86, "theme"))
        candidates.append(_candidate("Wild Area zone", ref, 0.7, 0.82, "theme"))
        cryptic.append("wild area site")
    if by_kind.get("large_lake"):
        ref = str(by_kind["large_lake"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Large regional lake", ref, 0.74, 0.84, "theme"))
        cryptic.append("large lake")
    if by_kind.get("contains_subarea"):
        fact = by_kind["contains_subarea"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        subarea = str(fact.get("subarea") or "").strip()
        if subarea:
            candidates.append(_candidate(f"Contains {subarea}", ref, 0.78, 0.88, "theme"))
    if by_kind.get("dynamax_tree"):
        ref = str(by_kind["dynamax_tree"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Site of the Dyna Tree", ref, 0.82, 0.9, "theme"))
        candidates.append(_candidate("Hill with a giant Dynamax tree", ref, 0.74, 0.86, "theme"))
        cryptic.append("dynamax tree site")
    if by_kind.get("dna_splicers_site"):
        ref = str(by_kind["dna_splicers_site"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Hidden location of the DNA Splicers", ref, 0.82, 0.9, "theme"))
        candidates.append(_candidate("Kyurem fusion item hideout", ref, 0.74, 0.86, "theme"))
        cryptic.append("fusion-item hideout")
    if by_kind.get("hisui_subregion_site"):
        fact = by_kind["hisui_subregion_site"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        area = str(fact.get("area") or "").strip()
        if area:
            candidates.append(_candidate(f"{area} area", ref, 0.74, 0.84, "theme"))
    if by_kind.get("mountain_site"):
        fact = by_kind["mountain_site"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        mountain = str(fact.get("mountain") or "").strip()
        if mountain:
            candidates.append(_candidate(f"Site on {mountain}", ref, 0.78, 0.88, "theme"))
    if by_kind.get("contest_venue"):
        ref = str(by_kind["contest_venue"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Building where Pokemon Contests are held", ref, 0.8, 0.9, "theme"))
        candidates.append(_candidate("Pokemon Contest venue", ref, 0.74, 0.86, "theme"))
        cryptic.append("contest venue")
    if by_kind.get("contest_workplace"):
        ref = str(by_kind["contest_workplace"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Workplace of Contest judges", ref, 0.76, 0.86, "theme"))
    if by_kind.get("legendary_rest"):
        ref = str(by_kind["legendary_rest"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Tower where weather legends rest", ref, 0.8, 0.92, "theme"))
        candidates.append(_candidate("Resting place of Groudon, Kyogre, and Rayquaza", ref, 0.74, 0.94, "theme"))
        cryptic.append("legendary resting place")
        descriptors.append("Legendary resting places")
    if by_kind.get("beach_house"):
        ref = str(by_kind["beach_house"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Beach house landmark", ref, 0.64, 0.82, "theme"))
        cryptic.append("beach house")
        descriptors.append("Beach houses")
    if by_kind.get("ribbon_reward"):
        ref = str(by_kind["ribbon_reward"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Home of the Footprint Ribbon", ref, 0.78, 0.92, "reward"))
        candidates.append(_candidate("Footprint Ribbon house", ref, 0.7, 0.88, "reward"))
        cryptic.append("ribbon house")
    if by_kind.get("friendship_reward"):
        ref = str(by_kind["friendship_reward"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Ribbon house for friendly Pokemon", ref, 0.7, 0.84, "reward"))
        cryptic.append("friendship ribbon house")
    if by_kind.get("dive_access"):
        candidates.append(_candidate("Partly reached by Dive", str(by_kind["dive_access"][0].get("evidence_ref") or "lead"), 0.76, 0.82, "access"))
        cryptic.append("Dive-access site")
        candidates.append(_candidate("Dive-only landmark", str(by_kind["dive_access"][0].get("evidence_ref") or "lead"), 0.68, 0.76, "access"))
    if by_kind.get("contains_scanner"):
        candidates.append(_candidate("Hides the Scanner", str(by_kind["contains_scanner"][0].get("evidence_ref") or "lead"), 0.8, 0.84, "treasure"))
        cryptic.append("scanner hideout")
    if by_kind.get("replaced_site"):
        candidates.append(
            _candidate(
                "Supplanted by Sea Mauville",
                str(by_kind["replaced_site"][0].get("evidence_ref") or "lead"),
                0.66,
                0.78,
                "version",
            )
        )
    if by_kind.get("sunken_ruins"):
        ref = str(by_kind["sunken_ruins"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Sunken temple ruins", ref, 0.82, 0.9, "theme"))
        candidates.append(_candidate("Dive-access ruins", ref, 0.78, 0.84, "theme"))
        cryptic.append("sunken ruins")
        descriptors.append("Sunken ruins")
    elif by_kind.get("ruins"):
        ref = str(by_kind["ruins"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Ancient regional ruins", ref, 0.64, 0.72, "theme"))
        cryptic.append("ancient ruins")
        descriptors.append("Ruins")
    for fact in by_kind.get("region", []):
        region = str(fact.get("region") or "").title()
        if region:
            candidates.append(_candidate(f"{region} landmark", str(fact.get("evidence_ref") or "lead"), 0.38, 0.5, "taxonomy"))
            descriptors.append(f"{region} landmarks")
    if by_kind.get("bay_site"):
        candidates.append(_candidate("Bay-side landmark", str(by_kind["bay_site"][0].get("evidence_ref") or "lead"), 0.56, 0.64, "theme"))
    if location_kind and by_kind.get("region"):
        kind = str(location_kind[0].get("location_kind") or "landmark")
        region = str(by_kind["region"][0].get("region") or "").title()
        ref = str(location_kind[0].get("evidence_ref") or "lead")
        if kind == "gate":
            candidates.append(_candidate(f"{region} route connector", ref, 0.64, 0.8, "taxonomy"))
            candidates.append(_candidate(f"Connector gate in {region}", ref, 0.62, 0.78, "taxonomy"))
        if kind == "meadow":
            candidates.append(_candidate(f"{region} meadow", ref, 0.62, 0.78, "taxonomy"))
        if kind == "plaza":
            candidates.append(_candidate(f"{region} plaza", ref, 0.62, 0.78, "taxonomy"))
        if kind == "biome":
            candidates.append(_candidate(f"{region} biome", ref, 0.64, 0.8, "taxonomy"))
        if kind == "pool":
            candidates.append(_candidate(f"{region} pool landmark", ref, 0.64, 0.8, "taxonomy"))
        if kind == "pass":
            candidates.append(_candidate(f"{region} mountain pass", ref, 0.66, 0.82, "taxonomy"))
        candidates.append(_candidate(f"{region} {kind}", ref, 0.52, 0.7, "taxonomy"))
        candidates.append(_candidate(f"Regional {kind}", ref, 0.44, 0.62, "taxonomy"))
        candidates.append(_candidate(f"{kind.title()} in {region}", ref, 0.42, 0.66, "taxonomy"))
        descriptors.append(f"{region} {kind}s")
    if by_kind.get("roaming_zone"):
        ref = str(by_kind["roaming_zone"][0].get("evidence_ref") or "title")
        candidates.append(_candidate("Regional roaming area", ref, 0.66, 0.78, "taxonomy"))
        candidates.append(_candidate("Wandering regional location", ref, 0.62, 0.76, "taxonomy"))
    if by_kind.get("near_town"):
        candidates.append(_candidate("Town-side landmark", str(by_kind["near_town"][0].get("evidence_ref") or "lead"), 0.42, 0.58, "theme"))
    if by_kind.get("city_site"):
        candidates.append(_candidate("Urban landmark", str(by_kind["city_site"][0].get("evidence_ref") or "lead"), 0.42, 0.58, "theme"))
    if by_kind.get("island_site"):
        ref = str(by_kind["island_site"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Island location", ref, 0.46, 0.66, "theme"))
        descriptors.append("Island locations")

    if not candidates:
        return _generic_payload(facts, "location")

    fact_nuggets = [
        {
            "text": str(fact["text"]),
            "evidence_ref": str(fact["evidence_ref"]),
            "specificity": float(fact["specificity"]),
        }
        for fact in facts[:12]
    ]
    return {
        "fact_nuggets": fact_nuggets,
        "crossword_candidates": candidates[:12],
        "cryptic_definition_seeds": _unique_strings(cryptic or ["Pokemon location"], 4),
        "connections_descriptors": _unique_strings(descriptors or ["Pokemon locations"], 6),
        "risk_flags": [],
        "confidence": 0.77,
    }


def _ability_payload(facts: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = _fact_map(facts)
    candidates: list[dict[str, Any]] = []
    cryptic: list[str] = []
    descriptors: list[str] = []
    risk_flags: list[str] = []

    summaries = by_kind.get("effect_text", []) + [
        fact for fact in by_kind.get("ability_summary", []) if len(str(fact.get("effect") or fact.get("text") or "")) <= 180
    ]
    for fact in summaries[:2]:
        effect = str(fact.get("effect") or fact.get("text") or "")
        ref = str(fact.get("evidence_ref") or "lead")
        for label in _keyword_effect(effect):
            candidates.append(_candidate(f"{label} trait", ref, 0.56, 0.66, "effect"))
            descriptors.append(f"{label.title()} abilities")
            cryptic.append(f"{label} trait")
        lowered = effect.lower()
        if ("normal" in lowered and "flying" in lowered and "moves" in lowered and ("become" in lowered or "turn" in lowered)):
            candidates.append(_candidate("Turns Normal moves Flying", ref, 0.74, 0.88, "effect"))
            candidates.append(_candidate("Aerial move-converting trait", ref, 0.68, 0.8, "effect"))
            candidates.append(_candidate("Flying-boosting move trait", ref, 0.64, 0.76, "effect"))
            cryptic.append("move-converting trait")
            descriptors.append("Type-changing abilities")
        if "same-type attack bonus" in lowered or "same type as the pokemon" in lowered:
            candidates.append(_candidate("Boosts same-type attacks", ref, 0.7, 0.84, "effect"))
            candidates.append(_candidate("Stronger matching-move trait", ref, 0.66, 0.8, "effect"))
            candidates.append(_candidate("Enhanced STAB trait", ref, 0.58, 0.76, "effect"))
            cryptic.append("same-type booster")
            descriptors.append("Damage-boosting abilities")
        if "raise" in lowered and "power" in lowered:
            candidates.append(_candidate("Boosts move power after typing shift", ref, 0.68, 0.76, "effect"))
            risk_flags.append("effect_paraphrase")
    if by_kind.get("signature_holder"):
        fact = by_kind["signature_holder"][0]
        holder = str(fact.get("holder_species") or "").strip()
        ref = str(fact.get("evidence_ref") or "lead")
        if holder:
            candidates.append(_candidate(f"{holder}'s signature Ability", ref, 0.74, 0.88, "theme"))
    if by_kind.get("berry_consume_heal"):
        ref = str(by_kind["berry_consume_heal"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Restores HP after a Berry", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Berry-eating heal trait", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Heals when it consumes a Berry", ref, 0.76, 0.88, "effect"))
        cryptic.extend(["berry healer", "berry-fed recovery"])
        descriptors.append("Berry-healing abilities")
    if by_kind.get("explosion_block"):
        ref = str(by_kind["explosion_block"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Prevents Explosion and Self-Destruct", ref, 0.8, 0.92, "effect"))
        candidates.append(_candidate("Explosion-blocking trait", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Stops self-destructing moves", ref, 0.74, 0.88, "effect"))
        cryptic.extend(["explosion blocker", "blast stopper"])
        descriptors.append("Explosion-blocking abilities")
    if by_kind.get("hit_type_change"):
        ref = str(by_kind["hit_type_change"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Changes type when hit", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Becomes the attack's type", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Hit-triggered type shift", ref, 0.7, 0.82, "effect"))
        cryptic.extend(["type shift", "reactive typing"])
        descriptors.append("Type-shifting abilities")
    if by_kind.get("poison_any_type"):
        ref = str(by_kind["poison_any_type"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Lets poison affect Steel-types", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Poisons even Poison foes", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Bypasses poison immunity", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["poison immunity breaker", "toxin bypass"])
        descriptors.append("Poison-bypassing abilities")
    if by_kind.get("global_speed_drop_on_hit"):
        ref = str(by_kind["global_speed_drop_on_hit"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Drops everyone else's Speed when hit", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Hit-triggered Speed drop", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Slows the whole field after contact", ref, 0.7, 0.82, "effect"))
        cryptic.extend(["fieldwide slowdown", "speed-dropping fluff"])
        descriptors.append("Field-slowing abilities")
    if by_kind.get("berry_repeat"):
        ref = str(by_kind["berry_repeat"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Makes a Berry trigger twice", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Re-chews a Berry next turn", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Double-Berry trait", ref, 0.68, 0.82, "effect"))
        cryptic.extend(["double berry", "second chew"])
        descriptors.append("Berry-repeating abilities")
    if by_kind.get("field_type_aura"):
        fact = by_kind["field_type_aura"][0]
        move_type = str(fact.get("move_type") or "typed")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Boosts all {move_type}-type attacks", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate(f"Fieldwide {move_type} aura", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate(f"Empowers everyone's {move_type} moves", ref, 0.72, 0.84, "effect"))
        cryptic.extend([f"{move_type.lower()} aura", "fieldwide aura"])
        descriptors.append("Aura abilities")
    if by_kind.get("strong_winds"):
        ref = str(by_kind["strong_winds"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Summons strong winds", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Creates a unique weather state", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Weather of strong winds", ref, 0.68, 0.82, "effect"))
        cryptic.extend(["strong winds", "stormcaller"])
        descriptors.append("Weather-setting abilities")
    if by_kind.get("download_boost"):
        ref = str(by_kind["download_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Raises Attack or Sp. Atk on entry", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Reads the foe's weaker defense", ref, 0.74, 0.86, "effect"))
        candidates.append(_candidate("Entry boost based on enemy defenses", ref, 0.7, 0.84, "effect"))
        cryptic.extend(["defense reader", "adaptive entry boost"])
        descriptors.append("Entry-boosting abilities")
    if by_kind.get("rain_summon"):
        ref = str(by_kind["rain_summon"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Summons rain on entry", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Automatic rainmaker", ref, 0.74, 0.84, "effect"))
        candidates.append(_candidate("Rain Dance on switch-in", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["rainmaker", "entry rain"])
        descriptors.append("Rain abilities")
    if by_kind.get("typed_heal_immunity"):
        fact = by_kind["typed_heal_immunity"][0]
        move_type = str(fact.get("move_type") or "typed")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Heals from {move_type}-type moves", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate(f"{move_type}-immunity that restores HP", ref, 0.74, 0.88, "effect"))
        candidates.append(_candidate(f"Recovers when struck by {move_type}", ref, 0.7, 0.84, "effect"))
        cryptic.extend([f"{move_type.lower()} eater", f"{move_type.lower()} heal"])
        descriptors.append(f"{move_type} healing abilities")
    if by_kind.get("typed_immunity_power_up"):
        fact = by_kind["typed_immunity_power_up"][0]
        ref = str(fact.get("evidence_ref") or "lead")
        defense_type = str(fact.get("defense_type") or "typed")
        boost_type = str(fact.get("boost_type") or defense_type)
        candidates.append(_candidate(f"Absorbs {defense_type}-type moves", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate(f"Boosts {boost_type}-type moves after a {defense_type} hit", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate(f"{defense_type}-absorbing power-up trait", ref, 0.7, 0.84, "effect"))
        cryptic.extend([f"{defense_type.lower()} absorber", f"{boost_type.lower()} booster"])
        descriptors.append("Absorbing abilities")
    if by_kind.get("berry_restore"):
        ref = str(by_kind["berry_restore"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("May restore a used Berry", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Berry-regrowing trait", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["berry restore", "harvest trait"])
        descriptors.append("Berry-restoring abilities")
    if by_kind.get("rain_status_cure"):
        ref = str(by_kind["rain_status_cure"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Cures status in rain", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Rain-washing ailment trait", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["rain cure", "storm cleanse"])
        descriptors.append("Rain-linked abilities")
    if by_kind.get("ally_damage_reduce"):
        ref = str(by_kind["ally_damage_reduce"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Reduces damage taken by allies", ref, 0.8, 0.9, "effect"))
        candidates.append(_candidate("Protective ally-screen trait", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["ally guard", "teammate protector"])
        descriptors.append("Ally-protecting abilities")
    if by_kind.get("foe_item_reveal"):
        ref = str(by_kind["foe_item_reveal"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Reveals the foe's held item on entry", ref, 0.82, 0.9, "effect"))
        candidates.append(_candidate("Item-sniffing switch-in trait", ref, 0.72, 0.84, "effect"))
        cryptic.extend(["item reveal", "item sniffer"])
        descriptors.append("Scouting abilities")
    if by_kind.get("weight_double"):
        ref = str(by_kind["weight_double"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Doubles the user's weight", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Weight-doubling trait", ref, 0.72, 0.82, "effect"))
        cryptic.extend(["heavy body", "weight booster"])
        descriptors.append("Weight-changing abilities")
    if by_kind.get("sleep_halve"):
        ref = str(by_kind["sleep_halve"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Halves sleep duration", ref, 0.8, 0.88, "effect"))
        candidates.append(_candidate("Wakes up unusually fast", ref, 0.72, 0.82, "effect"))
        candidates.append(_candidate("Quick-waking trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["fast sleeper", "quick waking"])
        descriptors.append("Sleep-shortening abilities")
    if by_kind.get("sleep_punish"):
        ref = str(by_kind["sleep_punish"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Damages sleeping foes", ref, 0.78, 0.86, "effect"))
        candidates.append(_candidate("Nightmare-causing trait", ref, 0.7, 0.8, "effect"))
        candidates.append(_candidate("Sleep-punishing trait", ref, 0.68, 0.82, "effect"))
        cryptic.extend(["nightmare trait", "sleep punisher"])
        descriptors.append("Sleep-punishing abilities")
    if by_kind.get("faint_recoil"):
        ref = str(by_kind["faint_recoil"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Punishes a knockout blow", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate("Retaliates when knocked out", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Fainting backlash trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["ko backlash", "retaliatory trait"])
        descriptors.append("Fainting-retaliation abilities")
    if by_kind.get("contact_recoil"):
        ref = str(by_kind["contact_recoil"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Punishes contact attackers", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate("Damages foes on contact KO", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate("Contact-backlash trait", ref, 0.66, 0.78, "effect"))
        cryptic.extend(["contact backlash", "contact punisher"])
        descriptors.append("Contact-punishing abilities")
    if by_kind.get("crit_rage"):
        ref = str(by_kind["crit_rage"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Maxes Attack after a critical hit", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("Critical-hit rage trait", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Attack-spiking crit trait", ref, 0.68, 0.82, "effect"))
        cryptic.extend(["crit rage", "attack-spiking trait"])
        descriptors.append("Critical-hit abilities")
    if by_kind.get("crit_immunity"):
        ref = str(by_kind["crit_immunity"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Blocks critical hits", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate("Critical-hit proof trait", ref, 0.72, 0.82, "effect"))
        candidates.append(_candidate("No-crit armor trait", ref, 0.66, 0.78, "effect"))
        cryptic.extend(["crit shield", "crit-proof trait"])
        descriptors.append("Critical-hit-blocking abilities")
    if by_kind.get("stat_protection"):
        ref = str(by_kind["stat_protection"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Protects stats from drops", ref, 0.72, 0.82, "effect"))
        candidates.append(_candidate("Stat-drop blocking trait", ref, 0.66, 0.78, "effect"))
        candidates.append(_candidate("Keeps stats from falling", ref, 0.62, 0.74, "effect"))
        cryptic.append("stat-protecting trait")
        descriptors.append("Stat-protecting abilities")
    if by_kind.get("defense_protection"):
        ref = str(by_kind["defense_protection"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Protects Defense from drops", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate("Defense-drop blocking trait", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate("Keeps Defense from falling", ref, 0.66, 0.78, "effect"))
        cryptic.extend(["defense guard", "defense shield"])
        descriptors.append("Defense-protecting abilities")
    if by_kind.get("status_immunity") and not by_kind.get("commander_pair"):
        ref = str(by_kind["status_immunity"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Status-blocking trait", ref, 0.68, 0.78, "effect"))
        candidates.append(_candidate("Prevents major status ailments", ref, 0.62, 0.76, "effect"))
        candidates.append(_candidate("Ailment-proof trait", ref, 0.58, 0.72, "effect"))
        cryptic.append("status immunity")
        descriptors.append("Status-blocking abilities")
    if by_kind.get("weather_nullify"):
        ref = str(by_kind["weather_nullify"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Cancels weather effects", ref, 0.76, 0.9, "effect"))
        candidates.append(_candidate("Turns weather ineffective", ref, 0.72, 0.86, "effect"))
        candidates.append(_candidate("Weather-clearing trait", ref, 0.68, 0.82, "effect"))
        cryptic.extend(["weather nullifier", "storm stopper"])
        descriptors.append("Weather-canceling abilities")
    if by_kind.get("weather_hook") and not (by_kind.get("low_hp_stat_boost") or by_kind.get("low_hp_type_boost")):
        ref = str(by_kind["weather_hook"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Weather-linked trait", ref, 0.56, 0.66, "effect"))
        cryptic.append("weather trait")
        descriptors.append("Weather abilities")
    if by_kind.get("danger_sense"):
        ref = str(by_kind["danger_sense"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Warns of dangerous moves", ref, 0.72, 0.82, "effect"))
        candidates.append(_candidate("Move-sensing trait", ref, 0.62, 0.72, "effect"))
        candidates.append(_candidate("Alerts you to lethal threats", ref, 0.66, 0.78, "effect"))
        cryptic.append("danger sensor")
        descriptors.append("Predictive abilities")
    if by_kind.get("ally_special_boost"):
        ref = str(by_kind["ally_special_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Boosts allies' Special Attack", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate("Powers teammates' special moves", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Ally special-move booster", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["ally booster", "special support trait"])
        descriptors.append("Ally-boosting abilities")
    if by_kind.get("global_stat_lower"):
        fact = by_kind["global_stat_lower"][0]
        stat = _pretty_stat(str(fact.get("stat") or "a stat"))
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Lowers others' {stat}", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate(f"Global {stat} debuff", ref, 0.7, 0.84, "effect"))
        candidates.append(_candidate(f"Weakens every foe's {stat}", ref, 0.68, 0.82, "effect"))
        cryptic.extend([f"{stat.lower()} debuff", "global weakening trait"])
        descriptors.append("Field-lowering abilities")
    if by_kind.get("weather_speed_boost"):
        ref = str(by_kind["weather_speed_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Doubles Speed in sunlight", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Sun-boosted Speed trait", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate("Faster in harsh sunlight", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["sun speed", "sunlight booster"])
        descriptors.append("Sunlight abilities")
    if by_kind.get("late_move_boost"):
        ref = str(by_kind["late_move_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Boosts moves when acting last", ref, 0.76, 0.86, "effect"))
        candidates.append(_candidate("Stronger when it moves last", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate("Late-turn power boost", ref, 0.66, 0.78, "effect"))
        cryptic.extend(["slow-power trait", "late-move booster"])
        descriptors.append("Move-last abilities")
    if by_kind.get("ko_highest_stat_boost"):
        ref = str(by_kind["ko_highest_stat_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Raises its highest stat after a knockout", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("KO-triggered top-stat boost", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Knockout snowball trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["ko stat boost", "snowball trait"])
        descriptors.append("Knockout-boosting abilities")
    if by_kind.get("low_hp_type_boost"):
        fact = by_kind["low_hp_type_boost"][0]
        move_type = str(fact.get("move_type") or "typed")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Boosts {move_type}-type moves at low HP", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate(f"Low-HP {move_type} boost", ref, 0.68, 0.82, "effect"))
        candidates.append(_candidate(f"{move_type}-power when weakened", ref, 0.66, 0.8, "effect"))
        cryptic.extend([f"{move_type.lower()} boost", "low-hp power trait"])
        descriptors.append(f"Low-HP {move_type} abilities")
    if by_kind.get("low_hp_stat_boost"):
        fact = by_kind["low_hp_stat_boost"][0]
        stat = _pretty_stat(str(fact.get("stat") or "a stat"))
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate(f"Raises {stat} below half HP", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate(f"Half-HP {stat} spike", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate(f"{stat} boost when weakened", ref, 0.66, 0.8, "effect"))
        cryptic.extend([f"{stat.lower()} surge", "low-hp boost"])
        descriptors.append("Low-HP boosting abilities")
    if by_kind.get("mental_guard"):
        ref = str(by_kind["mental_guard"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Protects allies from mental moves", ref, 0.76, 0.84, "effect"))
        candidates.append(_candidate("Ally mind-shield trait", ref, 0.7, 0.8, "effect"))
        candidates.append(_candidate("Guards teammates from mental disruption", ref, 0.66, 0.82, "effect"))
        cryptic.extend(["ally mind guard", "mental shield"])
        descriptors.append("Ally-protecting abilities")
    if by_kind.get("aura_reversal"):
        ref = str(by_kind["aura_reversal"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Reverses dark and fairy auras", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("Turns aura boosts into penalties", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Aura-flipping trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["aura reverser", "aura flipper"])
        descriptors.append("Aura-reversing abilities")
    if by_kind.get("post_ko_transform"):
        fact = by_kind["post_ko_transform"][0]
        form = str(fact.get("transform_form") or "new form")
        ref = str(fact.get("evidence_ref") or "lead")
        candidates.append(_candidate("Transforms after a knockout", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate(f"KO-triggered form change", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate(f"Becomes {form} after a KO", ref, 0.66, 0.82, "effect"))
        cryptic.extend(["battle transformation", "ko transform"])
        descriptors.append("Transformation abilities")
    if by_kind.get("priority_block"):
        ref = str(by_kind["priority_block"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Blocks incoming priority moves", ref, 0.78, 0.88, "effect"))
        candidates.append(_candidate("Priority-proof trait", ref, 0.72, 0.82, "effect"))
        candidates.append(_candidate("Stops first-strike moves", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["priority shield", "first-strike blocker"])
        descriptors.append("Priority-blocking abilities")
    if by_kind.get("trapping_ability"):
        ref = str(by_kind["trapping_ability"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Prevents escape", ref, 0.76, 0.84, "effect"))
        candidates.append(_candidate("Traps opposing Pokemon", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("No-escape battle trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["battle trap", "escape blocker"])
        descriptors.append("Trapping abilities")
    if by_kind.get("ball_retrieve"):
        ref = str(by_kind["ball_retrieve"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Retrieves the first failed Poke Ball", ref, 0.76, 0.88, "effect"))
        candidates.append(_candidate("Fetches a failed throw", ref, 0.7, 0.82, "effect"))
        candidates.append(_candidate("Ball-returning trait", ref, 0.66, 0.8, "effect"))
        cryptic.extend(["ball retriever", "failed-throw fetch"])
        descriptors.append("Ball-retrieving abilities")
    if by_kind.get("commander_pair"):
        ref = str(by_kind["commander_pair"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Powers up Dondozo from inside", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("Enters Dondozo's mouth", ref, 0.72, 0.86, "effect"))
        candidates.append(_candidate("Ally-swallowing boost trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["dondozo partner", "mouth commander"])
        descriptors.append("Partner-link abilities")
    if by_kind.get("ally_stat_copy"):
        ref = str(by_kind["ally_stat_copy"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Copies an ally's stat changes", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("Inherits teammate stat boosts", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Ally stat-copying trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["ally stat copier", "teammate mimic"])
        descriptors.append("Stat-copying abilities")
    if by_kind.get("ko_attack_boost"):
        ref = str(by_kind["ko_attack_boost"][0].get("evidence_ref") or "lead")
        candidates.append(_candidate("Raises Attack after a knockout", ref, 0.78, 0.9, "effect"))
        candidates.append(_candidate("KO-triggered Attack boost", ref, 0.72, 0.84, "effect"))
        candidates.append(_candidate("Attack snowball trait", ref, 0.68, 0.8, "effect"))
        cryptic.extend(["ko attack boost", "attack snowball"])
        descriptors.append("Knockout-boosting abilities")
    if by_kind.get("title_semantic"):
        fact = by_kind["title_semantic"][0]
        semantic = str(fact.get("semantic") or fact.get("text") or "special")
        ref = str(fact.get("evidence_ref") or "title")
        candidates.append(_candidate(f"{semantic.title()} trait", ref, 0.68, 0.72, "title"))
        candidates.append(_candidate(f"{semantic.title()} ability", ref, 0.64, 0.7, "title"))
        candidates.append(_candidate(f"{semantic.title()} power", ref, 0.6, 0.68, "title"))
        cryptic.append(f"{semantic} trait")
        descriptors.append(f"{semantic.title()} abilities")
    for fact in by_kind.get("ability_generation", []):
        generation = str(fact.get("generation") or "")
        if generation:
            descriptors.append(f"{generation} abilities")

    if not candidates:
        return _generic_payload(facts, "ability")

    fact_nuggets = [
        {
            "text": str(fact["text"]),
            "evidence_ref": str(fact["evidence_ref"]),
            "specificity": float(fact["specificity"]),
        }
        for fact in facts[:12]
    ]
    return {
        "fact_nuggets": fact_nuggets,
        "crossword_candidates": candidates[:12],
        "cryptic_definition_seeds": _unique_strings(cryptic or ["battle ability"], 4),
        "connections_descriptors": _unique_strings(descriptors or ["Battle abilities"], 6),
        "risk_flags": _unique_strings(risk_flags, 4),
        "confidence": 0.74,
    }
