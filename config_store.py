from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Callable

from difficulty_store import get_void_era, load_difficulty


WORKFORCE_ROLES = ("scientists", "priestesses", "engineers", "warriors")

_NORMAL_DIFFICULTY = load_difficulty("normal")
DEFAULT_WEEKLY_CHANGES = dict(_NORMAL_DIFFICULTY.get("weekly_defaults", {}))
DEFAULT_GAME_STATE = dict(_NORMAL_DIFFICULTY.get("starting_state", {}))
DEFAULT_GAME_STATE.update(
    {
        "difficulty": "normal",
        "next_void_surge_week": None,
        "void_surge_count": 0,
        "void_base_shift": 0,
        "active_void_surge": None,
        "weekly": dict(DEFAULT_WEEKLY_CHANGES),
        "votes": {},
    }
)


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _even_workforce(citizens: int) -> dict[str, int]:
    citizens = max(0, int(citizens))
    base, remainder = divmod(citizens, len(WORKFORCE_ROLES))
    result = {role: base for role in WORKFORCE_ROLES}
    for role in WORKFORCE_ROLES[:remainder]:
        result[role] += 1
    return result


def _normalize_workforce_policy(source: Any, fallback: Any) -> dict[str, Any]:
    source = source if isinstance(source, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}

    fallback_minimum = fallback.get("minimum", {}) if isinstance(fallback.get("minimum", {}), dict) else {}
    source_minimum = source.get("minimum", {}) if isinstance(source.get("minimum", {}), dict) else {}
    minimum = {
        role: max(0, int(source_minimum.get(role, fallback_minimum.get(role, 0))))
        for role in WORKFORCE_ROLES
    }

    fallback_ratio = fallback.get("ratio", {}) if isinstance(fallback.get("ratio", {}), dict) else {}
    source_ratio = source.get("ratio", {}) if isinstance(source.get("ratio", {}), dict) else {}
    ratio = {
        role: max(0, int(source_ratio.get(role, fallback_ratio.get(role, 25))))
        for role in WORKFORCE_ROLES
    }
    if sum(ratio.values()) != 100:
        ratio = {role: max(0, int(fallback_ratio.get(role, 25))) for role in WORKFORCE_ROLES}
    if sum(ratio.values()) != 100:
        ratio = {role: 25 for role in WORKFORCE_ROLES}

    raw_priority = source.get("priority", fallback.get("priority", list(WORKFORCE_ROLES)))
    priority: list[str] = []
    if isinstance(raw_priority, list):
        for role in raw_priority:
            role = str(role)
            if role in WORKFORCE_ROLES and role not in priority:
                priority.append(role)
    for role in WORKFORCE_ROLES:
        if role not in priority:
            priority.append(role)

    return {"minimum": minimum, "ratio": ratio, "priority": priority}


def _select_workforce_role(entry: dict[str, Any]) -> str:
    workforce = entry["workforce"]
    policy = entry["workforce_policy"]
    minimum = policy["minimum"]
    ratio = policy["ratio"]
    priority = policy["priority"]

    shortages = {role for role in WORKFORCE_ROLES if workforce[role] < minimum[role]}
    if shortages:
        for role in priority:
            if role in shortages:
                return role

    surplus = {role: max(0, workforce[role] - minimum[role]) for role in WORKFORCE_ROLES}
    future_total = sum(surplus.values()) + 1
    priority_index = {role: index for index, role in enumerate(priority)}

    def score(role: str) -> tuple[float, int]:
        target = future_total * ratio[role] / 100
        return target - surplus[role], -priority_index.get(role, len(WORKFORCE_ROLES))

    return max(WORKFORCE_ROLES, key=score)


def _assign_worker(entry: dict[str, Any]) -> str:
    role = _select_workforce_role(entry)
    entry["workforce"][role] += 1
    return role


def _remove_worker(entry: dict[str, Any]) -> str | None:
    workforce = entry["workforce"]
    policy = entry["workforce_policy"]
    minimum = policy["minimum"]
    ratio = policy["ratio"]
    priority = policy["priority"]

    candidates = [role for role in WORKFORCE_ROLES if workforce[role] > minimum[role]]
    if candidates:
        surplus = {role: max(0, workforce[role] - minimum[role]) for role in WORKFORCE_ROLES}
        total_surplus = max(1, sum(surplus.values()))

        def excess(role: str) -> float:
            target = total_surplus * ratio[role] / 100
            return surplus[role] - target

        role = max(candidates, key=excess)
    else:
        role = next((role for role in reversed(priority) if workforce[role] > 0), None)

    if role is not None:
        workforce[role] -= 1
    return role


def _set_citizen_total(entry: dict[str, Any], target: int) -> None:
    target = max(0, int(target))
    current = max(0, int(entry.get("citizens", 0)))
    while current < target:
        _assign_worker(entry)
        current += 1
    while current > target:
        if _remove_worker(entry) is None:
            break
        current -= 1
    entry["citizens"] = current


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


def _normalize_active_surge(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    try:
        active = {
            "number": max(1, int(source.get("number", 1))),
            "start_week": max(1, int(source.get("start_week", 1))),
            "end_week": max(1, int(source.get("end_week", 1))),
            "duration_weeks": max(1, int(source.get("duration_weeks", 1))),
            "multiplier": max(1.0, float(source.get("multiplier", 1.0))),
            "title": str(source.get("title", "🌑 MAJOR VOID SURGE")),
            "text": str(source.get("text", "The Void surges against Aethelgard.")),
        }
    except (TypeError, ValueError):
        return None

    for key in ("channel_id", "message_id"):
        if source.get(key) is not None:
            try:
                active[key] = int(source[key])
            except (TypeError, ValueError):
                pass
    return active


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
        weekly = {key: int(source_weekly.get(key, default)) for key, default in weekly_defaults.items()}

        citizens = max(0, int(source.get("citizens", starting.get("citizens", 0))))
        workforce_policy = _normalize_workforce_policy(source.get("workforce_policy"), starting.get("workforce_policy"))

        source_workforce = source.get("workforce")
        if isinstance(source_workforce, dict):
            workforce = {role: max(0, int(source_workforce.get(role, 0))) for role in WORKFORCE_ROLES}
        else:
            workforce = _even_workforce(citizens)

        normalized: dict[str, Any] = {
            "difficulty": difficulty_id,
            "week": int(source.get("week", starting.get("week", 1))),
            "food": max(0, int(source.get("food", starting.get("food", 0)))),
            "materials": max(0, int(source.get("materials", starting.get("materials", 0)))),
            "citizens": citizens,
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
            "workforce": workforce,
            "workforce_policy": workforce_policy,
            "next_void_surge_week": source.get("next_void_surge_week"),
            "void_surge_count": max(0, int(source.get("void_surge_count", 0))),
            "void_base_shift": max(0, int(source.get("void_base_shift", 0))),
            "active_void_surge": _normalize_active_surge(source.get("active_void_surge")),
            "weekly": weekly,
            "votes": source.get("votes", {}) if isinstance(source.get("votes", {}), dict) else {},
        }

        workforce_total = sum(normalized["workforce"].values())
        if workforce_total < citizens:
            for _ in range(citizens - workforce_total):
                _assign_worker(normalized)
        elif workforce_total > citizens:
            for _ in range(workforce_total - citizens):
                _remove_worker(normalized)

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

    def set_workforce_policy(
        self,
        guild_id: int,
        *,
        minimum: dict[str, int],
        ratio: dict[str, int],
        priority: list[str],
    ) -> dict[str, Any]:
        if set(minimum) != set(WORKFORCE_ROLES):
            raise ValueError("Minimum must define every workforce role")
        if set(ratio) != set(WORKFORCE_ROLES) or sum(int(v) for v in ratio.values()) != 100:
            raise ValueError("Workforce ratios must define every role and total 100%")
        if len(priority) != len(WORKFORCE_ROLES) or set(priority) != set(WORKFORCE_ROLES):
            raise ValueError("Priority must rank every workforce role once")
        if any(int(value) < 0 for value in minimum.values()):
            raise ValueError("Minimum workforce values cannot be negative")
        if any(int(value) < 0 for value in ratio.values()):
            raise ValueError("Workforce ratios cannot be negative")

        policy = {
            "minimum": {role: int(minimum[role]) for role in WORKFORCE_ROLES},
            "ratio": {role: int(ratio[role]) for role in WORKFORCE_ROLES},
            "priority": list(priority),
        }
        return self._update(guild_id, lambda entry: entry.update({"workforce_policy": policy}))

    def set_void_surge_message(self, guild_id: int, channel_id: int, message_id: int) -> dict[str, Any]:
        def mutate(entry: dict[str, Any]) -> None:
            active = entry.get("active_void_surge")
            if isinstance(active, dict):
                active = dict(active)
                active["channel_id"] = int(channel_id)
                active["message_id"] = int(message_id)
                entry["active_void_surge"] = active
        return self._update(guild_id, mutate)

    @staticmethod
    def _apply_birthrate(entry: dict[str, Any], change: int) -> int:
        total = max(0, int(entry.get("birthrate", 0)) + change)
        births, remainder = divmod(total, 100)
        entry["birthrate"] = remainder
        entry["children"] = max(0, int(entry.get("children", 0))) + births
        return births

    @staticmethod
    def _apply_growth(entry: dict[str, Any], change: int) -> tuple[int, dict[str, int]]:
        children = max(0, int(entry.get("children", 0)))
        assigned = {role: 0 for role in WORKFORCE_ROLES}
        if children <= 0:
            entry["growth"] = 0
            return 0, assigned

        total = max(0, int(entry.get("growth", 0)) + change)
        possible, remainder = divmod(total, 728)
        matured = min(children, possible)
        entry["children"] = children - matured
        for _ in range(matured):
            entry["citizens"] = max(0, int(entry.get("citizens", 0))) + 1
            role = _assign_worker(entry)
            assigned[role] += 1
        entry["growth"] = remainder if entry["children"] > 0 else 0
        return matured, assigned

    def add_resource(self, guild_id: int, resource_type: str, value: int) -> tuple[dict[str, Any], dict[str, Any]]:
        summary: dict[str, Any] = {
            "births": 0,
            "matured": 0,
            "workforce_added": {role: 0 for role in WORKFORCE_ROLES},
        }
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
                matured, assigned = self._apply_growth(entry, value)
                summary["matured"] = matured
                summary["workforce_added"] = assigned
                return
            if target == "citizens":
                _set_citizen_total(entry, int(entry.get("citizens", 0)) + value)
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
            "workforce_added": {role: 0 for role in WORKFORCE_ROLES},
            "barrier_damage": 0,
            "void_roll": None,
            "void_surge": None,
            "expired_void_surge": None,
        }

        def mutate(entry: dict[str, Any]) -> None:
            difficulty = load_difficulty(str(entry.get("difficulty", "normal")))
            weekly = entry.get("weekly", difficulty.get("weekly_defaults", {}))
            entry["week"] = max(1, int(entry.get("week", 1))) + 1
            week = int(entry["week"])

            active = entry.get("active_void_surge")
            if isinstance(active, dict) and week > int(active.get("end_week", 0)):
                summary["expired_void_surge"] = dict(active)
                entry["active_void_surge"] = None
                active = None

            food_net = int(weekly.get("food", 0)) - (max(0, int(entry.get("citizens", 0))) * 10)
            entry["food"] = max(0, int(entry.get("food", 0)) + food_net)
            entry["materials"] = max(0, int(entry.get("materials", 0)) + int(weekly.get("materials", 0)))
            entry["faith"] = clamp(int(entry.get("faith", 0)) + int(weekly.get("faith", 0)), 0, 100)
            entry["corruption"] = clamp(int(entry.get("corruption", 0)) + int(weekly.get("corruption", 0)), 0, 100)
            entry["nourishment"] = clamp(int(entry.get("nourishment", 0)) + int(weekly.get("nourishment", 0)), 0, 100)
            entry["crime"] = clamp(int(entry.get("crime", 0)) + int(weekly.get("crime", 0)), 0, 100)

            pressure_at_start = clamp(int(entry.get("void_pressure", 0)), 0, 9999)
            summary["barrier_damage"] = pressure_at_start
            entry["barrier"] = clamp(
                int(entry.get("barrier", 0)) + int(weekly.get("barrier", 0)) - pressure_at_start,
                0,
                100,
            )

            summary["births"] = self._apply_birthrate(entry, int(weekly.get("birthrate", 0)))
            if int(entry.get("children", 0)) > 0:
                matured, assigned = self._apply_growth(entry, int(weekly.get("growth", 1)))
                summary["matured"] = matured
                summary["workforce_added"] = assigned
            entry["cum"] = 0

            progression = difficulty.get("void_progression", {})
            era = get_void_era(difficulty, week)
            base_shift = max(0, int(entry.get("void_base_shift", 0)))
            band_min = clamp(int(era.get("pressure_min", 0)) + base_shift, 0, 9999)
            band_max = clamp(int(era.get("pressure_max", 9999)) + base_shift, band_min, 9999)
            pressure = clamp(pressure_at_start, band_min, band_max)

            interval = max(0, int(progression.get("pressure_check_interval", 0)))
            if interval and week % interval == 0:
                roll = random.randint(1, 20)
                dc = int(era.get("dc", 12))
                if roll == 20:
                    change = int(progression.get("natural_20_change", -5))
                    outcome = "natural_20"
                elif roll == 1:
                    change = int(progression.get("natural_1_change", 6))
                    outcome = "natural_1"
                elif roll >= dc:
                    change = int(progression.get("pass_change", -2))
                    outcome = "pass"
                else:
                    change = int(progression.get("fail_change", 3))
                    outcome = "fail"
                pressure = clamp(pressure + change, band_min, band_max)
                summary["void_roll"] = {
                    "roll": roll,
                    "dc": dc,
                    "outcome": outcome,
                    "change": change,
                    "band_min": band_min,
                    "band_max": band_max,
                }

            pressure = clamp(pressure + int(weekly.get("void_pressure", 0)), 0, 9999)
            surge_rules = progression.get("major_surges", {})

            if isinstance(active, dict):
                pressure = clamp(math.ceil(pressure * float(active.get("multiplier", 1.0))), 0, 9999)
            else:
                scheduled = entry.get("next_void_surge_week")
                if scheduled is None:
                    entry["next_void_surge_week"] = next_surge_week(week, difficulty)
                elif week >= int(scheduled):
                    count = max(0, int(entry.get("void_surge_count", 0)))
                    start_multiplier = float(surge_rules.get("multiplier_start", 1.2))
                    step = float(surge_rules.get("multiplier_step", 0.1))
                    maximum = float(surge_rules.get("multiplier_max", 1.6))
                    multiplier = min(maximum, start_multiplier + (count * step))
                    duration = max(1, int(surge_rules.get("duration_weeks", 5)))
                    end_week = week + duration - 1

                    before = pressure
                    pressure = clamp(math.ceil(pressure * multiplier), 0, 9999)

                    shift = max(0, int(surge_rules.get("base_shift_per_surge", 5)))
                    entry["void_base_shift"] = base_shift + shift

                    announcements = surge_rules.get("announcements", [])
                    announcement = random.choice(announcements) if isinstance(announcements, list) and announcements else {}
                    active = {
                        "number": count + 1,
                        "start_week": week,
                        "end_week": end_week,
                        "duration_weeks": duration,
                        "multiplier": multiplier,
                        "title": str(announcement.get("title", "🌑 MAJOR VOID SURGE")),
                        "text": str(announcement.get("text", "The Void surges against Aethelgard.")),
                    }
                    entry["active_void_surge"] = active
                    summary["void_surge"] = {
                        **active,
                        "before": before,
                        "after": pressure,
                        "base_shift": shift,
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
                "void_base_shift": 0,
                "active_void_surge": None,
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
