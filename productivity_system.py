from __future__ import annotations

from typing import Any

from difficulty_store import load_difficulty


def _difficulty_for(state: dict[str, Any]) -> dict[str, Any]:
    return load_difficulty(str(state.get("difficulty", "normal")))


def _find_tier(tiers: Any, value: int, fallback_label: str) -> dict[str, Any]:
    value = max(0, min(100, int(value)))
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = int(tier.get("min", 0))
            maximum = int(tier.get("max", 100))
            if minimum <= value <= maximum:
                return dict(tier)
    return {
        "id": fallback_label.lower().replace(" ", "_"),
        "label": fallback_label,
        "min": 0,
        "max": 100,
        "workforce_multiplier": 1.0,
    }


def get_faith_tier(state: dict[str, Any]) -> dict[str, Any]:
    difficulty = _difficulty_for(state)
    rules = difficulty.get("faith_system", {})
    tiers = rules.get("tiers", []) if isinstance(rules, dict) else []
    tier = _find_tier(tiers, int(state.get("faith", 0)), "Steady")
    tier.setdefault("workforce_multiplier", 1.0)
    tier.setdefault("void_exposure_risk", 0)
    tier.setdefault("ritual_power", 1.0)
    tier.setdefault("miracle_available", False)
    return tier


def get_nourishment_productivity_tier(state: dict[str, Any]) -> dict[str, Any]:
    difficulty = _difficulty_for(state)
    rules = difficulty.get("food_nourishment", {})
    tiers = rules.get("tiers", []) if isinstance(rules, dict) else []
    tier = _find_tier(tiers, int(state.get("nourishment", 0)), "Stable")
    tier.setdefault("workforce_multiplier", 1.0)
    return tier


def get_workforce_multiplier_breakdown(state: dict[str, Any]) -> list[dict[str, Any]]:
    nourishment = get_nourishment_productivity_tier(state)
    faith = get_faith_tier(state)
    return [
        {
            "source": "Nourishment",
            "label": str(nourishment.get("label", "Stable")),
            "multiplier": max(0.0, float(nourishment.get("workforce_multiplier", 1.0))),
        },
        {
            "source": "Faith",
            "label": str(faith.get("label", "Steady")),
            "multiplier": max(0.0, float(faith.get("workforce_multiplier", 1.0))),
        },
    ]


def get_total_workforce_multiplier(state: dict[str, Any]) -> float:
    total = 1.0
    for item in get_workforce_multiplier_breakdown(state):
        total *= float(item.get("multiplier", 1.0))
    return round(total, 4)


def apply_workforce_multiplier(value: int, state: dict[str, Any]) -> int:
    multiplier = get_total_workforce_multiplier(state)
    scaled = int(value) * multiplier
    if scaled >= 0:
        return int(scaled + 0.5)
    return -int(abs(scaled) + 0.5)


def get_effective_weekly_food(state: dict[str, Any]) -> dict[str, Any]:
    base = int(state.get("weekly", {}).get("food", 0))
    multiplier = get_total_workforce_multiplier(state)
    effective = apply_workforce_multiplier(base, state)
    return {
        "base": base,
        "effective": effective,
        "multiplier": multiplier,
        "breakdown": get_workforce_multiplier_breakdown(state),
    }
