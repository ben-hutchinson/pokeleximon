"""seed sample puzzle

Revision ID: 0002_seed_sample
Revises: 0001_initial
Create Date: 2026-02-10
"""

from __future__ import annotations

import datetime as dt

from alembic import op
import sqlalchemy as sa


revision = "0002_seed_sample"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


SAMPLE_ID = "puz_3f3c2a2e"
SAMPLE_DATE = dt.date(2026, 2, 10)
PUBLISHED_AT = dt.datetime(2026, 2, 10, 0, 0, 0, tzinfo=dt.timezone.utc)

GRID = {
    "width": 15,
    "height": 15,
    "cells": [
        {"x": 0, "y": 0, "isBlock": False, "solution": "P", "entryIdAcross": "a1", "entryIdDown": "d1"},
        {"x": 1, "y": 0, "isBlock": False, "solution": "I", "entryIdAcross": "a1", "entryIdDown": None},
        {"x": 2, "y": 0, "isBlock": False, "solution": "K", "entryIdAcross": "a1", "entryIdDown": None},
        {"x": 3, "y": 0, "isBlock": False, "solution": "A", "entryIdAcross": "a1", "entryIdDown": None},
        {"x": 4, "y": 0, "isBlock": False, "solution": "C", "entryIdAcross": "a1", "entryIdDown": None},
        {"x": 5, "y": 0, "isBlock": False, "solution": "H", "entryIdAcross": "a1", "entryIdDown": None},
        {"x": 6, "y": 0, "isBlock": False, "solution": "U", "entryIdAcross": "a1", "entryIdDown": None},
    ],
}

ENTRIES = [
    {
        "id": "a1",
        "direction": "across",
        "number": 1,
        "answer": "PIKACHU",
        "clue": "Electric-type mascot",
        "length": 7,
        "cells": [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0]],
        "sourceRef": "pokemon/25",
    }
]

METADATA = {
    "difficulty": "easy",
    "themeTags": ["electric", "mascot"],
    "source": "pokeapi",
    "generatorVersion": "0.1.0",
}


def upgrade() -> None:
    puzzles = sa.table(
        "puzzles",
        sa.column("id", sa.String),
        sa.column("date", sa.Date),
        sa.column("game_type", sa.String),
        sa.column("title", sa.String),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("timezone", sa.String),
        sa.column("grid", sa.JSON),
        sa.column("entries", sa.JSON),
        sa.column("metadata", sa.JSON),
    )

    op.execute(
        puzzles.insert().values(
            id=SAMPLE_ID,
            date=SAMPLE_DATE,
            game_type="crossword",
            title="Electric Sparks",
            published_at=PUBLISHED_AT,
            timezone="Europe/London",
            grid=GRID,
            entries=ENTRIES,
            metadata=METADATA,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM puzzles WHERE id = :id").bindparams(id=SAMPLE_ID)
    )
