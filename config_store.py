from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


DEFAULT_WEEKLY_CHANGES = {
    "food": 0,
    "materials": 0,
    "faith": 0,
    "corruption": 0,
    "birthrate": 0,
    "growth": 1,
}

DEFAULT_GAME_STATE = {
    "week": 1,
    "food": 2000,
    "materials": 500,
    "citizens": 20,
    "children": 0,
    "faith": 50,
    "corruption": 20,
    "birthrate": 0,
    "growth": 0,
    "weekly": dict(DEFAULT_WEEKLY_CHANGES),
    "votes": {},
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
        source = entry if isinstance(entry, dict) else {}
        source_weekly = source.get("weekly", {})
        if not isinstance(source_weekly, dict):
            source_weekly = {}

        weekly = {
            key: int(source_weekly.get(key, default))
            for key, default in DEFAULT_WEEKLY_CHANGES.items()
        }

        normalized: dict[str, Any] = {
            "week": int(source.get("week", DEFAULT_GAME_STATE["week"])),
            "food": max(0, int(source.get("food", DEFAULT_GAME_STATE["food"]))),
            "materials": max(0, int(source.get("materials", DEFAULT_GAME_STATE["materials"]))),
            "citizens": max(0, int(source.get("citizens", DEFAULT_GAME_STATE["citizens"]))),
            "children": max(0, int(source.get("children", DEFAULT_GAME_STATE["children"]))),
            "faith": max(0, min(100, int(source.get("faith", DEFAULT_GAME_STATE["faith"])))),
            "corruption": max(0, min(100, int(source.get("corruption", DEFAULT_GAME_STATE["corruption"])))),
            "birthrate": max(0, int(source.get("birthrate", DEFAULT_GAME_STATE["birthrate"]))) % 100,
            "growth": max(0, int(source.get("growth", DEFAULT_GAME_STATE["growth"]))) % 728,
            "weekly": weekly,
            "votes": source.get("votes", {}) if isinstance(source.get("votes", {}), dict) else {},
        }

        for key in ("channel_id", "message_id"):
            if key in source:
                normalized[key] = source[key]

        return normalized

    def _update(
        self,
        guild_id: int,
        mutator: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        data = self._load_all()
        key = str(guild_id)
        entry = self._normalize(data.get(key))
        mutator(entry)
        data[key] = entry
        self._save_all(data)
        return self._normalize(entry)

    def get(self, guild_id: int) -> dict[str, Any] | None:
        entry = self._load_all().get(str(guild_id))
        return self._normalize(entry) if entry is not None else None

    def set(self, guild_id: int, channel_id: int, message_id: int) -> dict[str, Any]:
        return self._update(
            guild_id,
            lambda entry: entry.update(
                {"channel_id": channel_id, "message_id": message_id}
            ),
        )

    def set_weekly_changes(
        self,
        guild_id: int,
        *,
        food: int,
        materials: int,
        faith: int,
        corruption: int,
        birthrate: int,
        growth: int,
    ) -> dict[str, Any]:
        return self._update(
            guild_id,
            lambda entry: entry.update(
                {
                    "weekly": {
                        "food": food,
                        "materials": materials,
                        "faith": faith,
                        "corruption": corruption,
                        "birthrate": birthrate,
                        "growth": growth,
                    }
                }
            ),
        )

    @staticmethod
    def _apply_birthrate(entry: dict[str, Any], change: int) -> int:
        total = max(0, int(entry.get("birthrate", 0)) + change)
        births, remainder = divmod(total, 100)
        entry["birthrate"] = remainder
        if births > 0:
            entry["children"] = max(0, int(entry.get("children", 0))) + births
        return births

    @staticmethod
    def _apply_growth(entry: dict[str, Any], change: int) -> int:
        children = max(0, int(entry.get("children", 0)))
        if children <= 0:
            entry["growth"] = 0
            return 0

        total = max(0, int(entry.get("growth", 0)) + change)
        possible_maturations, remainder = divmod(total, 728)
        matured = min(children, possible_maturations)

        if matured > 0:
            entry["children"] = children - matured
            entry["citizens"] = max(0, int(entry.get("citizens", 0))) + matured

        if int(entry.get("children", 0)) <= 0:
            entry["growth"] = 0
        else:
            entry["growth"] = remainder

        return matured

    def add_resource(
        self,
        guild_id: int,
        resource_type: str,
        value: int,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        summary = {"births": 0, "matured": 0}

        aliases = {
            "material": "materials",
            "materials": "materials",
            "food": "food",
            "faith": "faith",
            "corruption": "corruption",
            "citizen": "citizens",
            "citizens": "citizens",
            "child": "children",
            "children": "children",
            "birth": "birthrate",
            "birthrate": "birthrate",
            "growth": "growth",
            "growthrate": "growth",
        }
        target = aliases.get(resource_type.strip().lower())
        if target is None:
            raise ValueError("Unknown resource type")

        def mutate(entry: dict[str, Any]) -> None:
            if target == "birthrate":
                summary["births"] = self._apply_birthrate(entry, value)
                return
            if target == "growth":
                summary["matured"] = self._apply_growth(entry, value)
                return

            current = int(entry.get(target, 0))
            new_value = current + value
            if target in {"faith", "corruption"}:
                entry[target] = max(0, min(100, new_value))
            else:
                entry[target] = max(0, new_value)
                if target == "children" and entry[target] == 0:
                    entry["growth"] = 0

        state = self._update(guild_id, mutate)
        return state, summary

    def advance_week(self, guild_id: int) -> tuple[dict[str, Any], dict[str, int]]:
        summary = {
            "food_upkeep": 0,
            "food": 0,
            "food_net": 0,
            "materials": 0,
            "faith": 0,
            "corruption": 0,
            "birthrate": 0,
            "births": 0,
            "growth": 0,
            "matured": 0,
        }

        def mutate(entry: dict[str, Any]) -> None:
            weekly = entry.get("weekly", DEFAULT_WEEKLY_CHANGES)
            entry["week"] = max(1, int(entry.get("week", 1))) + 1

            summary["food_upkeep"] = max(0, int(entry.get("citizens", 0))) * 10
            summary["food"] = int(weekly.get("food", 0))
            summary["food_net"] = summary["food"] - summary["food_upkeep"]
            entry["food"] = max(0, int(entry.get("food", 0)) + summary["food_net"])
            entry["materials"] = max(
                0,
                int(entry.get("materials", 0)) + int(weekly.get("materials", 0)),
            )
            entry["faith"] = max(
                0,
                min(100, int(entry.get("faith", 0)) + int(weekly.get("faith", 0))),
            )
            entry["corruption"] = max(
                0,
                min(
                    100,
                    int(entry.get("corruption", 0)) + int(weekly.get("corruption", 0)),
                ),
            )

            birth_change = int(weekly.get("birthrate", 0))
            summary["birthrate"] = birth_change
            summary["births"] = self._apply_birthrate(entry, birth_change)

            growth_change = int(weekly.get("growth", 1))
            if int(entry.get("children", 0)) > 0:
                summary["growth"] = growth_change
                summary["matured"] = self._apply_growth(entry, growth_change)

            for key in ("materials", "faith", "corruption"):
                summary[key] = int(weekly.get(key, 0))

        state = self._update(guild_id, mutate)
        return state, summary

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
        data = self._load_all()
        key = str(guild_id)
        old_entry = self._normalize(data.get(key))

        entry: dict[str, Any] = {
            "week": 1,
            "food": food,
            "materials": materials,
            "citizens": citizens,
            "children": 0,
            "faith": faith,
            "corruption": corruption,
            "birthrate": 0,
            "growth": 0,
            "weekly": dict(DEFAULT_WEEKLY_CHANGES),
            "votes": old_entry.get("votes", {}),
        }

        for preserved_key in ("channel_id", "message_id"):
            if preserved_key in old_entry:
                entry[preserved_key] = old_entry[preserved_key]

        data[key] = entry
        self._save_all(data)
        return self._normalize(entry)

    def save_vote(
        self,
        guild_id: int,
        message_id: int,
        vote: dict[str, Any],
    ) -> dict[str, Any]:
        def mutate(entry: dict[str, Any]) -> None:
            votes = dict(entry.get("votes", {}))
            votes[str(message_id)] = vote
            entry["votes"] = votes

        return self._update(guild_id, mutate)

    def get_vote(self, guild_id: int, message_id: int) -> dict[str, Any] | None:
        state = self.get(guild_id)
        if not state:
            return None
        vote = state.get("votes", {}).get(str(message_id))
        return dict(vote) if isinstance(vote, dict) else None

    def cast_vote(
        self,
        guild_id: int,
        message_id: int,
        user_id: int,
        choice: str,
    ) -> dict[str, Any] | None:
        result: dict[str, Any] | None = None

        def mutate(entry: dict[str, Any]) -> None:
            nonlocal result
            votes = dict(entry.get("votes", {}))
            vote = votes.get(str(message_id))
            if not isinstance(vote, dict) or vote.get("status") != "open":
                return

            pro_votes = {int(v) for v in vote.get("pro_votes", [])}
            con_votes = {int(v) for v in vote.get("con_votes", [])}
            pro_votes.discard(user_id)
            con_votes.discard(user_id)

            if choice == "pro":
                pro_votes.add(user_id)
            elif choice == "con":
                con_votes.add(user_id)
            else:
                return

            vote["pro_votes"] = sorted(pro_votes)
            vote["con_votes"] = sorted(con_votes)
            votes[str(message_id)] = vote
            entry["votes"] = votes
            result = dict(vote)

        self._update(guild_id, mutate)
        return result

    def conclude_vote(
        self,
        guild_id: int,
        message_id: int,
        passed: bool,
    ) -> dict[str, Any] | None:
        result: dict[str, Any] | None = None

        def mutate(entry: dict[str, Any]) -> None:
            nonlocal result
            votes = dict(entry.get("votes", {}))
            vote = votes.get(str(message_id))
            if not isinstance(vote, dict) or vote.get("status") != "open":
                return

            vote["status"] = "passed" if passed else "failed"
            votes[str(message_id)] = vote
            entry["votes"] = votes
            result = dict(vote)

        self._update(guild_id, mutate)
        return result
