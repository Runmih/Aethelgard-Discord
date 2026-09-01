from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


DEFAULT_GAME_STATE = {
    "week": 1,
    "food": 2000,
    "materials": 500,
    "citizens": 20,
    "faith": 50,
    "corruption": 20,
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
        normalized: dict[str, Any] = {
            "week": int(source.get("week", DEFAULT_GAME_STATE["week"])),
            "food": int(source.get("food", DEFAULT_GAME_STATE["food"])),
            "materials": int(source.get("materials", DEFAULT_GAME_STATE["materials"])),
            "citizens": int(source.get("citizens", DEFAULT_GAME_STATE["citizens"])),
            "faith": int(source.get("faith", DEFAULT_GAME_STATE["faith"])),
            "corruption": int(source.get("corruption", DEFAULT_GAME_STATE["corruption"])),
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

    def advance_week(self, guild_id: int) -> tuple[dict[str, Any], int]:
        food_cost = 0

        def mutate(entry: dict[str, Any]) -> None:
            nonlocal food_cost
            entry["week"] = max(1, int(entry.get("week", 1))) + 1
            food_cost = max(0, int(entry.get("citizens", 0))) * 10
            entry["food"] = max(0, int(entry.get("food", 0)) - food_cost)

        state = self._update(guild_id, mutate)
        return state, food_cost

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
            "faith": faith,
            "corruption": corruption,
            # Votes are standalone helper messages and survive a game reset.
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
