from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from difficulty_store import load_difficulty
from healthcare_system import get_sickness_rating

RISK_MODES = {
    "safe": {"label": "Safe", "dc": 8, "multiplier": 0.8},
    "default": {"label": "Default", "dc": 12, "multiplier": 1.0},
    "risky": {"label": "Risky", "dc": 16, "multiplier": 1.5},
}


class ExtendedSystemsStore:
    def __init__(self, path: str | Path = "systems_state.json") -> None:
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

    def _defaults(self, difficulty_id: str) -> dict[str, Any]:
        try:
            difficulty = load_difficulty(difficulty_id)
        except ValueError:
            difficulty_id = "normal"
            difficulty = load_difficulty(difficulty_id)
        expedition_rules = difficulty.get("expeditions", {})
        outpost_rules = difficulty.get("outposts", {})
        healthcare_rules = difficulty.get("healthcare", {})
        return {
            "difficulty": difficulty_id,
            "void_exposure": 0.0,
            "weekly_void_exposure": 0,
            "patients": 0,
            "healthcare_capacity": max(0, int(healthcare_rules.get("starting_capacity", 0))),
            "expeditions": {
                "warriors": max(
                    1, int(expedition_rules.get("default_warriors_per_expedition", 3))
                ),
                "risk_mode": str(expedition_rules.get("default_risk_mode", "default")),
                "roll_modifier": int(expedition_rules.get("default_roll_modifier", 0)),
            },
            "outposts": {
                # Outposts no longer have a separate unlock switch. Count 0 means none.
                "unlocked": True,
                "count": 0,
                "warriors_per_outpost": max(
                    1, int(outpost_rules.get("default_warriors_per_outpost", 5))
                ),
                "risk_mode": str(outpost_rules.get("default_risk_mode", "default")),
            },
            "last_summary": {},
        }

    def _normalize(self, source: Any, difficulty_id: str = "normal") -> dict[str, Any]:
        source = source if isinstance(source, dict) else {}
        difficulty_id = str(source.get("difficulty", difficulty_id))
        default = self._defaults(difficulty_id)

        expeditions_source = source.get("expeditions", {})
        if not isinstance(expeditions_source, dict):
            expeditions_source = {}
        expedition_default = default["expeditions"]
        expedition_mode = str(
            expeditions_source.get("risk_mode", expedition_default["risk_mode"])
        ).lower()
        if expedition_mode not in RISK_MODES:
            expedition_mode = "default"

        # Migration: older saves called this warriors_per_expedition and also
        # stored a planned expedition count. Expeditions are now one recurring
        # weekly action, so only the Warrior count and risk setting remain.
        expedition_warriors = max(
            1,
            int(
                expeditions_source.get(
                    "warriors",
                    expeditions_source.get(
                        "warriors_per_expedition",
                        expedition_default["warriors"],
                    ),
                )
            ),
        )
        expedition_roll_modifier = int(
            expeditions_source.get(
                "roll_modifier",
                expedition_default.get("roll_modifier", 0),
            )
        )

        outposts_source = source.get("outposts", {})
        if not isinstance(outposts_source, dict):
            outposts_source = {}
        outpost_default = default["outposts"]
        outpost_mode = str(outposts_source.get("risk_mode", outpost_default["risk_mode"])).lower()
        if outpost_mode not in RISK_MODES:
            outpost_mode = "default"

        normalized = {
            "difficulty": difficulty_id,
            "void_exposure": max(0.0, min(100.0, float(source.get("void_exposure", 0.0)))),
            "weekly_void_exposure": int(source.get("weekly_void_exposure", 0)),
            "patients": max(0, int(source.get("patients", 0))),
            "healthcare_capacity": max(
                0, int(source.get("healthcare_capacity", default["healthcare_capacity"]))
            ),
            "expeditions": {
                "warriors": expedition_warriors,
                "risk_mode": expedition_mode,
                "roll_modifier": expedition_roll_modifier,
            },
            "outposts": {
                # Older saves may contain unlocked=false. Ignore it now.
                "unlocked": True,
                "count": max(0, int(outposts_source.get("count", 0))),
                "warriors_per_outpost": max(
                    1,
                    int(
                        outposts_source.get(
                            "warriors_per_outpost",
                            outpost_default["warriors_per_outpost"],
                        )
                    ),
                ),
                "risk_mode": outpost_mode,
            },
            "last_summary": source.get("last_summary", {})
            if isinstance(source.get("last_summary", {}), dict)
            else {},
        }
        for key in ("channel_id", "message_id"):
            if source.get(key) is not None:
                try:
                    normalized[key] = int(source[key])
                except (TypeError, ValueError):
                    pass
        return normalized

    def get(self, guild_id: int, difficulty_id: str = "normal") -> dict[str, Any]:
        data = self._load_all()
        return self._normalize(data.get(str(guild_id)), difficulty_id)

    def save(self, guild_id: int, entry: dict[str, Any]) -> dict[str, Any]:
        data = self._load_all()
        normalized = self._normalize(entry, str(entry.get("difficulty", "normal")))
        data[str(guild_id)] = normalized
        self._save_all(data)
        return normalized

    def reset(self, guild_id: int, difficulty_id: str) -> dict[str, Any]:
        old = self.get(guild_id, difficulty_id)
        entry = self._defaults(difficulty_id)
        for key in ("channel_id", "message_id"):
            if key in old:
                entry[key] = old[key]
        return self.save(guild_id, entry)

    def set_message(self, guild_id: int, channel_id: int, message_id: int, difficulty_id: str) -> dict[str, Any]:
        entry = self.get(guild_id, difficulty_id)
        entry["channel_id"] = int(channel_id)
        entry["message_id"] = int(message_id)
        return self.save(guild_id, entry)

    def configure_expeditions(
        self,
        guild_id: int,
        difficulty_id: str,
        *,
        warriors: int,
        risk_mode: str,
        roll_modifier: int,
    ) -> dict[str, Any]:
        entry = self.get(guild_id, difficulty_id)
        mode = str(risk_mode).lower()
        if mode not in RISK_MODES:
            raise ValueError("Unknown expedition risk mode")
        entry["expeditions"] = {
            "warriors": max(1, int(warriors)),
            "risk_mode": mode,
            "roll_modifier": int(roll_modifier),
        }
        return self.save(guild_id, entry)

    def configure_outposts(
        self,
        guild_id: int,
        difficulty_id: str,
        *,
        unlocked: bool = True,
        count: int,
        warriors_per_outpost: int,
        risk_mode: str,
    ) -> dict[str, Any]:
        entry = self.get(guild_id, difficulty_id)
        mode = str(risk_mode).lower()
        if mode not in RISK_MODES:
            raise ValueError("Unknown outpost risk mode")
        entry["outposts"] = {
            "unlocked": True,
            "count": max(0, int(count)),
            "warriors_per_outpost": max(1, int(warriors_per_outpost)),
            "risk_mode": mode,
        }
        return self.save(guild_id, entry)

    def configure_healthcare(
        self,
        guild_id: int,
        difficulty_id: str,
        *,
        patients: int,
        capacity: int,
    ) -> dict[str, Any]:
        entry = self.get(guild_id, difficulty_id)
        entry["patients"] = max(0, int(patients))
        entry["healthcare_capacity"] = max(0, int(capacity))
        return self.save(guild_id, entry)

    def set_void_exposure(self, guild_id: int, difficulty_id: str, value: float) -> dict[str, Any]:
        entry = self.get(guild_id, difficulty_id)
        entry["void_exposure"] = max(0.0, min(100.0, float(value)))
        return self.save(guild_id, entry)

    def set_weekly_void_exposure(
        self,
        guild_id: int,
        difficulty_id: str,
        value: int,
    ) -> dict[str, Any]:
        entry = self.get(guild_id, difficulty_id)
        entry["weekly_void_exposure"] = int(value)
        return self.save(guild_id, entry)

    def enrich(self, guild_id: int, state: dict[str, Any]) -> dict[str, Any]:
        result = dict(state)
        ext = self.get(guild_id, str(state.get("difficulty", "normal")))
        citizens = max(0, int(result.get("citizens", 0)))
        ext["patients"] = min(max(0, int(ext.get("patients", 0))), citizens)
        result["patients"] = ext["patients"]
        result["healthcare_capacity"] = max(0, int(ext.get("healthcare_capacity", 0)))
        result["void_exposure"] = max(0.0, min(100.0, float(ext.get("void_exposure", 0.0))))
        result["sickness"] = get_sickness_rating(result)
        return result


systems_store = ExtendedSystemsStore()
