from __future__ import annotations

import math
import random
from typing import Any

import discord
from discord import app_commands

from crime_store import crime_store
from systems_store import systems_store
import extended_systems
import weekly_systems


_INSTALLED = False


CRIME_TIERS = (
    {"id": "petty", "label": "Petty Crime", "emoji": "🟢", "min": 0, "max": 20},
    {"id": "theft", "label": "Theft", "emoji": "🟡", "min": 21, "max": 45, "food_stolen": 100},
    {"id": "major_theft", "label": "Major Theft", "emoji": "🟠", "min": 46, "max": 75, "food_stolen": 200},
    {
        "id": "dangerous",
        "label": "Dangerous Crime",
        "emoji": "🔴",
        "min": 76,
        "max": 90,
        "dc": 14,
        "death_dice": [1, 3],
        "barrier_damage": 20,
    },
    {
        "id": "severe",
        "label": "Severe Crime",
        "emoji": "🚨",
        "min": 91,
        "max": 95,
        "dc": 16,
        "death_dice": [1, 6],
        "barrier_damage": 20,
    },
    {
        "id": "extreme",
        "label": "Extreme Crime",
        "emoji": "☠️",
        "min": 96,
        "max": 99,
        "dc": 18,
        "death_dice": [2, 6],
        "barrier_damage": 30,
    },
    {
        "id": "kidnapping",
        "label": "Kidnapping",
        "emoji": "⛓️",
        "min": 100,
        "max": 100,
        "rescue_warriors": 10,
        "rescue_warrior_deaths": 6,
        "ransom_food": 500,
        "crime_reduction": 30,
    },
)


def get_crime_tier(crime: int) -> dict[str, Any]:
    value = max(0, min(100, int(crime)))
    for tier in CRIME_TIERS:
        if int(tier["min"]) <= value <= int(tier["max"]):
            return dict(tier)
    return dict(CRIME_TIERS[0])


def _dice_text(dice: list[int] | tuple[int, int]) -> str:
    count = max(1, int(dice[0]))
    sides = max(1, int(dice[1]))
    return f"{count}d{sides}"


def _roll_dice(dice: list[int] | tuple[int, int]) -> int:
    count = max(1, int(dice[0]))
    sides = max(1, int(dice[1]))
    return sum(random.randint(1, sides) for _ in range(count))


def _resolve_barrier_collapse(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if int(state.get("barrier", 0)) > 0:
        return state, None

    citizens = max(0, int(state.get("citizens", 0)))
    if citizens <= 0:
        return state, None

    affected = citizens
    corruption_gain = math.ceil((affected / citizens) * 100 / 2)
    corruption_before = max(0, int(state.get("corruption", 0)))
    state, _ = main_store.add_resource(guild_id, "corruption", corruption_gain)
    corruption_after = max(0, int(state.get("corruption", 0)))

    return state, {
        "citizens_affected": affected,
        "citizens_total": citizens,
        "formula_gain": corruption_gain,
        "actual_gain": corruption_after - corruption_before,
        "corruption_before": corruption_before,
        "corruption_after": corruption_after,
    }


def _resolve_crime(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    crime = max(0, min(100, int(state.get("crime", 0))))
    tier = get_crime_tier(crime)
    pending = crime_store.get(guild_id).get("pending")

    summary: dict[str, Any] = {
        "crime": crime,
        "tier": tier,
        "food_stolen": 0,
        "roll": None,
        "dc": tier.get("dc"),
        "passed": None,
        "pending": pending,
    }

    # One unresolved major Crime event at a time. This prevents weekly rolls
    # from stacking several mutually exclusive player choices.
    if isinstance(pending, dict):
        return state, summary

    tier_id = str(tier.get("id", "petty"))
    if tier_id in {"theft", "major_theft"}:
        requested = max(0, int(tier.get("food_stolen", 0)))
        stolen = min(requested, max(0, int(state.get("food", 0))))
        if stolen:
            state, _ = main_store.add_resource(guild_id, "food", -stolen)
        summary["food_stolen"] = stolen
        summary["food_requested"] = requested
        return state, summary

    if tier_id in {"dangerous", "severe", "extreme"}:
        dc = int(tier.get("dc", 14))
        roll = random.randint(1, 20)
        passed = roll >= dc
        summary["roll"] = roll
        summary["dc"] = dc
        summary["passed"] = passed

        if not passed:
            pending = {
                "type": "crime_choice",
                "tier_id": tier_id,
                "label": str(tier.get("label", "Crime Event")),
                "emoji": str(tier.get("emoji", "🚨")),
                "week": int(state.get("week", 1)),
                "crime": crime,
                "roll": roll,
                "dc": dc,
                "death_dice": list(tier.get("death_dice", [1, 3])),
                "barrier_damage": int(tier.get("barrier_damage", 20)),
            }
            crime_store.set_pending(guild_id, pending)
            summary["pending"] = pending
        return state, summary

    if tier_id == "kidnapping":
        pending = {
            "type": "kidnapping",
            "tier_id": tier_id,
            "label": str(tier.get("label", "Kidnapping")),
            "emoji": str(tier.get("emoji", "⛓️")),
            "week": int(state.get("week", 1)),
            "crime": crime,
            "rescue_warriors": int(tier.get("rescue_warriors", 10)),
            "rescue_warrior_deaths": int(tier.get("rescue_warrior_deaths", 6)),
            "ransom_food": int(tier.get("ransom_food", 500)),
            "crime_reduction": int(tier.get("crime_reduction", 30)),
        }
        crime_store.set_pending(guild_id, pending)
        summary["pending"] = pending

    return state, summary


def _extract_extended(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    nourishment = summary.get("nourishment", {})
    if not isinstance(nourishment, dict):
        return {}
    extended = nourishment.get("extended", {})
    return extended if isinstance(extended, dict) else {}


def _available_unstationed_warriors(guild_id: int, state: dict[str, Any]) -> int:
    total = max(0, int(state.get("workforce", {}).get("warriors", 0)))
    ext = systems_store.get(guild_id, str(state.get("difficulty", "normal")))
    outposts = ext.get("outposts", {})
    if not isinstance(outposts, dict) or not outposts.get("unlocked"):
        return total
    count = max(0, int(outposts.get("count", 0)))
    warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
    active = min(count, total // warriors_per)
    return max(0, total - (active * warriors_per))


def _append_sections(main: Any, embed: discord.Embed, sections: list[str]) -> discord.Embed:
    if not sections:
        return embed
    existing = embed.description or ""
    if existing == "*No active events.*":
        existing = ""
    extra = f"\n\n{main.SEPARATOR}\n\n".join(sections)
    embed.description = extra if not existing else existing + f"\n\n{main.SEPARATOR}\n\n" + extra
    return embed


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_resolve_extended_week = extended_systems.resolve_extended_week
    previous_make_events = main.make_events_embed
    previous_reset_game = main.store.reset_game

    def resolve_extended_week(
        main_module: Any,
        guild_id: int,
        state: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        state, summary = original_resolve_extended_week(main_module, guild_id, state)
        state, barrier_summary = _resolve_barrier_collapse(main_module.store, guild_id, state)
        state, crime_summary = _resolve_crime(main_module.store, guild_id, state)
        summary["barrier_collapse"] = barrier_summary
        summary["crime"] = crime_summary
        return state, summary

    # extended_systems resolves this global at runtime. Patching both references
    # also keeps direct callers of weekly_systems consistent.
    extended_systems.resolve_extended_week = resolve_extended_week
    weekly_systems.resolve_extended_week = resolve_extended_week

    def make_events_embed(
        guild: discord.Guild,
        state: dict[str, Any],
        summary: dict[str, Any] | None = None,
    ) -> discord.Embed:
        embed = previous_make_events(guild, state, summary)
        sections: list[str] = []
        extended = _extract_extended(summary)

        if int(state.get("barrier", 0)) <= 0 and int(state.get("citizens", 0)) > 0:
            barrier_summary = extended.get("barrier_collapse")
            if isinstance(barrier_summary, dict):
                corruption_line = (
                    f"This week: Corruption **{barrier_summary.get('corruption_before', 0)} → "
                    f"{barrier_summary.get('corruption_after', 0)}** "
                    f"(+{barrier_summary.get('actual_gain', 0)})"
                )
            else:
                corruption_line = "Corruption pressure: **+50/week** while the Barrier remains at 0."
            sections.append(
                "### 🛡️ BARRIER COLLAPSE\n"
                "The Void has direct access to the entire population.\n"
                f"**Citizens exposed:** {int(state.get('citizens', 0))}/{int(state.get('citizens', 0))}\n"
                f"{corruption_line}\n"
                "Formula: `(Affected Citizens ÷ Total Citizens) × 100 ÷ 2`"
            )

        crime_summary = extended.get("crime")
        pending = crime_store.get(guild.id).get("pending")

        if isinstance(crime_summary, dict):
            tier = crime_summary.get("tier", {})
            tier_id = str(tier.get("id", "")) if isinstance(tier, dict) else ""
            if tier_id in {"theft", "major_theft"}:
                requested = int(crime_summary.get("food_requested", 0))
                stolen = int(crime_summary.get("food_stolen", 0))
                sections.append(
                    f"### {tier.get('emoji', '🟠')} {tier.get('label', 'THEFT').upper()}\n"
                    f"Crime: **{int(crime_summary.get('crime', 0))}/100**\n"
                    f"Food stolen: **{stolen}**"
                    + (f" of {requested} targeted" if stolen < requested else "")
                )
            elif tier_id in {"dangerous", "severe", "extreme"} and crime_summary.get("passed") is True:
                sections.append(
                    f"### {tier.get('emoji', '🚨')} {tier.get('label', 'CRIME').upper()} CONTAINED\n"
                    f"Roll: **{int(crime_summary.get('roll', 0))}** vs DC **{int(crime_summary.get('dc', 0))}** • Passed\n"
                    "No deaths or Barrier sabotage this week."
                )

        if isinstance(pending, dict):
            if pending.get("type") == "crime_choice":
                death_dice = list(pending.get("death_dice", [1, 3]))
                sections.append(
                    f"### {pending.get('emoji', '🚨')} {str(pending.get('label', 'CRIME EVENT')).upper()}\n"
                    f"Crime: **{int(pending.get('crime', 0))}/100** • "
                    f"Roll **{int(pending.get('roll', 0))}** vs DC **{int(pending.get('dc', 0))}** • Failed\n\n"
                    "Choose one consequence:\n"
                    f"☠️ **Deaths:** {_dice_text(death_dice)} Citizens\n"
                    f"🛡️ **Sabotage:** Barrier -{int(pending.get('barrier_damage', 0))}\n"
                    "Resolve with `/crime_resolve`."
                )
            elif pending.get("type") == "kidnapping":
                sections.append(
                    "### ⛓️ MC KIDNAPPED\n"
                    "Crime has reached **100/100**. The MC remains kidnapped until this event is resolved.\n\n"
                    f"⚔️ **Rescue:** Requires {int(pending.get('rescue_warriors', 10))} available Warriors; "
                    f"{int(pending.get('rescue_warrior_deaths', 6))} Warriors die.\n"
                    f"💰 **Ransom:** Costs {int(pending.get('ransom_food', 500))} Food.\n"
                    f"After resolution: Crime -{int(pending.get('crime_reduction', 30))}.\n"
                    "Resolve with `/kidnapping_resolve`."
                )

        return _append_sections(main, embed, sections)

    main.make_events_embed = make_events_embed

    def reset_game(guild_id: int, difficulty_id: str) -> dict[str, Any]:
        state = previous_reset_game(guild_id, difficulty_id)
        crime_store.reset(guild_id)
        return state

    main.store.reset_game = reset_game

    crime_choices = [
        app_commands.Choice(name="Citizen deaths", value="deaths"),
        app_commands.Choice(name="Barrier sabotage", value="sabotage"),
    ]

    @main.bot.tree.command(
        name="crime_resolve",
        description="Resolve a failed Dangerous, Severe, or Extreme Crime event.",
    )
    @app_commands.choices(outcome=crime_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def crime_resolve(
        interaction: discord.Interaction,
        outcome: app_commands.Choice[str],
    ) -> None:
        if interaction.guild is None:
            return

        pending = crime_store.get(interaction.guild.id).get("pending")
        if not isinstance(pending, dict) or pending.get("type") != "crime_choice":
            await interaction.response.send_message("There is no unresolved Crime choice.", ephemeral=True)
            return

        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        if outcome.value == "deaths":
            death_dice = list(pending.get("death_dice", [1, 3]))
            requested = _roll_dice(death_dice)
            state, deaths = weekly_systems._remove_random_citizens(
                main.store,
                interaction.guild.id,
                requested,
            )
            if deaths:
                main.event_store.add_deaths(interaction.guild.id, deaths)
            result = f"☠️ {_dice_text(death_dice)} rolled **{requested}**. **{deaths} Citizens died**."
        else:
            damage = max(0, int(pending.get("barrier_damage", 0)))
            before = max(0, int(state.get("barrier", 0)))
            state, _ = main.store.add_resource(interaction.guild.id, "barrier", -damage)
            after = max(0, int(state.get("barrier", 0)))
            result = f"🛡️ Barrier sabotage: **{before} → {after}** (-{before - after})."

        crime_store.clear_pending(interaction.guild.id)
        await interaction.response.send_message(result, ephemeral=True)
        await main.refresh_saved_interface(interaction.guild, state)
        await main.refresh_event_message(interaction.guild, state)

    kidnapping_choices = [
        app_commands.Choice(name="Rescue Operation", value="rescue"),
        app_commands.Choice(name="Pay Ransom", value="ransom"),
    ]

    @main.bot.tree.command(
        name="kidnapping_resolve",
        description="Resolve an MC kidnapping caused by Crime 100.",
    )
    @app_commands.choices(method=kidnapping_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def kidnapping_resolve(
        interaction: discord.Interaction,
        method: app_commands.Choice[str],
    ) -> None:
        if interaction.guild is None:
            return

        pending = crime_store.get(interaction.guild.id).get("pending")
        if not isinstance(pending, dict) or pending.get("type") != "kidnapping":
            await interaction.response.send_message("There is no unresolved kidnapping.", ephemeral=True)
            return

        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        if method.value == "rescue":
            required = max(0, int(pending.get("rescue_warriors", 10)))
            casualties = max(0, int(pending.get("rescue_warrior_deaths", 6)))
            available = _available_unstationed_warriors(interaction.guild.id, state)
            if available < required:
                await interaction.response.send_message(
                    f"Rescue requires **{required} available Warriors**. Only **{available}** are available.",
                    ephemeral=True,
                )
                return
            state, deaths = weekly_systems._remove_specific_warriors(
                main.store,
                interaction.guild.id,
                casualties,
            )
            if deaths:
                main.event_store.add_deaths(interaction.guild.id, deaths)
            result = f"⚔️ Rescue successful. **{deaths} Warriors died** during the operation."
        else:
            ransom = max(0, int(pending.get("ransom_food", 500)))
            food = max(0, int(state.get("food", 0)))
            if food < ransom:
                await interaction.response.send_message(
                    f"The ransom requires **{ransom} Food**. Only **{food}** is available.",
                    ephemeral=True,
                )
                return
            state, _ = main.store.add_resource(interaction.guild.id, "food", -ransom)
            result = f"💰 Ransom paid. **{ransom} Food** spent and the MC is returned."

        reduction = max(0, int(pending.get("crime_reduction", 30)))
        crime_before = max(0, int(state.get("crime", 0)))
        state, _ = main.store.add_resource(interaction.guild.id, "crime", -reduction)
        crime_after = max(0, int(state.get("crime", 0)))
        crime_store.clear_pending(interaction.guild.id)

        await interaction.response.send_message(
            f"{result}\nCrime: **{crime_before} → {crime_after}**.",
            ephemeral=True,
        )
        await main.refresh_saved_interface(interaction.guild, state)
        await main.refresh_event_message(interaction.guild, state)

    crime_resolve.error(main.admin_error)
    kidnapping_resolve.error(main.admin_error)
