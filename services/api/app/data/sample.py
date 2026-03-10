from __future__ import annotations

import copy

def redact_puzzle(puzzle: dict) -> dict:
    sanitized = copy.deepcopy(puzzle)
    grid = sanitized.get("grid", {})
    for cell in grid.get("cells", []):
        if not cell.get("isBlock", False):
            cell["solution"] = None
    for entry in sanitized.get("entries", []):
        entry["answer"] = ""
    if sanitized.get("gameType") == "connections":
        metadata = sanitized.get("metadata", {})
        if isinstance(metadata, dict):
            connections = metadata.get("connections")
            if isinstance(connections, dict):
                tiles = connections.get("tiles")
                if isinstance(tiles, list):
                    for tile in tiles:
                        if isinstance(tile, dict):
                            tile["groupId"] = None
                groups = connections.get("groups")
                if isinstance(groups, list):
                    for group in groups:
                        if isinstance(group, dict):
                            group["labels"] = []
    return sanitized
