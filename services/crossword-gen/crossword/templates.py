from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class Template:
    name: str
    width: int
    height: int
    blocks: set[tuple[int, int]]


def load_template(path: Path) -> Template:
    data = json.loads(path.read_text())
    required = {"name", "width", "height", "blocks"}
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"template_json_missing_keys:{','.join(sorted(missing))}")
    blocks = {(cell[0], cell[1]) for cell in data.get("blocks", [])}
    return Template(
        name=data["name"],
        width=data["width"],
        height=data["height"],
        blocks=blocks,
    )


def load_templates(dir_path: Path) -> list[Template]:
    templates: list[Template] = []
    for path in sorted(dir_path.glob("*.json")):
        try:
            templates.append(load_template(path))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return templates
