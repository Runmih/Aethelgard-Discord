from __future__ import annotations

import math
import random
from typing import Any

from difficulty_store import load_difficulty
from healthcare_system import (
    get_expedition_sickness_dc_modifier,
    get_healthcare_tier,
    get_sickness_rating,
)
from productivity_system import get_faith_tier
from systems_store import RISK_MODES, systems_store

def _difficulty(state: dict[str, Any]) -> dict[str, Any]:
    return load_difficulty(str(state.get("difficulty", "normal")))


def _expedition_rules(state: dict[str, Any]) -> dict[str, Any]:
    rules = _difficulty(state).get("expeditions", {})
    return rules if isinstance(rules, dict) else {}


def _outpost_rules(state: dict[str, Any]) -> dict[str, Any]:
    rules = _difficulty(state).get("outposts", {})
    return rules if isinstance(rules, dict) else {}


def _healthcare_rules(state: dict[str, Any]) -> dict[str, Any]:
    rules = _difficulty(state).get("healthcare", {})
    return rules if isinstance(rules, dict) else {}


def get_void_exposure_tier(state: dict[str, Any]) -> dict[str, Any]:
    value = max(0.0, min(100.0, float(state.get("void_exposure", 0.0))))
    rules = _difficulty(state).get("void_exposure_system", {})
    tiers = rules.get("tiers", []) if isinstance(rules, dict) else []
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            if float(tier.get("min", 0)) <= value <= float(tier.get("max", 100)):
                result = dict(tier)
                result.setdefault("battle_bonus", 0)
                result.setdefault("crime_per_week", 0)
                return result
    return {
        "id": "clear",
        "label": "Clear",
        "emoji": "⚪",
        "min": 0,
        "max": 100,
        "battle_bonus": 0,
        "crime_per_week": 0,
    }


def _format_exposure(value: float) -> str:
    rounded = round(float(value), 1)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.1f}"


def _remove_specific_warriors(main_store: Any, guild_id: int, count: int) -> tuple[dict[str, Any], int]:
    removed = 0

    def mutate(entry: dict[str, Any]) -> None:
        nonlocal removed
        workforce = entry.get("workforce", {})
        available = max(0, int(workforce.get("warriors", 0)))
        removed = min(max(0, int(count)), available)
        if removed <= 0:
            return
        workforce = dict(workforce)
        workforce["warriors"] = available - removed
        entry["workforce"] = workforce
        entry["citizens"] = max(0, int(entry.get("citizens", 0)) - removed)

    state = main_store._update(guild_id, mutate)
    return state, removed


def _remove_random_citizens(main_store: Any, guild_id: int, count: int) -> tuple[dict[str, Any], int]:
    removed = 0

    def mutate(entry: dict[str, Any]) -> None:
        nonlocal removed
        workforce = dict(entry.get("workforce", {}))
        target = min(max(0, int(count)), max(0, int(entry.get("citizens", 0))))
        for _ in range(target):
            pool: list[str] = []
            for role, amount in workforce.items():
                pool.extend([str(role)] * max(0, int(amount)))
            if not pool:
                break
            role = random.choice(pool)
            workforce[role] = max(0, int(workforce.get(role, 0)) - 1)
            removed += 1
        entry["workforce"] = workforce
        entry["citizens"] = max(0, int(entry.get("citizens", 0)) - removed)

    state = main_store._update(guild_id, mutate)
    return state, removed


def _add_exposure(ext: dict[str, Any], affected: int, total_warriors: int) -> float:
    if affected <= 0 or total_warriors <= 0:
        return 0.0
    gained = (affected / total_warriors) * 100 / 2
    ext["void_exposure"] = min(100.0, float(ext.get("void_exposure", 0.0)) + gained)
    return gained


def _risk_details(state: dict[str, Any], mode_id: str) -> dict[str, Any]:
    mode = RISK_MODES.get(mode_id, RISK_MODES["default"])
    faith_risk = int(get_faith_tier(state).get("void_exposure_risk", 0))
    sickness_dc = get_expedition_sickness_dc_modifier(state)
    final_dc = max(2, min(20, int(mode["dc"]) + faith_risk + sickness_dc))
    return {
        "mode": mode_id,
        "label": mode["label"],
        "base_dc": int(mode["dc"]),
        "multiplier": float(mode["multiplier"]),
        "faith_modifier": faith_risk,
        "sickness_modifier": sickness_dc,
        "final_dc": final_dc,
    }


def _resolve_expeditions(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
    ext: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expedition = ext["expeditions"]
    outposts = ext["outposts"]
    workforce = state.get("workforce", {})
    total_warriors = max(0, int(workforce.get("warriors", 0)))
    outpost_warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
    configured_outposts = max(0, int(outposts.get("count", 0))) if outposts.get("unlocked") else 0
    active_outposts = min(configured_outposts, total_warriors // outpost_warriors_per)
    stationed = active_outposts * outpost_warriors_per
    available = max(0, total_warriors - stationed)
    planned = max(0, int(expedition.get("planned", 0)))
    warriors_per = max(1, int(expedition.get("warriors_per_expedition", 3)))
    health_tier = get_healthcare_tier(state)
    mode_id = str(expedition.get("risk_mode", "default"))
    risk = _risk_details(state, mode_id)

    blocked_reason = None
    if bool(health_tier.get("block_new_expeditions", False)):
        blocked_reason = "Sickness 100 prevents new expeditions."
    elif mode_id == "risky" and bool(health_tier.get("block_risky_expeditions", False)):
        blocked_reason = "Current sickness prevents Risky expeditions."

    runnable = 0 if blocked_reason else min(planned, available // warriors_per)
    material_base = max(0, int(_expedition_rules(state).get("material_per_expedition", 100)))
    material_each = int(round(material_base * float(risk["multiplier"])))
    material_gain = runnable * material_each
    if material_gain:
        state, _ = main_store.add_resource(guild_id, "materials", material_gain)

    rolls: list[int] = []
    failures = 0
    exposure_gained = 0.0
    for _ in range(runnable):
        roll = random.randint(1, 20)
        rolls.append(roll)
        if roll < int(risk["final_dc"]):
            failures += 1
            exposure_gained += _add_exposure(ext, warriors_per, total_warriors)

    return state, {
        "planned": planned,
        "runnable": runnable,
        "warriors_per_expedition": warriors_per,
        "available_warriors": available,
        "stationed_warriors": stationed,
        "risk": risk,
        "rolls": rolls,
        "failures": failures,
        "material_each": material_each,
        "material_gain": material_gain,
        "exposure_gained": exposure_gained,
        "blocked_reason": blocked_reason,
    }


def _resolve_outposts(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
    ext: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    outposts = ext["outposts"]
    unlocked = bool(outposts.get("unlocked", False))
    count = max(0, int(outposts.get("count", 0))) if unlocked else 0
    warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
    total_warriors = max(0, int(state.get("workforce", {}).get("warriors", 0)))
    active = min(count, total_warriors // warriors_per)
    risk = _risk_details(state, str(outposts.get("risk_mode", "default")))
    material_each = max(0, int(_outpost_rules(state).get("materials_per_outpost", 150)))
    material_gain = active * material_each
    if material_gain:
        state, _ = main_store.add_resource(guild_id, "materials", material_gain)

    rolls: list[int] = []
    failures = 0
    exposure_gained = 0.0
    for _ in range(active):
        roll = random.randint(1, 20)
        rolls.append(roll)
        if roll < int(risk["final_dc"]):
            failures += 1
            exposure_gained += _add_exposure(ext, warriors_per, total_warriors)

    return state, {
        "unlocked": unlocked,
        "configured": count,
        "active": active,
        "warriors_per_outpost": warriors_per,
        "risk": risk,
        "rolls": rolls,
        "failures": failures,
        "material_each": material_each,
        "material_gain": material_gain,
        "exposure_gained": exposure_gained,
    }


def _resolve_void_exposure(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
    ext: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = dict(state)
    enriched["void_exposure"] = float(ext.get("void_exposure", 0.0))
    tier = get_void_exposure_tier(enriched)
    crime = int(tier.get("crime_per_week", 0))
    if crime:
        state, _ = main_store.add_resource(guild_id, "crime", crime)

    lethal = None
    exposure = float(ext.get("void_exposure", 0.0))
    warriors = max(0, int(state.get("workforce", {}).get("warriors", 0)))
    deaths = 0
    patients_added = 0

    if warriors > 0 and exposure >= 100:
        roll = random.randint(1, 20)
        dc = 20
        passed = roll >= dc
        transformed = 0
        killed = 0
        injured = 0
        if not passed:
            state, transformed = _remove_specific_warriors(main_store, guild_id, 1)
            if transformed:
                rampage_kills = random.randint(1, 3)
                state, killed = _remove_random_citizens(main_store, guild_id, rampage_kills)
                injured = random.randint(1, 6)
                deaths = transformed + killed
                citizens = max(0, int(state.get("citizens", 0)))
                current_patients = max(0, int(ext.get("patients", 0)))
                patients_added = min(injured, max(0, citizens - current_patients))
                ext["patients"] = current_patients + patients_added
        lethal = {
            "type": "voidling",
            "roll": roll,
            "dc": dc,
            "passed": passed,
            "warriors_transformed": transformed,
            "citizens_killed": killed,
            "citizens_injured": patients_added,
        }
    elif warriors > 0 and exposure >= 80:
        roll = random.randint(1, 20)
        dc = 16
        passed = roll >= dc
        warrior_deaths = 0
        if not passed:
            state, warrior_deaths = _remove_specific_warriors(main_store, guild_id, 1)
            deaths = warrior_deaths
        lethal = {
            "type": "lethal_corruption",
            "roll": roll,
            "dc": dc,
            "passed": passed,
            "warrior_deaths": warrior_deaths,
        }

    return state, {
        "exposure": float(ext.get("void_exposure", 0.0)),
        "tier": tier,
        "crime": crime,
        "lethal": lethal,
        "deaths": deaths,
        "patients_added": patients_added,
    }


def _resolve_healthcare(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
    ext: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    rules = _healthcare_rules(state)
    citizens = max(0, int(state.get("citizens", 0)))
    patients_before = min(max(0, int(ext.get("patients", 0))), citizens)
    capacity = max(0, int(ext.get("healthcare_capacity", 0)))
    treated = min(patients_before, capacity)
    ext["patients"] = patients_before - treated

    enriched = dict(state)
    enriched["patients"] = ext["patients"]
    enriched["healthcare_capacity"] = capacity
    tier_before_rolls = get_healthcare_tier(enriched)

    worsening = None
    worsening_dc = tier_before_rolls.get("worsening_dc")
    if worsening_dc is not None and citizens > 0:
        roll = random.randint(1, 20)
        dc = int(worsening_dc)
        passed = roll >= dc
        added = 0
        if not passed:
            percent = max(0, int(rules.get("worsening_percent", 5)))
            added = math.floor(citizens * percent / 100)
            available_slots = max(0, citizens - int(ext.get("patients", 0)))
            added = min(added, available_slots)
            ext["patients"] = int(ext.get("patients", 0)) + added
        worsening = {"roll": roll, "dc": dc, "passed": passed, "patients_added": added}

    enriched = dict(state)
    enriched["patients"] = min(max(0, int(ext.get("patients", 0))), max(0, int(state.get("citizens", 0))))
    enriched["healthcare_capacity"] = capacity
    tier_after_worsening = get_healthcare_tier(enriched)

    crisis = None
    crisis_dc = tier_after_worsening.get("health_crisis_dc")
    crisis_deaths = 0
    if crisis_dc is not None and int(ext.get("patients", 0)) > 0:
        roll = random.randint(1, 20)
        dc = int(crisis_dc)
        passed = roll >= dc
        if not passed:
            death_percent = max(0, int(rules.get("health_crisis_death_percent", 10)))
            crisis_deaths = math.floor(int(ext.get("patients", 0)) * death_percent / 100)
            if crisis_deaths:
                state, crisis_deaths = _remove_random_citizens(main_store, guild_id, crisis_deaths)
                ext["patients"] = max(0, int(ext.get("patients", 0)) - crisis_deaths)
        crisis = {"roll": roll, "dc": dc, "passed": passed, "deaths": crisis_deaths}

    citizens_after = max(0, int(state.get("citizens", 0)))
    ext["patients"] = min(max(0, int(ext.get("patients", 0))), citizens_after)
    final_enriched = dict(state)
    final_enriched["patients"] = ext["patients"]
    final_enriched["healthcare_capacity"] = capacity
    final_tier = get_healthcare_tier(final_enriched)

    return state, {
        "patients_before": patients_before,
        "capacity": capacity,
        "treated": treated,
        "patients_after": int(ext.get("patients", 0)),
        "sickness": get_sickness_rating(final_enriched),
        "tier": final_tier,
        "worsening": worsening,
        "crisis": crisis,
        "deaths": crisis_deaths,
    }


def resolve_extended_week(main: Any, guild_id: int, state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    difficulty_id = str(state.get("difficulty", "normal"))
    ext = systems_store.get(guild_id, difficulty_id)
    ext["patients"] = min(max(0, int(ext.get("patients", 0))), max(0, int(state.get("citizens", 0))))

    state_for_risk = dict(state)
    state_for_risk["patients"] = ext["patients"]
    state_for_risk["healthcare_capacity"] = ext["healthcare_capacity"]
    state_for_risk["void_exposure"] = ext["void_exposure"]

    state, expeditions = _resolve_expeditions(main.store, guild_id, state_for_risk, ext)
    state_for_risk.update(state)
    state, outposts = _resolve_outposts(main.store, guild_id, state_for_risk, ext)
    state_for_risk.update(state)
    state_for_risk["void_exposure"] = ext["void_exposure"]
    state, void_exposure = _resolve_void_exposure(main.store, guild_id, state_for_risk, ext)
    state, healthcare = _resolve_healthcare(main.store, guild_id, state, ext)

    summary = {
        "expeditions": expeditions,
        "outposts": outposts,
        "void_exposure": void_exposure,
        "healthcare": healthcare,
        "deaths": int(void_exposure.get("deaths", 0)) + int(healthcare.get("deaths", 0)),
    }
    ext["last_summary"] = summary
    systems_store.save(guild_id, ext)
    return systems_store.enrich(guild_id, state), summary
