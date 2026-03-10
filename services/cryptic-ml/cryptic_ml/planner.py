from __future__ import annotations

import hashlib
import random

from cryptic_ml.models import ClueCandidate, CluePlan, LexiconEntry

SOURCE_DEFINITIONS = {
    "pokemon-species": "creature",
    "move": "battle technique",
    "item": "held object",
    "location": "regional area",
    "location-area": "regional area",
    "ability": "innate trait",
    "type": "elemental affinity",
}

INDICATORS = {
    "charade": ("from", "via", "using", "after"),
    "anagram": ("mixed", "scrambled", "reordered", "shuffled"),
    "hidden": ("hidden in", "concealed in", "inside", "found in"),
    "deletion": ("dropping", "losing", "removing", "taking out"),
    "container": ("around", "holding", "containing", "about"),
}

SURFACE_PREFIXES = ("strange", "brief", "noted", "casual", "rapid", "odd")
SURFACE_SUFFIXES = ("report", "remark", "phrase", "comment", "snippet", "line")
CHARADE_SURFACES = (
    "{definition} from bits {components} {indicator} joined",
    "{definition} formed by {indicator} joining {components}",
    "{definition} from assembled bits {components} {indicator}",
    "{definition} built with {components} {indicator} linked",
    "{definition} from fragments {components} {indicator} combined",
)
ANAGRAM_SURFACES_START = (
    "{definition} from {indicator} {fodder}",
    "{definition} appears if {fodder} is {indicator}",
    "{definition} when {fodder} is {indicator}",
)
ANAGRAM_SURFACES_END = (
    "{indicator_cap} {fodder} for {definition}",
    "{fodder} {indicator} gives {definition}",
    "When {fodder} is {indicator}, you get {definition}",
    "{fodder} {indicator} to make {definition}",
    "Rework {fodder} for {definition}",
)
HIDDEN_SURFACES_START = (
    "{definition} found {indicator} {surface}",
    "{definition} located {indicator} {surface}",
    "{definition} spotted {indicator} {surface}",
)
HIDDEN_SURFACES_END = (
    "{indicator_cap} {surface} gives {definition}",
    "In {surface} sits {definition}",
    "{surface_cap} conceals {definition}",
    "{surface_cap} hides {definition}",
    "Buried {indicator} {surface} is {definition}",
)
DELETION_SURFACES_START = (
    "{definition} after {indicator} {remove} from {fodder}",
    "{definition} from {fodder} with {remove} {indicator}",
    "{definition} once {remove} is {indicator} from {fodder}",
    "{definition} with {remove} {indicator} in {fodder}",
    "{definition} by {indicator} {remove} from {fodder}",
)
DELETION_SURFACES_END = (
    "{indicator_cap} {remove} from {fodder} gives {definition}",
    "If {remove} is {indicator} from {fodder}, it becomes {definition}",
    "{fodder} with {remove} {indicator} reveals {definition}",
)


def _definition_for_entry(entry: LexiconEntry) -> str:
    return SOURCE_DEFINITIONS.get(entry.source_type, "Pokemon term")


def _seed_for(entry: LexiconEntry, mechanism: str) -> int:
    digest = hashlib.sha256(f"{entry.answer_key}:{mechanism}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _seed_for_answer(answer_key: str, mechanism: str) -> int:
    digest = hashlib.sha256(f"{answer_key}:{mechanism}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _pick(values: tuple[str, ...], seed: int, offset: int = 0) -> str:
    return values[(seed + offset) % len(values)]


def _chunk_answer(answer: str) -> str:
    if len(answer) <= 4:
        return answer
    step = 2 if len(answer) <= 8 else 3
    return " ".join(answer[i : i + step] for i in range(0, len(answer), step))


def _scrambled_letters(answer: str, seed: int) -> str:
    letters = list(answer)
    rng = random.Random(seed)
    original = "".join(letters)
    for _ in range(8):
        rng.shuffle(letters)
        scrambled = "".join(letters)
        if scrambled != original:
            return scrambled
    return original[1:] + original[:1]


def _deletion_fodder(answer: str, seed: int) -> tuple[str, str]:
    if len(answer) < 3:
        return answer, ""
    remove_index = seed % len(answer)
    remove_letter = answer[remove_index]
    # Insert in the middle so the full answer is not trivially visible.
    insert_at = max(1, min(len(answer) - 1, len(answer) // 2))
    fodder = answer[:insert_at] + remove_letter + answer[insert_at:]
    return fodder, remove_letter


def _realize_surface(plan: CluePlan, mechanism_seed: int) -> tuple[str, str]:
    indicator = plan.metadata.get("indicator", "with")
    definition = plan.definition.lower()
    definition_position = plan.metadata.get("definitionPosition", "start")

    if plan.mechanism == "charade":
        components = " + ".join(plan.metadata.get("components", "").split("|"))
        template = CHARADE_SURFACES[mechanism_seed % len(CHARADE_SURFACES)]
        clue = template.format(definition=plan.definition, components=components, indicator=indicator)
        return clue, f"charade_{(mechanism_seed % len(CHARADE_SURFACES)) + 1}"

    if plan.mechanism == "anagram":
        fodder = plan.metadata.get("fodder", "letters")
        templates = ANAGRAM_SURFACES_END if definition_position == "end" else ANAGRAM_SURFACES_START
        template = templates[mechanism_seed % len(templates)]
        clue = template.format(
            definition=definition,
            fodder=fodder,
            indicator=indicator,
            indicator_cap=indicator.capitalize(),
        )
        return clue, f"anagram_{(mechanism_seed % len(templates)) + 1}"

    if plan.mechanism == "hidden":
        surface = plan.metadata.get("surface", "surface text")
        templates = HIDDEN_SURFACES_END if definition_position == "end" else HIDDEN_SURFACES_START
        template = templates[mechanism_seed % len(templates)]
        clue = template.format(
            definition=definition,
            surface=surface,
            surface_cap=surface.capitalize(),
            indicator=indicator,
            indicator_cap=indicator.capitalize(),
        )
        return clue, f"hidden_{(mechanism_seed % len(templates)) + 1}"

    if plan.mechanism == "deletion":
        fodder = plan.metadata.get("fodder", "letters")
        remove = plan.metadata.get("remove", "X")
        templates = DELETION_SURFACES_END if definition_position == "end" else DELETION_SURFACES_START
        template = templates[mechanism_seed % len(templates)]
        clue = template.format(
            definition=plan.definition,
            fodder=fodder,
            remove=remove,
            indicator=indicator,
            indicator_cap=indicator.capitalize(),
        )
        return clue, f"deletion_{(mechanism_seed % len(templates)) + 1}"

    return f"{plan.definition} by wordplay", "fallback_1"


def build_plans_for_entry(entry: LexiconEntry) -> list[CluePlan]:
    definition = _definition_for_entry(entry)
    plans: list[CluePlan] = []

    if entry.is_multiword and len(entry.answer_tokens) >= 2:
        seed = _seed_for(entry, "charade")
        indicator = _pick(INDICATORS["charade"], seed)
        plans.append(
            CluePlan(
                answer_key=entry.answer_key,
                answer=entry.answer,
                enumeration=entry.enumeration,
                definition=definition,
                mechanism="charade",
                wordplay=f"charade components: {' + '.join(entry.answer_tokens)}",
                metadata={
                    "definitionPosition": "start",
                    "indicator": indicator,
                    "components": "|".join(entry.answer_tokens),
                },
            )
        )

    if 6 <= len(entry.answer_key) <= 12:
        seed = _seed_for(entry, "anagram")
        indicator = _pick(INDICATORS["anagram"], seed)
        fodder = _scrambled_letters(entry.answer_key, seed)
        plans.append(
            CluePlan(
                answer_key=entry.answer_key,
                answer=entry.answer,
                enumeration=entry.enumeration,
                definition=definition,
                mechanism="anagram",
                wordplay=f"anagram fodder: {fodder}",
                metadata={
                    "definitionPosition": "end",
                    "indicator": indicator,
                    "fodder": fodder,
                },
            )
        )

    if 4 <= len(entry.answer_key) <= 10:
        seed = _seed_for(entry, "hidden")
        indicator = _pick(INDICATORS["hidden"], seed)
        prefix = _pick(SURFACE_PREFIXES, seed)
        suffix = _pick(SURFACE_SUFFIXES, seed, offset=3)
        surface = f"{prefix} {_chunk_answer(entry.answer_key)} {suffix}"
        plans.append(
            CluePlan(
                answer_key=entry.answer_key,
                answer=entry.answer,
                enumeration=entry.enumeration,
                definition=definition,
                mechanism="hidden",
                wordplay=f"hidden sequence in: {surface}",
                metadata={
                    "definitionPosition": "end",
                    "indicator": indicator,
                    "surface": surface,
                },
            )
        )

    if len(entry.answer_key) >= 6:
        seed = _seed_for(entry, "deletion")
        indicator = _pick(INDICATORS["deletion"], seed)
        fodder, remove = _deletion_fodder(entry.answer_key, seed)
        plans.append(
            CluePlan(
                answer_key=entry.answer_key,
                answer=entry.answer,
                enumeration=entry.enumeration,
                definition=definition,
                mechanism="deletion",
                wordplay=f"delete '{remove}' from {fodder}",
                metadata={
                    "definitionPosition": "start",
                    "indicator": indicator,
                    "fodder": fodder,
                    "remove": remove,
                },
            )
        )

    return plans


def realize_candidate(plan: CluePlan) -> ClueCandidate:
    mechanism_seed = _seed_for_answer(plan.answer_key, plan.mechanism)
    clue, variant = _realize_surface(plan, mechanism_seed)

    return ClueCandidate(
        answer_key=plan.answer_key,
        clue=clue,
        enumeration=plan.enumeration,
        mechanism=plan.mechanism,
        definition=plan.definition,
        plan_wordplay=plan.wordplay,
        metadata={**plan.metadata, "surfaceVariant": variant},
    )
