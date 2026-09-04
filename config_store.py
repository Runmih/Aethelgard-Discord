from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Callable

from difficulty_store import get_void_era, load_difficulty


_NORMAL_DIFFICULTY = load_difficulty("normal")
DEFAULT_WEEKLY_CHANGES = dict(_NORMAL_DIFFICULTY.get("weekly_defaults", {}))
DEFAULT_GAME_STATE = dict(_NORMAL_DIFFICULTY.get("starting_state", {}))
DEFAULT_GAME_STATE.update(
    {
        "difficulty": "normal",
        "next_void_surge_week": None,
        "void_surge_count": 0,
        "weekly": dict(DEFAULT_WEEKLY_CHANGES),
        "votes": {},
    }
)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def initial_surge_week(difficulty: dict[str, Any]) -> int | None:
    surge = difficulty.get("void_progression", {}).get("major_surges", {})
    window = surge.get("first_window", [])
    if not isinstance(window, list) or len(window) != 2:
        return None
    start, end = int(window[0]), int(window[1])
    return random.randint(min(start, end), max(start, end))


def next_surge_week(current_week: int, difficulty: dict[str, Any]) -> int | None:
    surge = difficulty.get("void_progression", {}).get("major_surges", {})
    interval = int(surge.get("interval_weeks", 0))
    if interval <= 0:
        return None
    jitter = max(0, int(surge.get("jitter_weeks", 0)))
    return max(current_week + 1, current_week + interval + random.randint(-jitter, jitter))


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
        source = entry if isinstance(entry, dict) else {}
        difficulty_id = str(source.get("difficulty", "normal"))
        try:
            difficulty = load_difficulty(difficulty_id)
        except ValueError:
            difficulty_id = "normal"
            difficulty = load_difficulty("normal")

        starting = difficulty.get("starting_state", {})
        weekly_defaults = difficulty.get("weekly_defaults", {})
        source_weekly = source.get("weekly", {})
        if not isinstance(source_weekly, dict):
            source_weekly = {}

        weekly = {
            key: int(source_weekly.get(key, default))
            for key, default in weekly_defaults.items()
        }

        normalized: dict[str, Any] = {
            "difficulty": difficulty_id,
            "week": int(source.get("week", starting.get("week", 1))),
            "food": max(0, int(source.get("food", starting.get("food", 0)))),
            "materials": max(0, int(source.get("materials", starting.get("materials", 0)))),
            "citizens": max(0, int(source.get("citizens", starting.get("citizens", 0)))),
            "children": max(0, int(source.get("children", starting.get("children", 0)))),
            "faith": clamp(int(source.get("faith", starting.get("faith", 0))), 0, 100),
            "corruption": clamp(int(source.get("corruption", starting.get("corruption", 0))), 0, 100),
            "birthrate": max(0, int(source.get("birthrate", starting.get("birthrate", 0)))) % 100,
            "growth": max(0, int(source.get("growth", starting.get("growth", 0)))) % 728,
            "barrier": clamp(int(source.get("barrier", starting.get("barrier", 0))), 0, 100),
            "void_pressure": clamp(int(source.get("void_pressure", starting.get("void_pressure", 0))), 0, 9999),
            "nourishment": clamp(int(source.get("nourishment", starting.get("nourishment", 0))), 0, 100),
            "crime": clamp(int(source.get("crime", starting.get("crime", 0))), 0, 100),
            "cum": 0,
            "next_void_surge_week": source.get("next_void_surge_week"),
            "void_surge_count": max(0, int(source.get("void_surge_count", 0))),
            "weekly": weekly,
            "votes": source.get("votes", {}) if isinstance(source.get("votes", {}), dict) else {},
        }
        if normalized["next_void_surge_week"] is not None:
            normalized["next_void_surge_week"] = int(normalized["next_void_surge_week"])

        for key in ("channel_id", "message_id"):
            if key in source:
                normalized[key] = source[key]
        return normalized

    def _update(self, guild_id: int, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
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
        return self._update(guild_id, lambda e: e.update({"channel_id": channel_id, "message_id": message_id}))

    def set_weekly_group(self, guild_id: int, **changes: int) -> dict[str, Any]:
        def mutate(entry: dict[str, Any]) -> None:
            difficulty = load_difficulty(str(entry.get("difficulty", "normal")))
            valid = set(difficulty.get("weekly_defaults", {}))
            invalid = set(changes) - valid
            if invalid:
                raise ValueError(f"Unknown weekly values: {', '.join(sorted(invalid))}")
            weekly = dict(entry.get("weekly", {}))
            for key, value in changes.items():
                weekly[key] = int(value)
            entry["weekly"] = weekly

        return self._update(guild_id, mutate)

    @staticmethod
    def _apply_birthrate(entry: dict[str, Any], change: int) -> int:
        total = max(0, int(entry.get("birthrate", 0)) + change)
        births, remainder = divmod(total, 100)
        entry["birthrate"] = remainder
        entry["children"] = max(0, int(entry.get("children", 0))) + births
        return births

    @staticmethod
    def _apply_growth(entry: dict[str, Any], change: int) -> int:
        children = max(0, int(entry.get("children", 0)))
        if children <= 0:
            entry["growth"] = 0
            return 0

        total = max(0, int(entry.get("growth", 0)) + change)
        possible, remainder = divmod(total, 728)
        matured = min(children, possible)
        entry["children"] = children - matured
        entry["citizens"] = max(0, int(entry.get("citizens", 0))) + matured
        entry["growth"] = remainder if entry["children"] > 0 else 0
        return matured

    def add_resource(self, guild_id: int, resource_type: str, value: int) -> tuple[dict[str, Any], dict[str, int]]:
        summary = {"births": 0, "matured": 0}
        aliases = {
            "material": "materials", "materials": "materials", "food": "food",
            "faith": "faith", "corruption": "corruption", "citizen": "citizens",
            "citizens": "citizens", "child": "children", "children": "children",
            "birth": "birthrate", "birthrate": "birthrate", "growth": "growth",
            "growthrate": "growth", "barrier": "barrier", "void": "void_pressure",
            "voidpressure": "void_pressure", "void_pressure": "void_pressure",
            "nourishment": "nourishment", "crime": "crime",
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

            new_value = int(entry.get(target, 0)) + value
            if target in {"faith", "corruption", "barrier", "nourishment", "crime"}:
                entry[target] = clamp(new_value, 0, 100)
            elif target == "void_pressure":
                entry[target] = clamp(new_value, 0, 9999)
            else:
                entry[target] = max(0, new_value)
                if target == "children" and entry[target] == 0:
                    entry["growth"] = 0

        return self._update(guild_id, mutate), summary

    def advance_week(self, guild_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        summary: dict[str, Any] = {
            "births": 0,
            "matured": 0,
            "barrier_damage": 0,
            "void_roll": None,
            "void_surge": None,
        }

        def mutate(entry: dict[str, Any]) -> None:
            difficulty = load_difficulty(str(entry.get("difficulty", "normal")))
            weekly = entry.get("weekly", difficulty.get("weekly_defaults", {}))
            entry["week"] = max(1, int(entry.get("week", 1))) + 1
            week = int(entry["week"])

            food_net = int(weekly.get("food", 0)) - (max(0, int(entry.get("citizens", 0))) * 10)
            entry["food"] = max(0, int(entry.get("food", 0)) + food_net)
            entry["materials"] = max(0, int(entry.get("materials", 0)) + int(weekly.get("materials", 0)))

            entry["faith"] = clamp(int(entry.get("faith", 0)) + int(weekly.get("faith", 0)), 0, 100)
            entry["corruption"] = clamp(int(entry.get("corruption", 0)) + int(weekly.get("corruption", 0)), 0, 100)
            entry["nourishment"] = clamp(int(entry.get("nourishment", 0)) + int(weekly.get("nourishment", 0)), 0, 100)
            entry["crime"] = clamp(int(entry.get("crime", 0)) + int(weekly.get("crime", 0)), 0, 100)

            # Barrier generation and Void damage are separate. Current pressure damages
            # the Barrier this week; pressure growth below affects the next week.
            pressure_at_start = clamp(int(entry.get("void_pressure", 0)), 0, 9999)
            summary["barrier_damage"] = pressure_at_start
            entry["barrier"] = clamp(
                int(entry.get("barrier", 0))
                + int(weekly.get("barrier", 0))
                - pressure_at_start,
                0,
                100,
            )

            summary["births"] = self._apply_birthrate(entry, int(weekly.get("birthrate", 0)))
            if int(entry.get("children", 0)) > 0:
                summary["matured"] = self._apply_growth(entry, int(weekly.get("growth", 1)))
            entry["cum"] = 0

            progression = difficulty.get("void_progression", {})
            era = get_void_era(difficulty, week)
            passive = int(era.get("passive_per_week", 0))
            pressure = pressure_at_start + int(weekly.get("void_pressure", 0)) + passive

            interval = max(0, int(progression.get("pressure_check_interval", 0)))
            if interval and week % interval == 0:
                roll = random.randint(1, 20)
                dc = int(era.get("dc", 10))
                multiplier = float(era.get("roll_multiplier", 1.0))

                if roll == 20:
                    change = int(progression.get("natural_20_change", -10))
                    outcome = "natural_20"
                elif roll == 1:
                    change = math.ceil(int(progression.get("natural_1_change", 30)) * multiplier)
                    outcome = "natural_1"
                elif roll >= dc:
                    change = math.ceil(int(progression.get("pass_change", 10)) * multiplier)
                    outcome = "pass"
                else:
                    change = math.ceil(int(progression.get("fail_change", 20)) * multiplier)
                    outcome = "fail"

                pressure += change
                summary["void_roll"] = {
                    "roll": roll,
                    "dc": dc,
                    "outcome": outcome,
                    "change": change,
                }

            pressure = clamp(pressure, 0, 9999)

            surge_rules = progression.get("major_surges", {})
            scheduled = entry.get("next_void_surge_week")
            if scheduled is None:
                entry["next_void_surge_week"] = next_surge_week(week, difficulty)
            elif week >= int(scheduled):
                count = max(0, int(entry.get("void_surge_count", 0)))
                start = float(surge_rules.get("multiplier_start", 1.2))
                step = float(surge_rules.get("multiplier_step", 0.1))
                maximum = float(surge_rules.get("multiplier_max", 2.0))
                multiplier = min(maximum, start + (count * step))

                before = pressure
                pressure = clamp(math.ceil(pressure * multiplier), 0, 9999)

                announcements = surge_rules.get("announcements", [])
                announcement = random.choice(announcements) if isinstance(announcements, list) and announcements else {}
                summary["void_surge"] = {
                    "number": count + 1,
                    "multiplier": multiplier,
                    "before": before,
                    "after": pressure,
                    "title": str(announcement.get("title", "🌑 MAJOR VOID SURGE")),
                    "text": str(announcement.get("text", "The Void surges against Aethelgard.")),
                }

                entry["void_surge_count"] = count + 1
                entry["next_void_surge_week"] = next_surge_week(week, difficulty)

            entry["void_pressure"] = pressure

        return self._update(guild_id, mutate), summary

    def reset_game(self, guild_id: int, difficulty_id: str) -> dict[str, Any]:
        difficulty = load_difficulty(difficulty_id)
        starting = difficulty.get("starting_state", {})
        weekly = difficulty.get("weekly_defaults", {})

        data = self._load_all()
        key = str(guild_id)
        old_entry = self._normalize(data.get(key))

        entry: dict[str, Any] = dict(starting)
        entry.update(
            {
                "difficulty": difficulty_id,
                "weekly": dict(weekly),
                "next_void_surge_week": initial_surge_week(difficulty),
                "void_surge_count": 0,
                "votes": old_entry.get("votes", {}),
            }
        )
        for preserved_key in ("channel_id", "message_id"):
            if preserved_key in old_entry:
                entry[preserved_key] = old_entry[preserved_key]

        data[key] = entry
        self._save_all(data)
        return self._normalize(entry)

    def save_vote(self, guild_id: int, message_id: int, vote: dict[str, Any]) -> dict[str, Any]:
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

    def cast_vote(self, guild_id: int, message_id: int, user_id: int, choice: str) -> dict[str, Any] | None:
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

    def conclude_vote(self, guild_id: int, message_id: int, passed: bool) -> dict[str, Any] | None:
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
