from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EventStore:
    def __init__(self, path: str | Path = "event_state.json") -> None:
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
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, guild_id: int) -> dict[str, Any]:
        source = self._load_all().get(str(guild_id), {})
        source = source if isinstance(source, dict) else {}
        result: dict[str, Any] = {"deaths": max(0, int(source.get("deaths", 0)))}
        for key in ("channel_id", "message_id"):
            if source.get(key) is not None:
                try:
                    result[key] = int(source[key])
                except (TypeError, ValueError):
                    pass
        return result

    def set_message(self, guild_id: int, channel_id: int, message_id: int) -> dict[str, Any]:
        data = self._load_all()
        entry = self.get(guild_id)
        entry["channel_id"] = int(channel_id)
        entry["message_id"] = int(message_id)
        data[str(guild_id)] = entry
        self._save_all(data)
        return entry

    def add_deaths(self, guild_id: int, amount: int) -> dict[str, Any]:
        data = self._load_all()
        entry = self.get(guild_id)
        entry["deaths"] = max(0, int(entry.get("deaths", 0)) + int(amount))
        data[str(guild_id)] = entry
        self._save_all(data)
        return entry

    def reset(self, guild_id: int) -> dict[str, Any]:
        data = self._load_all()
        old = self.get(guild_id)
        entry: dict[str, Any] = {"deaths": 0}
        for key in ("channel_id", "message_id"):
            if key in old:
                entry[key] = old[key]
        data[str(guild_id)] = entry
        self._save_all(data)
        return entry
