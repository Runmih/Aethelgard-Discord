from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DIFFICULTY_DIR = Path("content/difficulties")


def load_difficulty(difficulty_id: str) -> dict[str, Any]:
    path = DIFFICULTY_DIR / f"{difficulty_id}.json"
    if not path.exists():
        raise ValueError(f"Unknown difficulty: {difficulty_id}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Could not load difficulty: {difficulty_id}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Difficulty file is invalid: {difficulty_id}")
    return data


def list_difficulties() -> list[dict[str, str]]:
    difficulties: list[dict[str, str]] = []
    if not DIFFICULTY_DIR.exists():
        return difficulties

    for path in sorted(DIFFICULTY_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue

        difficulty_id = str(data.get("id", path.stem))
        difficulties.append(
            {
                "id": difficulty_id,
                "name": str(data.get("name", difficulty_id.title())),
                "description": str(data.get("description", "")),
            }
        )

    return difficulties


def get_void_era(difficulty: dict[str, Any], week: int) -> dict[str, Any]:
    progression = difficulty.get("void_progression", {})
    eras = progression.get("eras", [])
    if not isinstance(eras, list):
        return {}

    for era in eras:
        if not isinstance(era, dict):
            continue
        start = int(era.get("start_week", 1))
        end_raw = era.get("end_week")
        end = int(end_raw) if end_raw is not None else None
        if week >= start and (end is None or week <= end):
            return era

    return {}
