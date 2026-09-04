from __future__ import annotations

import math
import random
from typing import Any

from difficulty_store import load_difficulty
from productivity_system import get_effective_weekly_food


def _rules_for(state: dict[str, Any]) -> dict[str, Any]:
    difficulty = load_difficulty(str(state.get("difficulty", "normal")))
    rules = difficulty.get("food_nourishment", {})
    return rules if isinstance(rules, dict) else {}


def get_nourishment_tier(state: dict[str, Any]) -> dict[str, Any]:
    value = max(0, min(100, int(state.get("nourishment", 0))))
    rules = _rules_for(state)
    tiers = rules.get("tiers", [])
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = int(tier.get("min", 0))
            maximum = int(tier.get("max", 100))
            if minimum <= value <= maximum:
                return dict(tier)
    return {
        "id": "stable",
        "label": "Stable",
        "emoji": "🟨",
        "min": 0,
        "max": 100,
        "workforce_multiplier": 1.0,
        "crime": 0,
        "faith": 0,
        "corruption": 0,
        "birthrate": 0,
        "growth": 0,
    }


def apply_food_nourishment_week(
    store: Any,
    guild_id: int,
    before_state: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    rules = _rules_for(state)
    food_per_citizen = max(0, int(rules.get("food_per_citizen", 10)))
    citizens_at_start = max(0, int(before_state.get("citizens", 0)))
    food_before = max(0, int(before_state.get("food", 0)))

    food_income = get_effective_weekly_food(before_state)
    base_weekly_food = int(food_income["base"])
    effective_weekly_food = int(food_income["effective"])
    workforce_multiplier = float(food_income["multiplier"])

    food_required = citizens_at_start * food_per_citizen
    food_available = max(0, food_before + effective_weekly_food)
    food_used = min(food_required, food_available)
    target_food_after = max(0, food_available - food_required)

    # config_store applies the unmodified weekly Food value first. Correct the
    # resulting stockpile here so the effective income is Base × Workforce Multiplier.
    current_food_after = max(0, int(state.get("food", 0)))
    food_correction = target_food_after - current_food_after
    if food_correction:
        state, _ = store.add_resource(guild_id, "food", food_correction)

    if food_required <= 0:
        fed_percent = 100.0
    else:
        fed_percent = min(100.0, (food_used / food_required) * 100)
    unfed_percent = max(0.0, 100.0 - fed_percent)

    if unfed_percent <= 0:
        nourishment_change = int(rules.get("full_feed_nourishment_gain", 5))
    else:
        divisor = max(1, int(rules.get("unfed_percent_divisor", 5)))
        nourishment_change = -math.ceil(unfed_percent / divisor)

    state, _ = store.add_resource(guild_id, "nourishment", nourishment_change)
    tier = get_nourishment_tier(state)

    effects = {
        "crime": int(tier.get("crime", 0)),
        "faith": int(tier.get("faith", 0)),
        "corruption": int(tier.get("corruption", 0)),
        "birthrate": int(tier.get("birthrate", 0)),
        "growth": int(tier.get("growth", 0)),
    }

    for resource in ("crime", "faith", "corruption"):
        change = effects[resource]
        if change:
            state, _ = store.add_resource(guild_id, resource, change)

    bonus_births = 0
    bonus_matured = 0
    bonus_workforce: dict[str, int] = {}
    if effects["birthrate"]:
        state, birth_summary = store.add_resource(guild_id, "birthrate", effects["birthrate"])
        bonus_births = int(birth_summary.get("births", 0))
    if effects["growth"]:
        state, growth_summary = store.add_resource(guild_id, "growth", effects["growth"])
        bonus_matured = int(growth_summary.get("matured", 0))
        bonus_workforce = dict(growth_summary.get("workforce_added", {}))

    starvation: dict[str, Any] | None = None
    deaths = 0
    if str(tier.get("id", "")) == "starving" and int(state.get("citizens", 0)) > 0:
        dc = int(rules.get("starvation_death_dc", 16))
        roll = random.randint(1, 20)
        death_percent = 0

        if roll < dc:
            if roll == 1:
                percent_range = rules.get("starvation_critical_death_percent", [5, 10])
            else:
                percent_range = rules.get("starvation_death_percent", [2, 5])

            if not isinstance(percent_range, list) or len(percent_range) != 2:
                percent_range = [2, 5]
            low = max(0, int(percent_range[0]))
            high = max(low, int(percent_range[1]))
            death_percent = random.randint(low, high)
            citizens_before_deaths = max(0, int(state.get("citizens", 0)))
            deaths = min(citizens_before_deaths, math.ceil(citizens_before_deaths * death_percent / 100))
            if deaths > 0:
                state, _ = store.add_resource(guild_id, "citizens", -deaths)

        starvation = {
            "roll": roll,
            "dc": dc,
            "passed": roll >= dc,
            "death_percent": death_percent,
            "deaths": deaths,
        }

    summary = {
        "food_required": food_required,
        "food_available": food_available,
        "food_used": food_used,
        "food_base_income": base_weekly_food,
        "food_effective_income": effective_weekly_food,
        "workforce_multiplier": workforce_multiplier,
        "workforce_multiplier_breakdown": list(food_income.get("breakdown", [])),
        "fed_percent": fed_percent,
        "unfed_percent": unfed_percent,
        "nourishment_change": nourishment_change,
        "tier": tier,
        "effects": effects,
        "starvation": starvation,
        "deaths": deaths,
        "bonus_births": bonus_births,
        "bonus_matured": bonus_matured,
        "bonus_workforce": bonus_workforce,
    }
    return state, summary
