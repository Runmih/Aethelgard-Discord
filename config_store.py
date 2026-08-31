from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_GAME_STATE = {
    "week": 1,
    "food": 2000,
    "materials": 500,
    "citizens": 20,
    "faith": 50,
    "corruption": 20,
}


class InterfaceStore:
    def __init__(self, path: str | Path = "state.json") -> None:
        self.path = Path(path)

    def _load_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

        return data if isinstance(data, dict) else {}

    def _save_all(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _normalize(self, entry: dict[str, Any] | None) -> dict[str, Any]:
        normalized: dict[str, Any] = dict(DEFAULT_GAME_STATE)
        if isinstance(entry, dict):
            normalized.update(entry)
        return normalized

    def get(self, guild_id: int) -> dict[str, Any] | None:
        entry = self._load_all().get(str(guild_id))
        if entry is None:
            return None
        return self._normalize(entry)

    def set(self, guild_id: int, channel_id: int, message_id: int) -> dict[str, Any]:
        """Save the interface location while preserving all game-state values."""
        data = self._load_all()
        key = str(guild_id)
        entry = self._normalize(data.get(key))
        entry["channel_id"] = channel_id
        entry["message_id"] = message_id
        data[key] = entry
        self._save_all(data)
        return entry

    def advance_week(self, guild_id: int) -> tuple[dict[str, Any], int]:
        """Advance one week and consume 10 Food per citizen."""
        data = self._load_all()
        key = str(guild_id)
        entry = self._normalize(data.get(key))

        citizens = max(0, int(entry.get("citizens", 0)))
        food_cost = citizens * 10

        entry["week"] = max(1, int(entry.get("week", 1))) + 1
        entry["food"] = max(0, int(entry.get("food", 0)) - food_cost)

        data[key] = entry
        self._save_all(data)
        return entry, food_cost

    def reset_game(
        self,
        guild_id: int,
        *,
        food: int,
        materials: int,
        citizens: int,
        faith: int,
        corruption: int,
    ) -> dict[str, Any]:
        """Reset game variables to a fresh Week 1 while preserving interface IDs."""
        data = self._load_all()
        key = str(guild_id)
        old_entry = data.get(key, {})

        entry: dict[str, Any] = {
            "week": 1,
            "food": food,
            "materials": materials,
            "citizens": citizens,
            "faith": faith,
            "corruption": corruption,
        }

        if isinstance(old_entry, dict):
            if "channel_id" in old_entry:
                entry["channel_id"] = old_entry["channel_id"]
            if "message_id" in old_entry:
                entry["message_id"] = old_entry["message_id"]

        data[key] = entry
        self._save_all(data)
        return self._normalize(entry)
