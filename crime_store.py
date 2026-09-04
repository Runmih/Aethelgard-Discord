from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CrimeStore:
    def __init__(self, path: str | Path = "crime_state.json") -> None:
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
        pending = source.get("pending")
        return {"pending": dict(pending) if isinstance(pending, dict) else None}

    def set_pending(self, guild_id: int, event: dict[str, Any]) -> dict[str, Any]:
        data = self._load_all()
        entry = {"pending": dict(event)}
        data[str(guild_id)] = entry
        self._save_all(data)
        return entry

    def clear_pending(self, guild_id: int) -> dict[str, Any]:
        data = self._load_all()
        entry = {"pending": None}
        data[str(guild_id)] = entry
        self._save_all(data)
        return entry

    def reset(self, guild_id: int) -> dict[str, Any]:
        return self.clear_pending(guild_id)


crime_store = CrimeStore()
