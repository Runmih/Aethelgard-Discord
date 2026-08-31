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
    "buildings": [],
    "proposals": {},
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
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _normalize(self, entry: dict[str, Any] | None) -> dict[str, Any]:
        normalized: dict[str, Any] = dict(DEFAULT_GAME_STATE)
        normalized["buildings"] = []
        normalized["proposals"] = {}
        if isinstance(entry, dict):
            normalized.update(entry)
        if not isinstance(normalized.get("buildings"), list):
            normalized["buildings"] = []
        if not isinstance(normalized.get("proposals"), dict):
            normalized["proposals"] = {}
        return normalized

    def _update(self, guild_id: int, mutator) -> dict[str, Any]:
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
            lambda entry: entry.update({"channel_id": channel_id, "message_id": message_id}),
        )

    def set_building_panel(self, guild_id: int, channel_id: int, message_id: int) -> dict[str, Any]:
        return self._update(
            guild_id,
            lambda entry: entry.update(
                {"building_channel_id": channel_id, "building_message_id": message_id}
            ),
        )

    def save_proposal(self, guild_id: int, message_id: int, proposal: dict[str, Any]) -> dict[str, Any]:
        def mutate(entry: dict[str, Any]) -> None:
            proposals = dict(entry.get("proposals", {}))
            proposals[str(message_id)] = proposal
            entry["proposals"] = proposals

        return self._update(guild_id, mutate)

    def get_proposal(self, guild_id: int, message_id: int) -> dict[str, Any] | None:
        entry = self.get(guild_id)
        if not entry:
            return None
        proposal = entry.get("proposals", {}).get(str(message_id))
        return dict(proposal) if isinstance(proposal, dict) else None

    def cast_vote(self, guild_id: int, message_id: int, user_id: int, vote: str) -> dict[str, Any] | None:
        result: dict[str, Any] | None = None

        def mutate(entry: dict[str, Any]) -> None:
            nonlocal result
            proposals = dict(entry.get("proposals", {}))
            proposal = proposals.get(str(message_id))
            if not isinstance(proposal, dict) or proposal.get("status") not in {"proposed", "approved"}:
                return

            pro_votes = {int(v) for v in proposal.get("pro_votes", [])}
            con_votes = {int(v) for v in proposal.get("con_votes", [])}
            pro_votes.discard(user_id)
            con_votes.discard(user_id)
            (pro_votes if vote == "pro" else con_votes).add(user_id)
            proposal["pro_votes"] = sorted(pro_votes)
            proposal["con_votes"] = sorted(con_votes)
            proposals[str(message_id)] = proposal
            entry["proposals"] = proposals
            result = dict(proposal)

        self._update(guild_id, mutate)
        return result

    def conclude_proposal(
        self,
        guild_id: int,
        message_id: int,
        *,
        passed: bool,
        building: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        result: dict[str, Any] | None = None

        def mutate(entry: dict[str, Any]) -> None:
            nonlocal result
            proposals = dict(entry.get("proposals", {}))
            proposal = proposals.get(str(message_id))
            if not isinstance(proposal, dict):
                return

            if not passed:
                proposal["status"] = "rejected"
                proposals[str(message_id)] = proposal
                entry["proposals"] = proposals
                result = dict(proposal)
                return

            proposal["status"] = "approved"
            cost = int(building.get("cost", {}).get("materials", 0))
            build_time = building.get("build_time_weeks")

            if not isinstance(build_time, int):
                proposal["waiting_reason"] = "Building time is not specified."
            elif int(entry.get("materials", 0)) < cost:
                proposal["waiting_reason"] = "Not enough Materials."
            else:
                entry["materials"] = int(entry.get("materials", 0)) - cost
                buildings = list(entry.get("buildings", []))
                completion_week = int(entry.get("week", 1)) + max(0, build_time)
                instance = {
                    "instance_id": max([int(b.get("instance_id", 0)) for b in buildings if isinstance(b, dict)] + [0]) + 1,
                    "slot": len(buildings) + 1,
                    "building_id": building.get("id"),
                    "status": "active" if build_time <= 0 else "constructing",
                    "enabled": True,
                    "started_week": int(entry.get("week", 1)),
                    "completion_week": completion_week,
                }
                buildings.append(instance)
                entry["buildings"] = buildings
                proposal["status"] = "active" if build_time <= 0 else "constructing"
                proposal["building_instance_id"] = instance["instance_id"]
                proposal["completion_week"] = completion_week
                proposal.pop("waiting_reason", None)

            proposals[str(message_id)] = proposal
            entry["proposals"] = proposals
            result = dict(proposal)

        state = self._update(guild_id, mutate)
        return result, state

    def advance_week(self, guild_id: int, building_lookup: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        summary: dict[str, Any] = {
            "food_consumed": 0,
            "food_produced": 0,
            "completed": [],
            "rolls": [],
        }

        def mutate(entry: dict[str, Any]) -> None:
            entry["week"] = max(1, int(entry.get("week", 1))) + 1
            current_week = int(entry["week"])
            buildings = list(entry.get("buildings", []))

            for instance in buildings:
                if not isinstance(instance, dict):
                    continue
                if instance.get("status") == "constructing" and int(instance.get("completion_week", 10**9)) <= current_week:
                    instance["status"] = "active"
                    instance["enabled"] = True
                    summary["completed"].append(str(instance.get("building_id")))

            food_cost = max(0, int(entry.get("citizens", 0))) * 10
            entry["food"] = max(0, int(entry.get("food", 0)) - food_cost)
            summary["food_consumed"] = food_cost

            for instance in buildings:
                if not isinstance(instance, dict) or instance.get("status") != "active" or not instance.get("enabled", True):
                    continue
                definition = building_lookup.get(str(instance.get("building_id")), {})
                weekly = definition.get("weekly_effects", {})
                if isinstance(weekly, dict):
                    for target, raw_value in weekly.items():
                        if target not in entry:
                            continue
                        value = int(raw_value)
                        entry[target] = int(entry.get(target, 0)) + value
                        if target == "food" and value > 0:
                            summary["food_produced"] += value

                for roll in definition.get("weekly_rolls", []):
                    if not isinstance(roll, dict):
                        continue
                    dice = str(roll.get("dice", ""))
                    if not dice.startswith("1d"):
                        continue
                    try:
                        sides = int(dice[2:])
                    except ValueError:
                        continue
                    if sides <= 0:
                        continue
                    import random
                    value = random.randint(1, sides)
                    target = str(roll.get("target", ""))
                    operation = str(roll.get("operation", "add"))
                    if target in entry:
                        delta = value if operation == "add" else -value
                        entry[target] = int(entry.get(target, 0)) + delta
                        if target in {"faith", "corruption"}:
                            entry[target] = max(0, min(100, int(entry[target])))
                    summary["rolls"].append({"building_id": instance.get("building_id"), "target": target, "value": value, "operation": operation})

            entry["buildings"] = buildings

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
        old_entry = data.get(key, {})
        entry: dict[str, Any] = {
            "week": 1,
            "food": food,
            "materials": materials,
            "citizens": citizens,
            "faith": faith,
            "corruption": corruption,
            "buildings": [],
            "proposals": {},
        }
        if isinstance(old_entry, dict):
            for preserved_key in (
                "channel_id",
                "message_id",
                "building_channel_id",
                "building_message_id",
            ):
                if preserved_key in old_entry:
                    entry[preserved_key] = old_entry[preserved_key]
        data[key] = entry
        self._save_all(data)
        return self._normalize(entry)
