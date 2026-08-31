from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class InterfaceConfig(TypedDict):
    channel_id: int
    message_id: int


class InterfaceStore:
    def __init__(self, path: str | Path = "state.json") -> None:
        self.path = Path(path)

    def _load_all(self) -> dict[str, InterfaceConfig]:
        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

        return data if isinstance(data, dict) else {}

    def _save_all(self, data: dict[str, InterfaceConfig]) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, guild_id: int) -> InterfaceConfig | None:
        return self._load_all().get(str(guild_id))

    def set(self, guild_id: int, channel_id: int, message_id: int) -> None:
        data = self._load_all()
        data[str(guild_id)] = {
            "channel_id": channel_id,
            "message_id": message_id,
        }
        self._save_all(data)
