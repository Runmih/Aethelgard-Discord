from __future__ import annotations

import random
from typing import Any

import discord
from discord import app_commands

from healthcare_system import get_healthcare_tier
from systems_store import RISK_MODES, systems_store
import extended_systems
import weekly_systems


_INSTALLED = False


def _availability(state: dict[str, Any], ext: dict[str, Any]) -> tuple[int, int, int, int]:
    total_warriors = max(0, int(state.get("workforce", {}).get("warriors", 0)))
    outposts = ext.get("outposts", {})
    outpost_count = max(0, int(outposts.get("count", 0))) if outposts.get("unlocked") else 0
    outpost_warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
    active_outposts = min(outpost_count, total_warriors // outpost_warriors_per)
    stationed = active_outposts * outpost_warriors_per
    available = max(0, total_warriors - stationed)
    return total_warriors, active_outposts, stationed, available


def _resolve_expeditions(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
    ext: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expedition = ext["expeditions"]
    warriors = max(1, int(expedition.get("warriors", 3)))
    mode_id = str(expedition.get("risk_mode", "default"))
    risk = weekly_systems._risk_details(state, mode_id)
    health_tier = get_healthcare_tier(state)

    total_warriors, _, stationed, available = _availability(state, ext)

    blocked_reason = None
    if bool(health_tier.get("block_new_expeditions", False)):
        blocked_reason = "Sickness 100 prevents expeditions."
    elif mode_id == "risky" and bool(health_tier.get("block_risky_expeditions", False)):
        blocked_reason = "Current sickness prevents Risky expeditions."
    elif available < warriors:
        blocked_reason = f"Not enough Warriors: {warriors} required, {available} available."

    ran = blocked_reason is None
    material_base = max(
        0,
        int(weekly_systems._expedition_rules(state).get("material_per_expedition", 100)),
    )
    material_gain = int(round(material_base * float(risk["multiplier"]))) if ran else 0
    if material_gain:
        state, _ = main_store.add_resource(guild_id, "materials", material_gain)

    roll = None
    failed = False
    exposure_gained = 0.0
    if ran:
        roll = random.randint(1, 20)
        failed = roll < int(risk["final_dc"])
        if failed:
            exposure_gained = weekly_systems._add_exposure(ext, warriors, total_warriors)

    return state, {
        "ran": ran,
        "warriors": warriors,
        "available_warriors": available,
        "stationed_warriors": stationed,
        "risk": risk,
        "roll": roll,
        "rolls": [roll] if roll is not None else [],
        "failures": 1 if failed else 0,
        "material_gain": material_gain,
        "exposure_gained": exposure_gained,
        "blocked_reason": blocked_reason,
    }


def make_expedition_embed(main: Any, guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
    enriched = systems_store.enrich(guild.id, state)
    ext = systems_store.get(guild.id, str(state.get("difficulty", "normal")))
    expedition = ext["expeditions"]
    outposts = ext["outposts"]
    last = ext.get("last_summary", {})
    health_tier = get_healthcare_tier(enriched)

    total_warriors, active_outposts, stationed, available = _availability(enriched, ext)
    warriors = max(1, int(expedition.get("warriors", 3)))
    risk = weekly_systems._risk_details(enriched, str(expedition.get("risk_mode", "default")))
    material_base = int(weekly_systems._expedition_rules(enriched).get("material_per_expedition", 100))
    material_each = int(round(material_base * float(risk["multiplier"])))

    if bool(health_tier.get("block_new_expeditions", False)):
        status = "⛔ **Blocked:** Sickness 100 prevents expeditions."
    elif risk["mode"] == "risky" and bool(health_tier.get("block_risky_expeditions", False)):
        status = "⛔ **Blocked:** Current Sickness prevents Risky expeditions."
    elif available < warriors:
        status = f"⚠️ **Waiting:** {warriors} Warriors required • {available} available."
    else:
        status = f"✅ **Ready:** {warriors} Warriors will deploy this week."

    expedition_lines = [
        "### ⚔️ Expeditions",
        f"**Warriors:** {warriors} • Available: {available}/{total_warriors}",
        f"**Risk Setting:** {risk['label']}",
        f"**Total Void Risk:** DC **{risk['final_dc']}**",
        f"**Materials:** +{material_each}/week when deployed",
        status,
    ]

    last_expedition = last.get("expeditions", {}) if isinstance(last, dict) else {}
    if isinstance(last_expedition, dict) and last_expedition:
        ran = bool(last_expedition.get("ran", False))
        if ran:
            last_risk = last_expedition.get("risk", {})
            last_dc = int(last_risk.get("final_dc", risk["final_dc"])) if isinstance(last_risk, dict) else int(risk["final_dc"])
            roll = last_expedition.get("roll")
            if roll is None:
                rolls = list(last_expedition.get("rolls", []))
                roll = rolls[0] if rolls else None
            roll_text = "None" if roll is None else f"{int(roll)}{'✅' if int(roll) >= last_dc else '❌'}"
            expedition_lines.extend(
                [
                    "",
                    "**Last Week:** ✅ Deployed",
                    f"Materials +{int(last_expedition.get('material_gain', 0))} • Void roll {roll_text}",
                    f"Exposure +{weekly_systems._format_exposure(float(last_expedition.get('exposure_gained', 0.0)))}",
                ]
            )
        else:
            reason = str(last_expedition.get("blocked_reason") or "Expedition did not deploy.")
            expedition_lines.extend(["", "**Last Week:** ⚠️ Not deployed", reason])

    if outposts.get("unlocked"):
        outpost_risk = weekly_systems._risk_details(enriched, str(outposts.get("risk_mode", "default")))
        outpost_warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
        outpost_count = max(0, int(outposts.get("count", 0)))
        outpost_material = int(weekly_systems._outpost_rules(enriched).get("materials_per_outpost", 150))
        outpost_lines = [
            "### 🏕️ Outposts",
            f"**Active / Configured:** {active_outposts}/{outpost_count}",
            f"**Warriors / Outpost:** {outpost_warriors_per} • Stationed: {stationed}",
            f"**Materials / Outpost:** {outpost_material}/week",
            f"**Risk:** {outpost_risk['label']} • DC **{outpost_risk['final_dc']}**",
        ]
        last_outposts = last.get("outposts", {}) if isinstance(last, dict) else {}
        if isinstance(last_outposts, dict) and last_outposts:
            last_dc = int(last_outposts.get("risk", {}).get("final_dc", outpost_risk["final_dc"]))
            outpost_lines.extend(
                [
                    "",
                    "**Last Week**",
                    f"Materials +{int(last_outposts.get('material_gain', 0))} • "
                    f"Void rolls: {extended_systems._rolls_text(list(last_outposts.get('rolls', [])), last_dc)}",
                    f"Exposure +{weekly_systems._format_exposure(float(last_outposts.get('exposure_gained', 0.0)))}",
                ]
            )
    else:
        outpost_lines = [
            "### 🏕️ Outposts",
            "**Locked.** Permanent operations beyond the Barrier are currently considered unthinkable.",
        ]

    description = "\n".join(expedition_lines) + f"\n\n{main.SEPARATOR}\n\n" + "\n".join(outpost_lines)
    embed = discord.Embed(
        title=f"Aethelgard Expeditions & Outposts • Week {int(state.get('week', 1))}",
        description=description,
    )
    embed.set_footer(text="The configured expedition repeats every week while enough Warriors are available.")
    return embed


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # resolve_extended_week looks up this module-level function at runtime.
    weekly_systems._resolve_expeditions = _resolve_expeditions
    extended_systems.make_expedition_embed = make_expedition_embed

    # Replace the older planned-count command with the recurring configuration.
    main.bot.tree.remove_command("expedition_setup")

    risk_choices = [
        app_commands.Choice(name="Safe", value="safe"),
        app_commands.Choice(name="Default", value="default"),
        app_commands.Choice(name="Risky", value="risky"),
    ]

    @main.bot.tree.command(
        name="expedition_setup",
        description="Set the recurring weekly expedition risk and Warrior count.",
    )
    @app_commands.describe(
        risk_mode="Void risk and material reward setting",
        warriors="Warriors assigned to the expedition each week",
    )
    @app_commands.choices(risk_mode=risk_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def expedition_setup(
        interaction: discord.Interaction,
        risk_mode: app_commands.Choice[str],
        warriors: app_commands.Range[int, 1, 100] = 3,
    ) -> None:
        if interaction.guild is None:
            return

        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        difficulty_id = str(state.get("difficulty", "normal"))
        systems_store.configure_expeditions(
            interaction.guild.id,
            difficulty_id,
            warriors=int(warriors),
            risk_mode=risk_mode.value,
        )

        enriched = systems_store.enrich(interaction.guild.id, state)
        ext = systems_store.get(interaction.guild.id, difficulty_id)
        _, _, _, available = _availability(enriched, ext)
        ready = available >= int(warriors)
        availability_text = (
            f"Ready with **{available} available Warriors**."
            if ready
            else f"Needs **{int(warriors)} Warriors**, but only **{available}** are currently available. It will wait until enough are available."
        )

        await interaction.response.send_message(
            f"Recurring expedition updated: **{risk_mode.name}**, **{int(warriors)} Warriors**.\n"
            f"{availability_text}",
            ephemeral=True,
        )
        await extended_systems.refresh_expedition_message(main, interaction.guild, enriched)

    expedition_setup.error(main.admin_error)
