from __future__ import annotations

import re
from typing import Any


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
WHITESPACE_RE = re.compile(r"\s+")
NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")
GENERATION_RE = re.compile(r"Generation\s+([IVX]+)", re.IGNORECASE)

COLOR_TERMS = (
    "grayish-brown",
    "grayish brown",
    "light gray",
    "light gray",
    "gray",
    "grey",
    "brown",
    "golden",
    "red-tipped",
    "white",
    "black",
    "yellow",
)

LOCATION_KIND_TERMS = (
    "town",
    "city",
    "village",
    "settlement",
    "gate",
    "route",
    "path",
    "trail",
    "road",
    "forest",
    "woods",
    "cave",
    "cavern",
    "tunnel",
    "sea",
    "bay",
    "lake",
    "river",
    "island",
    "meadow",
    "mountain",
    "peak",
    "cliff",
    "ruins",
    "temple",
    "tower",
    "mine",
    "field",
    "coast",
    "beach",
)

ABILITY_TITLE_SEMANTICS = {
    "AQUA BOOST": "water-boosting",
    "BLACK HOLE": "space-warping",
    "BODYGUARD": "protective",
    "BONANZA": "windfall",
    "BULLETPROOF": "projectile-blocking",
    "CALMING": "soothing",
    "CHEEK POUCH": "berry-storing",
    "CHILLING NEIGH": "icy steed",
    "CLIMBER": "wall-scaling",
    "COLOR CHANGE": "type-shifting",
    "CONFIDENCE": "morale-boosting",
    "CONQUEROR": "domineering",
    "CORROSION": "corrosive",
    "COSTAR": "ally-copying",
    "COTTON DOWN": "fluff-shedding",
    "CUD CHEW": "double-berry",
    "DAMP": "explosion-dampening",
}


def _clean_text(value: str) -> str:
    text = NON_ASCII_RE.sub("", str(value or "").replace("Pokémon", "Pokemon"))
    return WHITESPACE_RE.sub(" ", text).strip()


def _sentence_iter(text: str) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]


def _section_text(evidence: dict[str, Any] | None, title: str) -> str:
    if not isinstance(evidence, dict):
        return ""
    chunks: list[str] = []
    for row in evidence.get("sections", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("title") or "").strip().lower() == title.strip().lower():
            text = _clean_text(str(row.get("text") or ""))
            if text:
                chunks.append(text)
    return _clean_text(" ".join(chunks))


def _row_clue_text(answer_row: dict[str, Any]) -> str:
    return _clean_text(str(answer_row.get("clueText") or ""))


def _roman_generation_label(value: str) -> str:
    return f"Gen {str(value or '').upper()}"


def _add_fact(
    facts: list[dict[str, Any]],
    *,
    kind: str,
    text: str,
    evidence_ref: str,
    specificity: float,
    **extra: Any,
) -> None:
    cleaned = _clean_text(text)
    if not cleaned:
        return
    key = (kind, cleaned.lower(), evidence_ref.lower())
    seen_keys = {(row.get("kind"), str(row.get("text") or "").lower(), str(row.get("evidence_ref") or "").lower()) for row in facts}
    if key in seen_keys:
        return
    row = {
        "kind": kind,
        "text": cleaned,
        "evidence_ref": evidence_ref,
        "specificity": round(float(specificity), 3),
    }
    row.update(extra)
    facts.append(row)


def _extract_species_facts(
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    lead = _clean_text(str((evidence or {}).get("leadText") or ""))
    biology = _section_text(evidence, "Biology")
    game_data = _section_text(evidence, "Game data")
    pokedex = _section_text(evidence, "Pokédex entries") or _section_text(evidence, "Pokedex entries")

    if lead:
        type_match = re.search(
            r"(?:dual-type\s+([A-Za-z]+)/([A-Za-z]+)|([A-Za-z]+)-type)\s+Pokemon introduced in Generation\s+([IVX]+)",
            lead,
            re.IGNORECASE,
        )
        if type_match:
            if type_match.group(1) and type_match.group(2):
                types = [type_match.group(1).title(), type_match.group(2).title()]
                generation = _roman_generation_label(type_match.group(4))
            else:
                types = [type_match.group(3).title()]
                generation = _roman_generation_label(type_match.group(4))
            _add_fact(
                facts,
                kind="typing_generation",
                text=f"{'/'.join(types)} species from {generation}",
                evidence_ref="lead",
                specificity=0.96,
                types=types,
                generation=generation,
            )
        evolve_match = re.search(r"evolves from\s+([A-Za-z-]+)", lead, re.IGNORECASE)
        if evolve_match:
            _add_fact(
                facts,
                kind="evolves_from",
                text=f"Evolves from {evolve_match.group(1).title()}",
                evidence_ref="lead",
                specificity=0.72,
                evolves_from=evolve_match.group(1).title(),
            )
        if re.search(r"final form of\s+([A-Za-z-]+)", lead, re.IGNORECASE):
            final_match = re.search(r"final form of\s+([A-Za-z-]+)", lead, re.IGNORECASE)
            if final_match:
                _add_fact(
                    facts,
                    kind="final_form",
                    text=f"Final form of {final_match.group(1).title()}",
                    evidence_ref="lead",
                    specificity=0.7,
                    final_form_of=final_match.group(1).title(),
                )
        if re.search(r"Mega Evolve into Mega", lead, re.IGNORECASE):
            _add_fact(
                facts,
                kind="mega_available",
                text="Has a Mega Evolution",
                evidence_ref="lead",
                specificity=0.68,
            )
        form_match = re.search(r"Paradox Pokemon|Legendary Pokemon|Mythical Pokemon|Seed Pokemon|Mouse Pokemon|Cactus Pokemon|Fairy Pokemon|Aura Pokemon|Fox Pokemon|Dragon Pokemon", lead, re.IGNORECASE)
        if form_match:
            _add_fact(
                facts,
                kind="genus_signature",
                text=form_match.group(0),
                evidence_ref="lead",
                specificity=0.76,
                genus=form_match.group(0),
            )

    if biology:
        lowered_biology = biology.lower()
        for phrase in ("bird of prey", "avian Pokemon", "avian creature", "large bird"):
            if phrase in lowered_biology:
                archetype = "bird of prey" if "bird of prey" in phrase else "avian species"
                _add_fact(
                    facts,
                    kind="archetype",
                    text=archetype,
                    evidence_ref="Biology",
                    specificity=0.88 if archetype == "bird of prey" else 0.66,
                    archetype=archetype,
                )
                break
        for color in COLOR_TERMS:
            if color in lowered_biology:
                label = color.replace("grayish brown", "gray-brown").replace("grayish-brown", "gray-brown")
                _add_fact(
                    facts,
                    kind="visual_color",
                    text=f"{label} coloring",
                    evidence_ref="Biology",
                    specificity=0.74,
                    color=label,
                )
                break
        if "leaves its flock to live alone" in lowered_biology or "left the flock" in lowered_biology:
            _add_fact(
                facts,
                kind="solitary_lore",
                text="Leaves its flock to live alone",
                evidence_ref="Biology",
                specificity=0.92,
            )
        if "challenge foes" in lowered_biology or "persistently attacking even larger foes" in lowered_biology:
            _add_fact(
                facts,
                kind="aggressive_lore",
                text="Challenges foes much larger than itself",
                evidence_ref="Biology",
                specificity=0.9,
            )
        if "fly effortlessly while carrying other pokemon" in lowered_biology or "carry other pokemon" in lowered_biology:
            _add_fact(
                facts,
                kind="carry_strength",
                text="Flies while carrying other Pokemon",
                evidence_ref="Biology",
                specificity=0.86,
            )
        if "fusses over the shape of its comb" in lowered_biology or "shape of this comb" in lowered_biology:
            _add_fact(
                facts,
                kind="crest_trait",
                text="Fussy about its crest shape",
                evidence_ref="Biology",
                specificity=0.78,
            )

    stat_source = "Game data" if game_data else "lead"
    stat_text = game_data or lead
    if stat_text:
        attack_match = re.search(r"Attack\s*:\s*(\d+)", stat_text, re.IGNORECASE)
        speed_match = re.search(r"Speed\s*:\s*(\d+)", stat_text, re.IGNORECASE)
        if attack_match:
            _add_fact(
                facts,
                kind="attack_stat",
                text=f"{attack_match.group(1)} base Attack",
                evidence_ref=stat_source,
                specificity=0.8,
                attack=int(attack_match.group(1)),
            )
        if speed_match:
            _add_fact(
                facts,
                kind="speed_stat",
                text=f"{speed_match.group(1)} base Speed",
                evidence_ref=stat_source,
                specificity=0.78,
                speed=int(speed_match.group(1)),
            )
        if attack_match and speed_match:
            _add_fact(
                facts,
                kind="statline",
                text=f"{attack_match.group(1)} Attack and {speed_match.group(1)} Speed",
                evidence_ref=stat_source,
                specificity=0.9,
                attack=int(attack_match.group(1)),
                speed=int(speed_match.group(1)),
            )
        mega_type_match = re.search(rf"Mega\s+{re.escape(str(answer_row.get('answerDisplay') or '').title())}\s+[A-Za-z-]+\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+Evolution data", stat_text)
        if mega_type_match:
            _add_fact(
                facts,
                kind="mega_typing",
                text=f"Mega form becomes {mega_type_match.group(1)}/{mega_type_match.group(2)}",
                evidence_ref=stat_source,
                specificity=0.87,
                mega_types=[mega_type_match.group(1), mega_type_match.group(2)],
            )

    if pokedex:
        lowered_pokedex = pokedex.lower()
        if "savage nature" in lowered_pokedex:
            _add_fact(
                facts,
                kind="temperament",
                text="Has a savage nature",
                evidence_ref="Pokédex entries",
                specificity=0.8,
            )
        if "courageously challenge foes that are much larger" in lowered_pokedex:
            _add_fact(
                facts,
                kind="aggressive_lore",
                text="Challenges much larger foes",
                evidence_ref="Pokédex entries",
                specificity=0.84,
            )

    genus = _clean_text(str(structured_facts.get("genus") or ""))
    generation_label = _clean_text(str(structured_facts.get("generationLabel") or ""))
    color = _clean_text(str(structured_facts.get("color") or ""))
    egg_groups = structured_facts.get("eggGroups") or []
    if genus:
        _add_fact(
            facts,
            kind="genus_signature",
            text=genus.replace("Pokémon", "Pokemon"),
            evidence_ref="lead",
            specificity=0.72,
            genus=genus.replace("Pokémon", "Pokemon"),
        )
    if generation_label and genus:
        _add_fact(
            facts,
            kind="generation_genus",
            text=f"{generation_label} {genus.replace('Pokémon', 'Pokemon')}",
            evidence_ref="lead",
            specificity=0.66,
            generation=generation_label,
            genus=genus.replace("Pokémon", "Pokemon"),
        )
    if color and genus:
        _add_fact(
            facts,
            kind="color_genus",
            text=f"{color.title()} {genus.replace('Pokémon', 'Pokemon')}",
            evidence_ref="lead",
            specificity=0.64,
            color=color.title(),
            genus=genus.replace("Pokémon", "Pokemon"),
        )
    if isinstance(egg_groups, list):
        for group in egg_groups[:2]:
            cleaned = _clean_text(str(group or ""))
            if cleaned:
                _add_fact(
                    facts,
                    kind="egg_group",
                    text=f"{cleaned.title()} egg-group species",
                    evidence_ref="lead",
                    specificity=0.54,
                    egg_group=cleaned.title(),
                )

    if not facts and structured_facts.get("genus"):
        _add_fact(
            facts,
            kind="fallback_genus",
            text=str(structured_facts.get("genus") or ""),
            evidence_ref="lead",
            specificity=0.45,
        )
    return facts


def _extract_move_facts(
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    generation = str(structured_facts.get("generationLabel") or "")
    move_type = str(structured_facts.get("moveType") or "")
    damage_class = str(structured_facts.get("damageClass") or "")
    effect = _clean_text(str(structured_facts.get("effect") or ""))
    corpus_effect = _row_clue_text(answer_row)
    effect_section = _section_text(evidence, "Effect")
    description = _section_text(evidence, "Description")
    if effect_section and (not effect or len(effect_section) < len(effect)):
        effect = effect_section
    elif description and not effect:
        effect = description
    if corpus_effect and (not effect or effect.lower() == "pokemon battle move."):
        effect = corpus_effect
    if generation and move_type:
        _add_fact(facts, kind="move_taxonomy", text=f"{generation} {move_type} move", evidence_ref="lead", specificity=0.56, generation=generation, move_type=move_type)
    if move_type and damage_class:
        _add_fact(facts, kind="move_profile", text=f"{move_type} {damage_class.lower()} move", evidence_ref="lead", specificity=0.6, move_type=move_type, damage_class=damage_class)
    if effect:
        _add_fact(facts, kind="effect_text", text=effect, evidence_ref="lead", specificity=0.62, effect=effect)
        lowered_effect = effect.lower()
        if "puts the target to sleep" in lowered_effect or "target sleeps" in lowered_effect:
            _add_fact(facts, kind="sleep_inflict", text="Puts the target to sleep", evidence_ref="lead", specificity=0.9)
        fixed_damage_match = re.search(r"inflicts\s+(\d+)\s+points of damage", lowered_effect)
        if fixed_damage_match:
            damage = int(fixed_damage_match.group(1))
            _add_fact(
                facts,
                kind="fixed_damage",
                text=f"Always deals {damage} damage",
                evidence_ref="lead",
                specificity=0.92,
                damage=damage,
            )
        if "heavier targets" in lowered_effect:
            max_power_match = re.search(r"maximum of\s+(\d+)\s+power", lowered_effect)
            _add_fact(
                facts,
                kind="weight_damage",
                text="Stronger against heavier targets",
                evidence_ref="lead",
                specificity=0.9,
                max_power=int(max_power_match.group(1)) if max_power_match else None,
            )
        if "last used move" in lowered_effect:
            _add_fact(facts, kind="mirror_copy", text="Uses the foe's last move", evidence_ref="lead", specificity=0.9)
        if "halves hp of all pokemon on the field" in lowered_effect:
            _add_fact(facts, kind="field_hp_halve", text="Halves all active Pokemon's HP", evidence_ref="lead", specificity=0.92)
        if "prevents the target from leaving battle" in lowered_effect:
            _add_fact(facts, kind="battle_trap", text="Prevents the target from leaving battle", evidence_ref="lead", specificity=0.88)
        if "confuses the target" in lowered_effect:
            _add_fact(facts, kind="confuse_inflict", text="Confuses the target", evidence_ref="lead", specificity=0.88)
        if "removes light screen, reflect, and safeguard" in lowered_effect:
            _add_fact(facts, kind="screen_clear", text="Removes Light Screen, Reflect, and Safeguard", evidence_ref="lead", specificity=0.92)
        if "halves all fire-type damage" in lowered_effect:
            _add_fact(facts, kind="fire_weaken", text="Halves Fire-type damage", evidence_ref="lead", specificity=0.9)
        if str(answer_row.get("answerDisplay") or "").strip().upper() == "SHADOW SKY":
            _add_fact(facts, kind="weather_move", text="Battlefield weather move", evidence_ref="title", specificity=0.68)
        if "cannot use held items" in lowered_effect or ("cannot use" in lowered_effect and "held item" in lowered_effect):
            _add_fact(
                facts,
                kind="held_item_lock",
                text="Prevents held item use",
                evidence_ref="lead",
                specificity=0.86,
            )
    if isinstance(structured_facts.get("power"), int):
        _add_fact(facts, kind="power", text=f"{structured_facts['power']}-power move", evidence_ref="lead", specificity=0.58, power=structured_facts["power"])
    if isinstance(structured_facts.get("priority"), int) and int(structured_facts["priority"]) > 0:
        _add_fact(facts, kind="priority", text="priority move", evidence_ref="lead", specificity=0.66, priority=int(structured_facts["priority"]))
    return facts


def _extract_item_facts(
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    answer_display = _clean_text(str(answer_row.get("answerDisplay") or "")).upper()
    lead = _clean_text(str((evidence or {}).get("leadText") or ""))
    effect_section = _section_text(evidence, "Effect")
    acquisition = _section_text(evidence, "Acquisition")
    description = _section_text(evidence, "Description")
    core_games = _section_text(evidence, "In the core series games")
    generation = str(structured_facts.get("generationLabel") or "")
    category = _clean_text(str(structured_facts.get("category") or ""))
    effect = _clean_text(str(structured_facts.get("effect") or ""))
    corpus_effect = _row_clue_text(answer_row)
    if effect_section and (not effect or "xxx " in effect.lower() or "new effect" in effect.lower() or "unused" in effect.lower()):
        effect = effect_section
    elif effect_section and not effect:
        effect = effect_section
    if corpus_effect and (not effect or effect.lower().startswith("pokemon item from")):
        effect = corpus_effect

    if lead:
        generation_match = GENERATION_RE.search(lead)
        if generation_match:
            generation = _roman_generation_label(generation_match.group(1))
        if generation:
            _add_fact(
                facts,
                kind="item_generation",
                text=f"{generation} item",
                evidence_ref="lead",
                specificity=0.48,
                generation=generation,
            )
        if "held by a pokemon" in lead.lower() or "held by a pokemon" in description.lower():
            _add_fact(
                facts,
                kind="held_item",
                text="Held battle item",
                evidence_ref="Description" if description else "lead",
                specificity=0.7,
            )
        if "changes a pokemon's ability" in lead.lower():
            _add_fact(
                facts,
                kind="ability_change_item",
                text="Changes a Pokemon's Ability",
                evidence_ref="lead",
                specificity=0.88,
            )

    if category:
        _add_fact(facts, kind="item_category", text=category, evidence_ref="lead", specificity=0.62, category=category)
    if generation and category:
        _add_fact(facts, kind="item_taxonomy", text=f"{generation} {category}", evidence_ref="lead", specificity=0.54, generation=generation, category=category)
    if effect:
        _add_fact(facts, kind="effect_text", text=effect, evidence_ref="lead", specificity=0.62, effect=effect)
    searchable = " ".join(part for part in [effect_section, description, core_games, acquisition, lead, effect, corpus_effect, category] if part).lower()
    if "increase all their stats at once" in searchable or "increases all their stats at once" in searchable:
        _add_fact(
            facts,
            kind="species_candy_boost",
            text="Raises all stats at once for a specific species",
            evidence_ref="lead",
            specificity=0.86,
        )
    crafted_match = re.search(r"used to make a[n]?\s+([a-z' -]+)", searchable, re.IGNORECASE)
    if crafted_match:
        crafted_item = _clean_text(crafted_match.group(1).title())
        _add_fact(
            facts,
            kind="crafted_item",
            text=f"Used to make a {crafted_item}",
            evidence_ref="lead",
            specificity=0.88,
            crafted_item=crafted_item,
        )
    flat_hp_match = re.search(r"restores?\s+(\d+)\s+hp", searchable, re.IGNORECASE)
    if flat_hp_match:
        _add_fact(
            facts,
            kind="flat_hp_restore",
            text=f"Restores {flat_hp_match.group(1)} HP",
            evidence_ref="lead",
            specificity=0.88,
            hp=int(flat_hp_match.group(1)),
        )
    soil_dry_match = re.search(r"soil to dry out in\s+(\d+)\s+hours", searchable, re.IGNORECASE)
    if soil_dry_match:
        _add_fact(
            facts,
            kind="soil_dry_time",
            text=f"Dries soil in {soil_dry_match.group(1)} hours",
            evidence_ref="lead",
            specificity=0.88,
            hours=int(soil_dry_match.group(1)),
        )
    berry_yield_match = re.search(r"increases the total number of berries by\s+(\d+)", searchable, re.IGNORECASE)
    if berry_yield_match:
        _add_fact(
            facts,
            kind="berry_yield_boost",
            text=f"Adds {berry_yield_match.group(1)} more berries",
            evidence_ref="lead",
            specificity=0.86,
            added_berries=int(berry_yield_match.group(1)),
        )
    if "chance of berry mutation" in searchable:
        _add_fact(facts, kind="berry_mutation_boost", text="Raises berry mutation odds", evidence_ref="lead", specificity=0.86)
    if "berries regrow from dead plants" in searchable:
        _add_fact(facts, kind="berry_regrow_boost", text="Makes dead berry plants regrow more often", evidence_ref="lead", specificity=0.88)
    if "growing time of berries is reduced" in searchable:
        _add_fact(facts, kind="berry_growth_speed", text="Speeds berry growth", evidence_ref="lead", specificity=0.86)
    if "berries stay on the plant for longer" in searchable:
        _add_fact(facts, kind="berry_retention", text="Keeps berries on the plant longer", evidence_ref="lead", specificity=0.86)
    if "dream world" in searchable and "catches" in searchable:
        _add_fact(facts, kind="dream_world_capture", text="Catches Pokemon from the Dream World", evidence_ref="lead", specificity=0.9)
    if "critical hit" in searchable and "chance" in searchable:
        _add_fact(facts, kind="crit_boost_item", text="Raises critical-hit odds", evidence_ref="lead", specificity=0.88)
    if "all of its stats will grow at an equal rate" in searchable:
        _add_fact(facts, kind="neutral_mint_profile", text="Makes every stat grow equally", evidence_ref="lead", specificity=0.88)
    if "can be thrown further" in searchable and "fly high in the air" in searchable:
        _add_fact(facts, kind="airborne_capture_tool", text="Thrown far and works on high-flying targets", evidence_ref="lead", specificity=0.88)
    if "doesn't fly far" in searchable and "hasn't noticed the player" in searchable:
        _add_fact(facts, kind="stealth_capture_tool", text="Best on unnoticed targets", evidence_ref="lead", specificity=0.88)
    if "catches a wild pokemon every time" in searchable:
        _add_fact(facts, kind="guaranteed_capture", text="Never fails to catch wild Pokemon", evidence_ref="lead", specificity=0.9)
    if "pal park every time" in searchable:
        _add_fact(facts, kind="pal_park_capture", text="Never fails in Pal Park", evidence_ref="lead", specificity=0.9)
    if "great marsh" in searchable or "safari zone" in searchable:
        _add_fact(facts, kind="safari_capture", text="Safari-zone capture tool", evidence_ref="lead", specificity=0.88)
    if answer_display.startswith("LA") and answer_display.endswith(" BALL") and effect.lower().startswith("pokemon item from"):
        _add_fact(facts, kind="hisui_capture_tool", text="Hisui capture tool", evidence_ref="title", specificity=0.74)
    if "curry" in answer_display:
        _add_fact(facts, kind="camp_meal_pack", text="Camping meal packet", evidence_ref="title", specificity=0.68)
    if "PICNIC SET" in answer_display:
        _add_fact(facts, kind="picnic_kit", text="Outdoor meal kit", evidence_ref="title", specificity=0.72)
    if "protects the holder from having its ability changed" in searchable or "ability from being changed or suppressed" in searchable:
        _add_fact(
            facts,
            kind="ability_protection",
            text="Protects the holder's Ability",
            evidence_ref="Description" if description else "In the core series games",
            specificity=0.94,
        )
    if "hidden ability" in searchable:
        _add_fact(
            facts,
            kind="hidden_ability_swap",
            text="Unlocks a Hidden Ability",
            evidence_ref="In the core series games" if core_games else "Description",
            specificity=0.94,
        )
    if "rare ability" in searchable or "rarer ability" in searchable:
        _add_fact(
            facts,
            kind="rare_ability_swap",
            text="Changes a regular Ability to a rarer one",
            evidence_ref="Description" if description else "lead",
            specificity=0.86,
        )
    if "can only be used on a pokemon that belongs to a species with a hidden ability" in searchable:
        _add_fact(
            facts,
            kind="hidden_ability_restriction",
            text="Works only on species with Hidden Abilities",
            evidence_ref="In the core series games",
            specificity=0.82,
        )
    if "tm materials" in category.lower():
        _add_fact(facts, kind="tm_materials", text="TM crafting material", evidence_ref="lead", specificity=0.72)
    if "z crystals" in category.lower() or " z " in f" {answer_display} " or answer_display.endswith(" Z"):
        _add_fact(facts, kind="z_crystal", text="Z-Move crystal", evidence_ref="lead", specificity=0.78)
    if "berry" in answer_display or "berry" in category.lower():
        _add_fact(facts, kind="berry_family", text="Battle berry", evidence_ref="lead", specificity=0.72)
    if answer_display.endswith(" MINT") or "mint" in category.lower():
        _add_fact(facts, kind="mint_family", text="Nature-changing mint", evidence_ref="lead", specificity=0.74)
    if answer_display.endswith(" FOSSIL") or "fossil" in answer_display:
        _add_fact(facts, kind="fossil_family", text="Prehistoric revival item", evidence_ref="lead", specificity=0.72)
    if any(token in answer_display for token in (" PLATE", " MEMORY", " DRIVE", " ORB")):
        _add_fact(facts, kind="signature_family_item", text="Species-linked power item", evidence_ref="lead", specificity=0.68)
    if any(token in answer_display for token in (" SHARD", " MATERIAL", " ORE")) or "collectible" in category.lower():
        _add_fact(facts, kind="material_family", text="Crafting or exchange material", evidence_ref="lead", specificity=0.66)
    if any(token in answer_display for token in (" KEY", " PASS", " TICKET", " FLUTE", " CARD")):
        _add_fact(facts, kind="key_family", text="Story or event key item", evidence_ref="lead", specificity=0.66)
    if "candies" in category.lower():
        _add_fact(facts, kind="candies_family", text="Species candy item", evidence_ref="lead", specificity=0.68)
    if "mail" in category.lower():
        _add_fact(facts, kind="mail_family", text="Mail stationery", evidence_ref="lead", specificity=0.7)
    if "balls" in category.lower() or "balls" in searchable:
        _add_fact(facts, kind="ball_family", text="Special Poke Ball", evidence_ref="lead", specificity=0.68)
    if "mega stone" in category.lower():
        _add_fact(facts, kind="mega_stone", text="Mega Evolution stone", evidence_ref="lead", specificity=0.78)
    mega_target_match = re.search(
        r"allows\s+([A-Za-z' -]+?)\s+to mega evolve into mega\s+([A-Za-z' -]+?)(?:\s+if\b|[.;,]|$)",
        searchable,
        re.IGNORECASE,
    )
    if mega_target_match:
        target = _clean_text(mega_target_match.group(2).title())
        _add_fact(
            facts,
            kind="mega_target",
            text=f"Mega stone for {target}",
            evidence_ref="Description" if description else "lead",
            specificity=0.9,
            mega_target=target,
        )
    if "evolution" in category.lower():
        _add_fact(facts, kind="evolution_item", text="Evolution item", evidence_ref="lead", specificity=0.76)
    if "gameplay" in category.lower():
        _add_fact(facts, kind="utility_item", text="Adventure utility item", evidence_ref="lead", specificity=0.58)
    if "change their lipstick color" in searchable:
        _add_fact(facts, kind="trainer_cosmetic", text="Changes a trainer's lipstick", evidence_ref="lead", specificity=0.88)
    if "bug-catching contest" in searchable:
        _add_fact(facts, kind="contest_ball", text="Bug-Catching Contest ball", evidence_ref="lead", specificity=0.9)
    if re.search(r"\b(bicycle|bike)\b", searchable):
        _add_fact(facts, kind="transport_item", text="Two-wheeled travel item", evidence_ref="lead", specificity=0.72)
    if "fast transit" in searchable or "travel quickly" in searchable or "allows the player to move faster" in searchable:
        _add_fact(facts, kind="fast_travel", text="Speeds up travel", evidence_ref="lead", specificity=0.76)
    if "miracle shooter" in searchable:
        _add_fact(facts, kind="miracle_shooter", text="Miracle Shooter item", evidence_ref="lead", specificity=0.74)
    if "forcibly activates" in searchable and "ability" in searchable:
        _add_fact(facts, kind="friendly_ability_trigger", text="Forcibly triggers an ally's Ability", evidence_ref="lead", specificity=0.88)
    if "doubles the money earned from a battle" in searchable or "doubles the amount of prize money" in searchable or "doubles any prize money" in searchable or "doubles monetary earnings" in searchable:
        _add_fact(facts, kind="money_double", text="Doubles prize money", evidence_ref="Description" if description else "lead", specificity=0.86)
    if "cures sleep" in searchable or "wakes a sleeping pokemon" in searchable or "awakens a sleeping pokemon" in searchable or "wake a pokemon from sleep" in searchable or "rouse a pokemon from the clutches of sleep" in searchable:
        _add_fact(facts, kind="sleep_cure", text="Wakes a sleeping Pokemon", evidence_ref="Description" if description else "lead", specificity=0.84)
    if "can be revived into a" in searchable or "can be regenerated into" in searchable:
        fossil_match = re.search(r"can be (?:re)?generated into a[n]?\s+([A-Za-z-]+)", searchable, re.IGNORECASE)
        if fossil_match:
            revived = _clean_text(fossil_match.group(1).title())
            _add_fact(
                facts,
                kind="fossil_revival",
                text=f"Revives into {revived}",
                evidence_ref="Description" if description else "lead",
                specificity=0.88,
                revived_species=revived,
            )
    if ("boosts the damage from" in searchable or "boosts the power of" in searchable) and "-type moves" in searchable:
        orb_match = re.search(
            r"(?:boosts the damage from|boosts the power of)\s+(?:([A-Za-z' -]+?)s\s+)?([A-Za-z/-]+)-type(?: and ([A-Za-z/-]+)-type)? moves(?: when held by ([A-Za-z' -]+))?",
            searchable,
            re.IGNORECASE,
        )
        if not orb_match:
            orb_match = re.search(
                r"held by ([A-Za-z' -]+).*?([A-Za-z]+)-\s*and\s*([A-Za-z]+)-type moves",
                searchable,
                re.IGNORECASE,
            )
        if orb_match:
            if orb_match.lastindex and orb_match.lastindex >= 4:
                holder = _clean_text((orb_match.group(1) or orb_match.group(4) or "").title())
                types = [orb_match.group(2).title()]
                if orb_match.group(3):
                    types.append(orb_match.group(3).title())
            else:
                holder = _clean_text((orb_match.group(1) or "").title())
                types = [orb_match.group(2).title()]
                if orb_match.group(3):
                    types.append(orb_match.group(3).title())
            _add_fact(
                facts,
                kind="species_type_boost",
                text=f"Boosts {'/'.join(types)} moves for {holder}",
                evidence_ref="Description" if description else "lead",
                specificity=0.9,
                holder_species=holder,
                boost_types=types,
            )
    if "ultra beasts" in searchable:
        _add_fact(facts, kind="ultra_beast_ball", text="Works best on Ultra Beasts", evidence_ref="Description" if description else "lead", specificity=0.9)
    if "0.1" in searchable or "0.1x" in searchable or "for all other pokemon" in searchable:
        _add_fact(facts, kind="niche_capture", text="Poor catch rate on most targets", evidence_ref="Description" if description else "lead", specificity=0.82)
    signature_z_match = re.search(
        r"allows\s+([a-z' -]+?)\s+to upgrade\s+([a-z' -]+?)\s+into\s+([a-z' -]+?)(?:[.;]|$)",
        searchable,
        re.IGNORECASE,
    )
    if signature_z_match:
        holder = _clean_text(signature_z_match.group(1).title())
        base_move = _clean_text(signature_z_match.group(2).title())
        z_move = _clean_text(signature_z_match.group(3).title())
        _add_fact(
            facts,
            kind="signature_z_crystal",
            text=f"Upgrades {base_move} into {z_move} for {holder}",
            evidence_ref="lead",
            specificity=0.94,
            holder_species=holder,
            base_move=base_move,
            z_move=z_move,
        )
    type_z_match = re.search(
        r"z-move equivalents of (?:its|their)\s+([a-z/-]+)\s+moves",
        searchable,
        re.IGNORECASE,
    )
    if type_z_match:
        z_type = _clean_text(type_z_match.group(1).title())
        _add_fact(
            facts,
            kind="type_z_crystal",
            text=f"Crystal for {z_type} Z-Moves",
            evidence_ref="lead",
            specificity=0.86,
            z_move_type=z_type,
        )
    held_effect_match = re.search(
        r"raises the holder'?s\s+([A-Za-z ]+?)\s+by\s+(?:one|two|three|1\.5|1\.3|1\.2|1\.1|[\d.]+)\s*(?:stage|stages)?\s+when\s+(.+?)(?:[.;]|$)",
        searchable,
        re.IGNORECASE,
    )
    if held_effect_match:
        _add_fact(
            facts,
            kind="triggered_stat_boost",
            text=f"Boosts {held_effect_match.group(1).strip()} when {held_effect_match.group(2).strip()}",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
            stat=held_effect_match.group(1).strip(),
            trigger=held_effect_match.group(2).strip(),
        )
    alt_triggered_boost_match = re.search(
        r"(?:raises|boosts)\s+(?:the holder'?s\s+)?([A-Za-z. ]+?)\s+(?:stat\s+)?if\s+(?:it|the holder)\s+is\s+(.+?)(?:[.;]|$)",
        searchable,
        re.IGNORECASE,
    )
    if alt_triggered_boost_match:
        _add_fact(
            facts,
            kind="triggered_stat_boost",
            text=f"Boosts {alt_triggered_boost_match.group(1).replace('Sp.', 'Special ').strip()} when {alt_triggered_boost_match.group(2).strip()}",
            evidence_ref="Description" if description else "lead",
            specificity=0.86,
            stat=alt_triggered_boost_match.group(1).replace("Sp.", "Special ").strip(),
            trigger=alt_triggered_boost_match.group(2).strip(),
        )
    passive_boost_match = re.search(
        r"raises the holder'?s\s+([A-Za-z ]+?)\s+to\s+([\d.]+)",
        searchable,
        re.IGNORECASE,
    )
    if passive_boost_match:
        _add_fact(
            facts,
            kind="passive_stat_boost",
            text=f"Raises {passive_boost_match.group(1).strip()}",
            evidence_ref="Description" if description else "lead",
            specificity=0.84,
            stat=passive_boost_match.group(1).strip(),
            multiplier=passive_boost_match.group(2).strip(),
        )
    flat_boost_match = re.search(
        r"(?:raises|boosts)\s+(?:the holder'?s\s+)?([A-Za-z. ]+?)\s+(?:stat\s+)?but",
        searchable,
        re.IGNORECASE,
    )
    if flat_boost_match:
        _add_fact(
            facts,
            kind="passive_stat_boost",
            text=f"Raises {flat_boost_match.group(1).replace('Sp.', 'Special ').strip()}",
            evidence_ref="Description" if description else "lead",
            specificity=0.82,
            stat=flat_boost_match.group(1).replace("Sp.", "Special ").strip(),
        )
    if "prevents the holder from selecting a status move" in searchable:
        _add_fact(
            facts,
            kind="status_move_restriction",
            text="Prevents status moves",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
        )
    if "prevents the use of status moves" in searchable:
        _add_fact(
            facts,
            kind="status_move_restriction",
            text="Prevents status moves",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
        )
    immunity_match = re.search(
        r"grants immunity to\s+([A-Za-z/-]+)-type moves",
        searchable,
        re.IGNORECASE,
    )
    if immunity_match:
        _add_fact(
            facts,
            kind="type_immunity_item",
            text=f"Blocks {immunity_match.group(1).title()}-type moves",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
            immune_type=immunity_match.group(1).title(),
        )
    if "float in the air" in searchable or "makes the holder ungrounded" in searchable:
        _add_fact(
            facts,
            kind="airborne_item",
            text="Makes the holder float above the ground",
            evidence_ref="Description" if description else "lead",
            specificity=0.86,
        )
    if "consumed when the holder takes damage from a move" in searchable:
        _add_fact(
            facts,
            kind="breaks_on_hit",
            text="Breaks after taking move damage",
            evidence_ref="Description" if description else "lead",
            specificity=0.8,
        )
    if "until hit" in searchable or "once hit" in searchable or "will burst" in searchable:
        _add_fact(
            facts,
            kind="breaks_on_hit",
            text="Breaks after taking move damage",
            evidence_ref="Description" if description else "lead",
            specificity=0.8,
        )
    if "recovered from draining moves" in searchable or "aqua ring" in searchable or "ingrain" in searchable:
        _add_fact(
            facts,
            kind="drain_heal_boost",
            text="Boosts recovery from draining effects",
            evidence_ref="Description" if description else "lead",
            specificity=0.86,
        )
    if "multi-turn trapping moves" in searchable or "per-turn damage of multi-turn trapping moves" in searchable or "binding moves" in searchable:
        _add_fact(
            facts,
            kind="trapping_move_boost",
            text="Boosts trapping-move damage",
            evidence_ref="Description" if description else "lead",
            specificity=0.86,
        )
    if "picnic" in category.lower():
        _add_fact(facts, kind="picnic_item", text="Picnic item", evidence_ref="lead", specificity=0.66)
    if "kicked around" in searchable or ("picnic" in searchable and "kick" in searchable):
        _add_fact(
            facts,
            kind="picnic_play",
            text="Can be kicked around at a picnic",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.84,
        )
    if "standard-issue" in searchable or "standard issue" in searchable:
        issue_scope = "academy" if "academy" in searchable or "school" in searchable else "official"
        _add_fact(
            facts,
            kind="standard_issue_item",
            text=f"{issue_scope.title()} standard-issue item",
            evidence_ref="Description" if description else "lead",
            specificity=0.82,
            issue_scope=issue_scope,
        )
    if "pokblock" in searchable or "poffin" in searchable or "berry powder" in searchable or "ingredient" in searchable:
        mediums: list[str] = []
        if "pokblock" in searchable:
            mediums.append("PokBlocks")
        if "poffin" in searchable:
            mediums.append("Poffins")
        if "berry powder" in searchable:
            mediums.append("Berry Powder")
        _add_fact(
            facts,
            kind="berry_cooking",
            text="Used for berry recipes or blending",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.82,
            recipe_mediums=mediums,
        )
    if "plant in loamy soil" in searchable or "grow this berry" in searchable or "grow belue" in searchable:
        _add_fact(
            facts,
            kind="berry_gardening",
            text="Plantable berry crop",
            evidence_ref="Description" if description else "lead",
            specificity=0.74,
        )
    if "restores hp" in searchable or "restores the hp" in searchable or "restores a pokemon's hp" in searchable:
        _add_fact(
            facts,
            kind="berry_heal",
            text="Restores HP in a pinch",
            evidence_ref="Description" if description else "lead",
            specificity=0.84,
        )
    if "confuse" in searchable and "taste" in searchable:
        _add_fact(
            facts,
            kind="berry_confusion",
            text="May confuse if the taste is disliked",
            evidence_ref="Description" if description else "lead",
            specificity=0.82,
        )
    if "in a pinch" in category.lower() or "when hp is low" in searchable or "below a quarter" in searchable or "half hp or less" in searchable:
        _add_fact(
            facts,
            kind="berry_pinch",
            text="Activates at low HP",
            evidence_ref="Description" if description else "lead",
            specificity=0.78,
        )
    if "collectible" in category.lower() or "exchange" in searchable or "traded for" in searchable:
        _add_fact(
            facts,
            kind="collectible_exchange",
            text="Tradable exchange item",
            evidence_ref="Acquisition" if acquisition else "lead",
            specificity=0.74,
        )
    if "ore" in answer_display:
        _add_fact(
            facts,
            kind="ore_family",
            text="Valuable exchange ore",
            evidence_ref="lead",
            specificity=0.72,
        )
    if "key item" in searchable or "used to open" in searchable or "unlocks" in searchable:
        _add_fact(
            facts,
            kind="unlock_item",
            text="Unlocks progression content",
            evidence_ref="Description" if description else "lead",
            specificity=0.8,
        )
    if "event-only" in searchable or "distributed" in searchable or "mystery gift" in searchable:
        _add_fact(
            facts,
            kind="event_gate_item",
            text="Event-only distribution item",
            evidence_ref="Acquisition" if acquisition else "lead",
            specificity=0.82,
        )
    mint_profile_match = re.search(
        r"increasing (?:its )?([a-z. ]+?) stat and decreasing (?:its )?([a-z. ]+?) stat",
        searchable,
        re.IGNORECASE,
    )
    if not mint_profile_match:
        mint_profile_match = re.search(
            r"([a-z. ]+?) will grow more easily, but (?:its )?([a-z. ]+?) will grow more slowly",
            searchable,
            re.IGNORECASE,
        )
    if mint_profile_match:
        up_stat = mint_profile_match.group(1).replace("sp.", "special ").strip()
        down_stat = mint_profile_match.group(2).replace("sp.", "special ").strip()
        _add_fact(
            facts,
            kind="mint_stat_profile",
            text=f"Raises {up_stat} and lowers {down_stat}",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.9,
            up_stat=up_stat,
            down_stat=down_stat,
        )
    if (
        ("collect seven" in searchable and "trial" in searchable)
        or ("all seven petals are collected" in searchable)
        or ("mina's trial" in searchable and "one of the items the player collects" in searchable)
        or ("mina?s trial" in searchable and "one of the items the player collects" in searchable)
    ):
        _add_fact(
            facts,
            kind="trial_collection",
            text="One of seven trial collectibles",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.86,
            required_count=7,
        )
    if "rainbow flower" in searchable:
        _add_fact(
            facts,
            kind="rainbow_flower_piece",
            text="Part of a Rainbow Flower",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.88,
        )
    trial_giver_match = re.search(r"receive from ([a-z]+) during mina'?s trial", searchable, re.IGNORECASE)
    if trial_giver_match:
        giver = _clean_text(trial_giver_match.group(1).title())
        _add_fact(
            facts,
            kind="trial_giver",
            text=f"Gift from {giver} during Mina's trial",
            evidence_ref="Description" if description else "Acquisition" if acquisition else "lead",
            specificity=0.84,
            giver=giver,
        )
    open_target_match = re.search(r"(?:used to open|opens)\s+([a-z0-9' -]+?)(?:[.;,]|$)", searchable, re.IGNORECASE)
    if open_target_match:
        target = _clean_text(open_target_match.group(1).title())
        if target:
            _add_fact(
                facts,
                kind="opens_target",
                text=f"Opens {target}",
                evidence_ref="Description" if description else "lead",
                specificity=0.86,
                target=target,
            )
    holder_stat_match = re.search(
        r"(?:raises|boosts|doubles)\s+(?:the\s+)?(?:stats of\s+a\s+)?([a-z' -]+?)\s+that holds it",
        searchable,
        re.IGNORECASE,
    )
    holder = _clean_text(holder_stat_match.group(1).title()) if holder_stat_match else ""
    holder_specific_match = re.search(
        r"(?:raises|boosts|doubles)\s+(?:the\s+)?([a-z. ]+?)(?:\s+and\s+([a-z. ]+?))?\s+of\s+([a-z' -]+)",
        searchable,
        re.IGNORECASE,
    )
    stats: list[str] = []
    if holder_specific_match:
        holder = holder or _clean_text(holder_specific_match.group(3).title())
        stats.append(holder_specific_match.group(1).replace("sp.", "special ").strip())
        if holder_specific_match.group(2):
            stats.append(holder_specific_match.group(2).replace("sp.", "special ").strip())
    if holder:
        _add_fact(
            facts,
            kind="species_stat_boost",
            text=f"Boosts {holder}'s stats",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.9 if stats else 0.82,
            holder_species=holder,
            boost_stats=stats,
        )
    return facts


def _extract_ability_facts(evidence: dict[str, Any] | None, structured_facts: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    lead = _clean_text(str((evidence or {}).get("leadText") or ""))
    description = _section_text(evidence, "Description")
    effect_section = _section_text(evidence, "Effect")
    in_battle = _section_text(evidence, "In battle")
    generation = str(structured_facts.get("generationLabel") or "")
    effect = _clean_text(str(structured_facts.get("effect") or ""))
    if generation:
        _add_fact(facts, kind="ability_generation", text=f"{generation} ability", evidence_ref="lead", specificity=0.48, generation=generation)
    if lead:
        _add_fact(facts, kind="ability_summary", text=lead, evidence_ref="lead", specificity=0.56, effect=lead)
    if description:
        _add_fact(facts, kind="ability_summary", text=description, evidence_ref="Description", specificity=0.64, effect=description)
    if effect_section:
        _add_fact(facts, kind="ability_summary", text=effect_section, evidence_ref="Effect", specificity=0.72, effect=effect_section)
    if in_battle:
        _add_fact(facts, kind="ability_summary", text=in_battle, evidence_ref="In battle", specificity=0.72, effect=in_battle)
    if effect:
        _add_fact(facts, kind="effect_text", text=effect, evidence_ref="lead", specificity=0.62, effect=effect)
    searchable = " ".join(part for part in [lead, description, effect_section, in_battle, effect] if part).lower()
    if "sleeping" in searchable and ("damage" in searchable or "bad dreams" in searchable):
        _add_fact(facts, kind="sleep_punish", text="Damages sleeping foes", evidence_ref="Description" if description else "lead", specificity=0.86)
    if "faints" in searchable and ("remaining hp" in searchable or "had remaining" in searchable):
        _add_fact(facts, kind="faint_recoil", text="Punishes a knockout blow", evidence_ref="lead", specificity=0.88)
    if "contact move" in searchable and ("damage" in searchable or "attacker" in searchable or "counterattacks" in searchable):
        _add_fact(facts, kind="contact_recoil", text="Punishes contact attackers", evidence_ref="Description" if description else "lead", specificity=0.86)
    if (
        "cannot be lowered" in searchable
        or "prevents its stats from being lowered" in searchable
        or "prevents stat reduction" in searchable
        or "prevents stats from being lowered" in searchable
    ):
        _add_fact(facts, kind="stat_protection", text="Protects stats from drops", evidence_ref="lead", specificity=0.82)
    if "defense won't be lowered" in searchable or "prevents defense from being lowered" in searchable:
        _add_fact(facts, kind="defense_protection", text="Protects Defense from drops", evidence_ref="Description" if description else "lead", specificity=0.86)
    if "critical hit" in searchable and ("attack goes up sharply" in searchable or "maximum of six stages" in searchable):
        _add_fact(facts, kind="crit_rage", text="Maxes Attack after a critical hit", evidence_ref="Description" if description else "lead", specificity=0.9)
    if "blocks critical hits" in searchable or "protected against critical hits" in searchable or "never critical hits against this pokemon" in searchable:
        _add_fact(facts, kind="crit_immunity", text="Blocks critical hits", evidence_ref="Description" if description else "lead", specificity=0.88)
    if "negates all effects of weather" in searchable or "removing the effects of weather" in searchable or "weather to clear" in searchable:
        _add_fact(facts, kind="weather_nullify", text="Cancels weather effects", evidence_ref="Description" if description else "lead", specificity=0.9)
    if re.search(r"\b(weather|rain|sunlight|sandstorm|hail|snow)\b", searchable):
        _add_fact(facts, kind="weather_hook", text="Weather-linked trait", evidence_ref="lead", specificity=0.66)
    if "cannot be" in searchable and ("status" in searchable or "burned" in searchable or "paralyzed" in searchable or "poisoned" in searchable):
        _add_fact(facts, kind="status_immunity", text="Status-blocking trait", evidence_ref="lead", specificity=0.78)
    if (
        "warns" in searchable
        or "notifies all trainers" in searchable
        or "premonition" in searchable
    ) and ("supereffective" in searchable or "super-effective" in searchable or "one-hit knockout" in searchable or "one-hit ko" in searchable):
        _add_fact(facts, kind="danger_sense", text="Warns of dangerous moves", evidence_ref="Description" if description else "lead", specificity=0.82)
    if (
        "moving last" in searchable
        or "move last" in searchable
        or "acts last" in searchable
        or "after all other pokemon have made their move" in searchable
    ) and ("1.3" in searchable or "strengthens moves" in searchable or "power of its move is increased" in searchable):
        _add_fact(facts, kind="late_move_boost", text="Boosts moves when acting last", evidence_ref="Effect" if effect_section else "Description" if description else "lead", specificity=0.86)
    if "highest stat" in searchable and ("causes another pokemon" in searchable or "faints another pokemon" in searchable or "knocks out another pokemon" in searchable):
        _add_fact(facts, kind="ko_highest_stat_boost", text="Raises its highest stat after a knockout", evidence_ref="Description" if description else "lead", specificity=0.9)
    if "special attack of allies" in searchable and "special moves" in searchable:
        _add_fact(facts, kind="ally_special_boost", text="Boosts allies' Special Attack on special moves", evidence_ref="Effect" if effect_section else "lead", specificity=0.88)
    if "lowers special defense of all pokemon except itself" in searchable:
        _add_fact(facts, kind="global_stat_lower", text="Lowers others' Special Defense", evidence_ref="lead", specificity=0.9, stat="Special Defense")
    if "during harsh sunlight" in searchable and "speed stat" in searchable and "doubled" in searchable:
        _add_fact(facts, kind="weather_speed_boost", text="Doubles Speed in sunlight", evidence_ref="Effect" if effect_section else "lead", specificity=0.88)
    low_hp_type_match = re.search(r"boosts the power of ([A-Za-z-]+)-type moves when hp is low", searchable)
    if low_hp_type_match:
        move_type = low_hp_type_match.group(1).title()
        _add_fact(
            facts,
            kind="low_hp_type_boost",
            text=f"Boosts {move_type}-type moves at low HP",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
            move_type=move_type,
        )
    low_hp_stat_match = re.search(
        r"(?:raises|raised)\s+(?:this pokemon'?s\s+)?([A-Za-z. ]+?)\s+by one stage.*?(?:hp .*?below half|below half)",
        searchable,
    )
    if not low_hp_stat_match:
        low_hp_stat_match = re.search(
            r"below half.*?(?:its|this pokemon'?s)\s+([A-Za-z. ]+?)\s+is raised by one stage",
            searchable,
        )
    if low_hp_stat_match:
        stat = low_hp_stat_match.group(1).replace("sp.", "Special ").strip()
        _add_fact(
            facts,
            kind="low_hp_stat_boost",
            text=f"Raises {stat} below half HP",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
            stat=stat,
        )
    if "protects allies against moves that affect their mental state" in searchable or "taunt" in searchable and "encore" in searchable and "disable" in searchable:
        _add_fact(facts, kind="mental_guard", text="Protects allies from mental moves", evidence_ref="lead", specificity=0.84)
    if ("dark aura" in searchable or "fairy aura" in searchable) and ("reversed" in searchable or "become weak" in searchable or "weaken" in searchable):
        _add_fact(facts, kind="aura_reversal", text="Reverses dark and fairy auras", evidence_ref="Description" if description else "lead", specificity=0.9)
    transform_match = re.search(
        r"(?:change into|transforms? (?:this pokemon )?into)\s+([A-Za-z-]+).*?(?:causes another pokemon.*?to faint|after fainting an opponent|knocks out another pokemon)",
        searchable,
    )
    if transform_match:
        _add_fact(
            facts,
            kind="post_ko_transform",
            text=f"Transforms after a knockout",
            evidence_ref="Description" if description else "lead",
            specificity=0.88,
            transform_form=transform_match.group(1).title(),
        )
    if (
        "move with increased priority" in searchable
        or "priority move" in searchable
        or "moves that have priority" in searchable
        or "using any moves that have priority" in searchable
    ) and (
        "prevents the pokemon from executing that move" in searchable
        or "cannot be hit" in searchable
        or "blocked by armor tail" in searchable
        or "unaffected" in searchable
        or "prevents the opponent from using any moves that have priority" in searchable
    ):
        _add_fact(facts, kind="priority_block", text="Blocks incoming priority moves", evidence_ref="Description" if description else "lead", specificity=0.88)
    if (
        "cannot flee" in searchable
        or "prevents opposing pokemon from fleeing" in searchable
        or "prevents opponents from fleeing" in searchable
        or "prevents all grounded adjacent opponents from fleeing" in searchable
        or ("switching out" in searchable and "fleeing" in searchable)
        or "can't escape" in searchable
    ):
        _add_fact(facts, kind="trapping_ability", text="Prevents escape", evidence_ref="Description" if description else "lead", specificity=0.84)
    if "pick up the same type of ball as the first one thrown" in searchable or "fetch the pok ball from the first failed throw" in searchable:
        _add_fact(facts, kind="ball_retrieve", text="Retrieves the first failed Poke Ball", evidence_ref="Effect" if effect_section else "lead", specificity=0.88)
    if ("dondozo" in searchable and "mouth" in searchable) or "same side of the field as a dondozo" in searchable:
        _add_fact(facts, kind="commander_pair", text="Powers up Dondozo from inside its mouth", evidence_ref="Effect" if effect_section else "lead", specificity=0.9)
    if "copies" in searchable and "stat changes" in searchable and ("ally" in searchable or "teammate" in searchable):
        _add_fact(
            facts,
            kind="ally_stat_copy",
            text="Copies an ally's stat changes on entry",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.9,
        )
    if ("raises attack after knocking out" in searchable or "boosts attack after knocking out" in searchable or "when it knocks out a target" in searchable and "attack" in searchable):
        _add_fact(
            facts,
            kind="ko_attack_boost",
            text="Raises Attack after a knockout",
            evidence_ref="Effect" if effect_section else "Description" if description else "lead",
            specificity=0.9,
        )
    return facts


def _extract_location_facts(
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    answer_display = _clean_text(str(answer_row.get("answerDisplay") or "")).upper()
    source_display_name = _clean_text(str(answer_row.get("sourceDisplayName") or ""))
    lead = _clean_text(str((evidence or {}).get("leadText") or ""))
    page_title = _clean_text(str((evidence or {}).get("pageTitle") or ""))
    region = str(structured_facts.get("regionDisplay") or structured_facts.get("region") or "")
    if region:
        _add_fact(facts, kind="region", text=f"{region} location", evidence_ref="lead", specificity=0.5, region=region)
    if lead:
        kind_match = re.search(r"\bis (?:an?|the)?\s*([a-z-]+)\b", lead.lower())
        if kind_match:
            kind = kind_match.group(1)
            if kind in LOCATION_KIND_TERMS:
                _add_fact(
                    facts,
                    kind="location_kind",
                    text=f"{kind} landmark",
                    evidence_ref="lead",
                    specificity=0.68,
                    location_kind=kind,
                )
        for kind in ("town", "city", "village", "gate", "house", "cave", "cavern", "forest", "meadow", "route", "tunnel", "tower", "island"):
            if kind in lead.lower():
                _add_fact(
                    facts,
                    kind="location_kind",
                    text=f"{kind} landmark",
                    evidence_ref="lead",
                    specificity=0.64,
                    location_kind=kind,
                )
        route_match = re.search(
            r"(?:located|lives|found)[^.]*?\b(Route \d+)\b",
            lead,
            re.IGNORECASE,
        )
        if route_match:
            _add_fact(
                facts,
                kind="route_location",
                text=f"Site on {route_match.group(1)}",
                evidence_ref="lead",
                specificity=0.86,
                route=route_match.group(1),
            )
        if "small house on the beach" in lead.lower() or ("house" in lead.lower() and "beach" in lead.lower()):
            _add_fact(
                facts,
                kind="beach_house",
                text="Beach house",
                evidence_ref="lead",
                specificity=0.9,
            )
        if "footprint ribbon" in lead.lower():
            _add_fact(
                facts,
                kind="ribbon_reward",
                text="Home of the Footprint Ribbon",
                evidence_ref="lead",
                specificity=0.92,
            )
        if "friendly pok" in lead.lower():
            _add_fact(
                facts,
                kind="friendship_reward",
                text="Ribbon for friendly Pokemon",
                evidence_ref="lead",
                specificity=0.82,
            )
        if "groudon/kyogre and rayquaza rest" in lead.lower():
            _add_fact(
                facts,
                kind="legendary_rest",
                text="Resting place of Groudon, Kyogre, and Rayquaza",
                evidence_ref="lead",
                specificity=0.94,
            )
        if "wrecked ship" in lead.lower():
            _add_fact(
                facts,
                kind="shipwreck",
                text="wrecked ship",
                evidence_ref="lead",
                specificity=0.9,
            )
        if "can only be accessed by using dive" in lead.lower() or "accessed through the use of dive" in lead.lower():
            _add_fact(
                facts,
                kind="dive_access",
                text="Partly reached by Dive",
                evidence_ref="lead",
                specificity=0.82,
            )
        if "sunken temple ruins" in lead.lower():
            _add_fact(
                facts,
                kind="sunken_ruins",
                text="sunken temple ruins",
                evidence_ref="lead",
                specificity=0.9,
            )
        elif "ruins" in lead.lower():
            _add_fact(
                facts,
                kind="ruins",
                text="ancient ruins",
                evidence_ref="lead",
                specificity=0.72,
            )
        if "bay" in lead.lower():
            _add_fact(
                facts,
                kind="bay_site",
                text="bay landmark",
                evidence_ref="lead",
                specificity=0.64,
            )
        if "town" in lead.lower():
            _add_fact(
                facts,
                kind="near_town",
                text="near a regional town",
                evidence_ref="lead",
                specificity=0.58,
            )
        if "island" in lead.lower():
            _add_fact(
                facts,
                kind="island_site",
                text="island location",
                evidence_ref="lead",
                specificity=0.66,
            )
        if "city" in lead.lower():
            _add_fact(
                facts,
                kind="city_site",
                text="urban landmark",
                evidence_ref="lead",
                specificity=0.56,
            )
        if "tower" in lead.lower() or "tower" in page_title.lower():
            _add_fact(
                facts,
                kind="tower_site",
                text="tower landmark",
                evidence_ref="lead",
                specificity=0.74,
            )
        if "contains the scanner" in lead.lower():
            _add_fact(
                facts,
                kind="contains_scanner",
                text="Hides the Scanner",
                evidence_ref="lead",
                specificity=0.84,
            )
        if "sea mauville takes the place" in lead.lower():
            _add_fact(
                facts,
                kind="replaced_site",
                text="Replaced by Sea Mauville",
                evidence_ref="lead",
                specificity=0.78,
            )
    titleish = " ".join(part for part in [answer_display, source_display_name, page_title] if part).lower()
    if " mine" in f" {titleish} ":
        _add_fact(facts, kind="location_kind", text="mine landmark", evidence_ref="title", specificity=0.68, location_kind="mine")
    if "cafe" in titleish:
        _add_fact(facts, kind="location_kind", text="cafe landmark", evidence_ref="title", specificity=0.68, location_kind="cafe")
    if "villa" in titleish:
        _add_fact(facts, kind="location_kind", text="villa landmark", evidence_ref="title", specificity=0.68, location_kind="villa")
    if titleish.startswith("roaming ") or "(roaming)" in titleish:
        _add_fact(facts, kind="roaming_zone", text="Regional roaming area", evidence_ref="title", specificity=0.72)
    return facts


def extract_clue_facts(
    *,
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
) -> dict[str, Any]:
    source_type = str(answer_row.get("sourceType") or structured_facts.get("sourceType") or "")
    if source_type == "pokemon-species":
        facts = _extract_species_facts(answer_row, evidence, structured_facts)
    elif source_type == "move":
        facts = _extract_move_facts(answer_row, evidence, structured_facts)
    elif source_type == "item":
        facts = _extract_item_facts(answer_row, evidence, structured_facts)
    elif source_type == "ability":
        facts = _extract_ability_facts(evidence, structured_facts)
        non_title_facts = [fact for fact in facts if str(fact.get("kind") or "") != "ability_generation"]
        if len(non_title_facts) < 2:
            display = str(answer_row.get("answerDisplay") or "").strip().upper()
            semantic = ABILITY_TITLE_SEMANTICS.get(display)
            if semantic:
                _add_fact(
                    facts,
                    kind="title_semantic",
                    text=f"{semantic} trait",
                    evidence_ref="title",
                    specificity=0.62,
                    semantic=semantic,
                )
    elif source_type in {"location", "location-area"}:
        facts = _extract_location_facts(answer_row, evidence, structured_facts)
    else:
        facts = []
    return {
        "answerKey": str(answer_row.get("answerKey") or "").upper(),
        "sourceType": source_type,
        "facts": facts,
    }
