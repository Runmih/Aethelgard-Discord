from __future__ import annotations

import math
from typing import Any

from difficulty_store import load_difficulty


def _rules_for(state: dict[str, Any]) -> dict[str, Any]:
    difficulty = load_difficulty(str(state.get("difficulty", "normal")))
    rules = difficulty.get("healthcare", {})
    return rules if isinstance(rules, dict) else {}


def get_sickness_rating(state: dict[str, Any]) -> int:
    citizens = max(0, int(state.get("citizens", 0)))
    patients = max(0, int(state.get("patients", 0)))
    if citizens <= 0:
        return 0
    return max(0, min(100, math.floor((patients / citizens) * 100)))


def get_healthcare_tier(state: dict[str, Any]) -> dict[str, Any]:
    sickness = get_sickness_rating(state)
    tiers = _rules_for(state).get("tiers", [])
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = int(tier.get("min", 0))
            maximum = int(tier.get("max", 100))
            if minimum <= sickness <= maximum:
                result = dict(tier)
                result["sickness"] = sickness
                result.setdefault("workforce_multiplier", 1.0)
                result.setdefault("expedition_risk_percent", 0)
                result.setdefault("block_risky_expeditions", False)
                result.setdefault("block_new_expeditions", False)
                result.setdefault("research_stops", False)
                result.setdefault("ritual_prepaid_only", False)
                return result
    return {
        "id": "healthy",
        "label": "Healthy",
        "emoji": "🩺",
        "min": 0,
        "max": 100,
        "sickness": sickness,
        "workforce_multiplier": 1.0,
        "expedition_risk_percent": 0,
        "block_risky_expeditions": False,
        "block_new_expeditions": False,
        "research_stops": False,
        "ritual_prepaid_only": False,
    }


def get_expedition_sickness_dc_modifier(state: dict[str, Any]) -> int:
    """Convert the written +10%/+20% expedition risk into d20 DC points.

    Each d20 point changes success probability by five percentage points, so
    +10% risk becomes +2 DC and +20% becomes +4 DC.
    """
    percent = max(0, int(get_healthcare_tier(state).get("expedition_risk_percent", 0)))
    return math.ceil(percent / 5)
