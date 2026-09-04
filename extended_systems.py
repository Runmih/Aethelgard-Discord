from __future__ import annotations

from typing import Any

import discord
from discord import app_commands

from healthcare_system import get_healthcare_tier, get_sickness_rating
from productivity_system import get_faith_tier
from systems_store import RISK_MODES, systems_store
from weekly_systems import (
    _expedition_rules,
    _format_exposure,
    _outpost_rules,
    _risk_details,
    get_void_exposure_tier,
    resolve_extended_week,
)

_INSTALLED = False

def _rolls_text(rolls: list[int], dc: int) -> str:
    if not rolls:
        return "None"
    return ", ".join(f"{roll}{'✅' if roll >= dc else '❌'}" for roll in rolls)


def make_expedition_embed(main: Any, guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
    enriched = systems_store.enrich(guild.id, state)
    ext = systems_store.get(guild.id, str(state.get("difficulty", "normal")))
    expedition = ext["expeditions"]
    outposts = ext["outposts"]
    last = ext.get("last_summary", {})
    health_tier = get_healthcare_tier(enriched)
    total_warriors = max(0, int(enriched.get("workforce", {}).get("warriors", 0)))

    outpost_count = int(outposts.get("count", 0)) if outposts.get("unlocked") else 0
    outpost_warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
    active_outposts = min(outpost_count, total_warriors // outpost_warriors_per)
    stationed = active_outposts * outpost_warriors_per
    available = max(0, total_warriors - stationed)
    planned = int(expedition.get("planned", 0))
    warriors_per = int(expedition.get("warriors_per_expedition", 3))
    risk = _risk_details(enriched, str(expedition.get("risk_mode", "default")))
    material_base = int(_expedition_rules(enriched).get("material_per_expedition", 100))
    material_each = int(round(material_base * float(risk["multiplier"])))

    blocked = None
    if bool(health_tier.get("block_new_expeditions", False)):
        blocked = "⛔ New expeditions blocked by Sickness 100."
    elif risk["mode"] == "risky" and bool(health_tier.get("block_risky_expeditions", False)):
        blocked = "⛔ Risky expeditions blocked by current Sickness."

    expedition_lines = [
        "### ⚔️ Expeditions",
        f"**Planned Weekly Expeditions:** {planned}",
        f"**Warriors / Expedition:** {warriors_per}",
        f"**Warriors Needed:** {planned * warriors_per} • Available: {available}/{total_warriors}",
        f"**Materials / Expedition:** {material_base} ×{risk['multiplier']:.1f} = {material_each}",
        f"**Risk:** {risk['label']} • DC {risk['base_dc']} → **{risk['final_dc']}**",
        f"↳ Faith {main.format_risk(int(risk['faith_modifier']))} DC • Sickness {main.format_risk(int(risk['sickness_modifier']))} DC",
    ]
    if blocked:
        expedition_lines.append(blocked)

    last_expedition = last.get("expeditions", {}) if isinstance(last, dict) else {}
    if isinstance(last_expedition, dict) and last_expedition:
        last_dc = int(last_expedition.get("risk", {}).get("final_dc", risk["final_dc"]))
        expedition_lines.extend(
            [
                "",
                "**Last Week**",
                f"Ran: {int(last_expedition.get('runnable', 0))}/{int(last_expedition.get('planned', 0))} • Materials +{int(last_expedition.get('material_gain', 0))}",
                f"Void rolls: {_rolls_text(list(last_expedition.get('rolls', [])), last_dc)}",
                f"Exposure gained: +{_format_exposure(float(last_expedition.get('exposure_gained', 0.0)))}",
            ]
        )

    if outposts.get("unlocked"):
        outpost_risk = _risk_details(enriched, str(outposts.get("risk_mode", "default")))
        outpost_material = int(_outpost_rules(enriched).get("materials_per_outpost", 150))
        outpost_lines = [
            "### 🏕️ Outposts",
            f"**Active / Configured:** {active_outposts}/{outpost_count}",
            f"**Warriors / Outpost:** {outpost_warriors_per} • Stationed: {stationed}",
            f"**Materials / Outpost:** {outpost_material}/week",
            f"**Risk:** {outpost_risk['label']} • DC {outpost_risk['base_dc']} → **{outpost_risk['final_dc']}**",
        ]
        last_outposts = last.get("outposts", {}) if isinstance(last, dict) else {}
        if isinstance(last_outposts, dict) and last_outposts:
            last_dc = int(last_outposts.get("risk", {}).get("final_dc", outpost_risk["final_dc"]))
            outpost_lines.extend(
                [
                    "",
                    "**Last Week**",
                    f"Materials +{int(last_outposts.get('material_gain', 0))} • Void rolls: {_rolls_text(list(last_outposts.get('rolls', [])), last_dc)}",
                    f"Exposure gained: +{_format_exposure(float(last_outposts.get('exposure_gained', 0.0)))}",
                ]
            )
    else:
        outpost_lines = [
            "### 🏕️ Outposts",
            "**Locked.** Permanent operations beyond the Barrier are currently considered unthinkable.",
            "When unlocked: stationed Warriors become unavailable to expeditions, each Outpost generates Materials weekly, and each makes its own Void Exposure roll.",
        ]

    description = "\n".join(expedition_lines) + f"\n\n{main.SEPARATOR}\n\n" + "\n".join(outpost_lines)
    embed = discord.Embed(
        title=f"Aethelgard Expeditions & Outposts • Week {int(state.get('week', 1))}",
        description=description,
    )
    embed.set_footer(text="Failed Void rolls expose every Warrior assigned to that expedition or outpost.")
    return embed


async def refresh_expedition_message(
    main: Any,
    guild: discord.Guild,
    state: dict[str, Any],
    target_channel: discord.TextChannel | None = None,
) -> None:
    difficulty_id = str(state.get("difficulty", "normal"))
    ext = systems_store.get(guild.id, difficulty_id)
    saved_channel = await main._get_text_channel(guild, ext.get("channel_id"))
    message_id = ext.get("message_id")
    embed = make_expedition_embed(main, guild, state)

    if saved_channel is not None and message_id and (
        target_channel is None or saved_channel.id == target_channel.id
    ):
        try:
            message = await saved_channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    channel = target_channel or await main._get_text_channel(guild, state.get("channel_id"))
    if channel is None:
        return
    try:
        message = await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        return
    systems_store.set_message(guild.id, channel.id, message.id, difficulty_id)


def _augment_interface(main: Any, guild: discord.Guild, state: dict[str, Any], embed: discord.Embed) -> discord.Embed:
    enriched = systems_store.enrich(guild.id, state)
    health = get_healthcare_tier(enriched)
    sickness = get_sickness_rating(enriched)
    patients = int(enriched.get("patients", 0))
    capacity = int(enriched.get("healthcare_capacity", 0))
    risk_percent = int(health.get("expedition_risk_percent", 0))
    health_lines = (
        f"**Healthcare:** {patients} Patients • Capacity {capacity}/week\n"
        f"**Sickness:** {sickness}/100 • {health.get('emoji', '🩺')} {health.get('label', 'Healthy')}\n"
        f"↳ Workforce ×{float(health.get('workforce_multiplier', 1.0)):.2f} • Expedition Risk +{risk_percent}%\n"
        f"{main.progress_bar(sickness, filled='🟨')}\n\n"
    )

    description = embed.description or ""
    marker = f"{main.SEPARATOR}\n### Barrier & Void"
    if marker in description:
        description = description.replace(marker, health_lines + marker, 1)

    exposure = float(enriched.get("void_exposure", 0.0))
    void_tier = get_void_exposure_tier(enriched)
    battle = int(void_tier.get("battle_bonus", 0))
    crime = int(void_tier.get("crime_per_week", 0))
    effect_parts = []
    if battle:
        effect_parts.append(f"Battle Actions +{battle}")
    if crime:
        effect_parts.append(f"Crime +{crime}/week")
    effects = " • ".join(effect_parts) if effect_parts else "No active effects"
    description += (
        f"\n**Void Exposure:** {_format_exposure(exposure)}/100 • "
        f"{void_tier.get('emoji', '⚪')} {void_tier.get('label', 'Clear')}\n"
        f"↳ {effects}\n"
        f"{main.progress_bar(int(round(exposure)), filled='🟪')}"
    )
    embed.description = description
    return embed


def _augment_events(main: Any, state: dict[str, Any], summary: dict[str, Any] | None, embed: discord.Embed) -> discord.Embed:
    summary = summary or {}
    nourishment = summary.get("nourishment", {})
    extended = nourishment.get("extended", {}) if isinstance(nourishment, dict) else {}
    if not isinstance(extended, dict) or not extended:
        return embed

    sections: list[str] = []
    void_summary = extended.get("void_exposure", {})
    if isinstance(void_summary, dict):
        lethal = void_summary.get("lethal")
        if isinstance(lethal, dict):
            roll = int(lethal.get("roll", 0))
            dc = int(lethal.get("dc", 0))
            if lethal.get("passed"):
                sections.append(f"### 🟪 VOID EXPOSURE\n**Roll:** {roll} vs DC {dc} • Passed")
            elif lethal.get("type") == "voidling":
                sections.append(
                    "### 👁️ VOIDLING EMERGENCE\n"
                    f"**Roll:** {roll} vs DC {dc} • Failed\n"
                    f"⚔️ Warriors transformed: {int(lethal.get('warriors_transformed', 0))}\n"
                    f"☠️ Citizens killed: {int(lethal.get('citizens_killed', 0))}\n"
                    f"🩹 Citizens injured: {int(lethal.get('citizens_injured', 0))}"
                )
            else:
                sections.append(
                    "### ☠️ LETHAL VOID CORRUPTION\n"
                    f"**Roll:** {roll} vs DC {dc} • Failed\n"
                    f"Warriors killed: **{int(lethal.get('warrior_deaths', 0))}**"
                )

    healthcare = extended.get("healthcare", {})
    if isinstance(healthcare, dict):
        worsening = healthcare.get("worsening")
        crisis = healthcare.get("crisis")
        lines = []
        if int(healthcare.get("treated", 0)):
            lines.append(f"Treated: **{int(healthcare.get('treated', 0))}** Patients")
        if isinstance(worsening, dict) and not worsening.get("passed"):
            lines.append(
                f"Worsening: {int(worsening.get('roll', 0))} vs DC {int(worsening.get('dc', 0))} • "
                f"**+{int(worsening.get('patients_added', 0))} Patients**"
            )
        if isinstance(crisis, dict) and not crisis.get("passed"):
            lines.append(
                f"Health Crisis: {int(crisis.get('roll', 0))} vs DC {int(crisis.get('dc', 0))} • "
                f"**{int(crisis.get('deaths', 0))} died**"
            )
        if lines:
            lines.append(
                f"Current: **{int(healthcare.get('patients_after', 0))} Patients • "
                f"Sickness {int(healthcare.get('sickness', 0))}/100**"
            )
            sections.append("### 🏥 HEALTHCARE\n" + "\n".join(lines))

    if sections:
        existing = embed.description or "*No active events.*"
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

    original_make_interface = main.make_interface_embed
    original_make_events = main.make_events_embed
    original_apply_nourishment = main.apply_food_nourishment_week
    original_refresh_event = main.refresh_event_message
    original_reset_game = main.store.reset_game

    def make_interface_embed(guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
        enriched = systems_store.enrich(guild.id, state)
        return _augment_interface(main, guild, enriched, original_make_interface(guild, enriched))

    def make_events_embed(
        guild: discord.Guild,
        state: dict[str, Any],
        summary: dict[str, Any] | None = None,
    ) -> discord.Embed:
        enriched = systems_store.enrich(guild.id, state)
        return _augment_events(main, enriched, summary, original_make_events(guild, enriched, summary))

    def apply_food_nourishment_week(
        store: Any,
        guild_id: int,
        before_state: dict[str, Any],
        state: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        enriched_before = systems_store.enrich(guild_id, before_state)
        enriched_state = systems_store.enrich(guild_id, state)
        updated_state, nourishment_summary = original_apply_nourishment(
            store,
            guild_id,
            enriched_before,
            enriched_state,
        )
        updated_state, extended_summary = resolve_extended_week(main, guild_id, updated_state)
        nourishment_summary["extended"] = extended_summary
        extra_deaths = int(extended_summary.get("deaths", 0))
        if extra_deaths:
            main.event_store.add_deaths(guild_id, extra_deaths)
        return updated_state, nourishment_summary

    async def refresh_event_message(
        guild: discord.Guild,
        state: dict[str, Any],
        summary: dict[str, Any] | None = None,
        target_channel: discord.TextChannel | None = None,
    ) -> None:
        enriched = systems_store.enrich(guild.id, state)
        await original_refresh_event(guild, enriched, summary, target_channel)
        await refresh_expedition_message(main, guild, enriched, target_channel)

    def reset_game(guild_id: int, difficulty_id: str) -> dict[str, Any]:
        state = original_reset_game(guild_id, difficulty_id)
        systems_store.reset(guild_id, difficulty_id)
        return systems_store.enrich(guild_id, state)

    main.make_interface_embed = make_interface_embed
    main.make_events_embed = make_events_embed
    main.apply_food_nourishment_week = apply_food_nourishment_week
    main.refresh_event_message = refresh_event_message
    main.store.reset_game = reset_game

    risk_choices = [
        app_commands.Choice(name="Safe", value="safe"),
        app_commands.Choice(name="Default", value="default"),
        app_commands.Choice(name="Risky", value="risky"),
    ]

    @main.bot.tree.command(
        name="expedition_setup",
        description="Configure recurring weekly expeditions.",
    )
    @app_commands.describe(
        planned="How many expeditions should run each week",
        warriors_per_expedition="Warriors assigned to each expedition",
        risk_mode="Void risk and material reward mode",
    )
    @app_commands.choices(risk_mode=risk_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def expedition_setup(
        interaction: discord.Interaction,
        planned: app_commands.Range[int, 0, 20],
        warriors_per_expedition: app_commands.Range[int, 1, 100],
        risk_mode: app_commands.Choice[str],
    ) -> None:
        if interaction.guild is None:
            return
        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        systems_store.configure_expeditions(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            planned=int(planned),
            warriors_per_expedition=int(warriors_per_expedition),
            risk_mode=risk_mode.value,
        )
        await interaction.response.send_message("Expedition plan updated.", ephemeral=True)
        await refresh_expedition_message(main, interaction.guild, state)

    @main.bot.tree.command(
        name="outpost_setup",
        description="Unlock/configure permanent outposts beyond the Barrier.",
    )
    @app_commands.describe(
        unlocked="Whether outposts are currently available",
        count="Number of outposts to maintain",
        warriors_per_outpost="Warriors permanently stationed at each outpost",
        risk_mode="Weekly Void risk mode for each outpost",
    )
    @app_commands.choices(risk_mode=risk_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def outpost_setup(
        interaction: discord.Interaction,
        unlocked: bool,
        count: app_commands.Range[int, 0, 10],
        warriors_per_outpost: app_commands.Range[int, 1, 100],
        risk_mode: app_commands.Choice[str],
    ) -> None:
        if interaction.guild is None:
            return
        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        systems_store.configure_outposts(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            unlocked=unlocked,
            count=int(count),
            warriors_per_outpost=int(warriors_per_outpost),
            risk_mode=risk_mode.value,
        )
        await interaction.response.send_message("Outpost configuration updated.", ephemeral=True)
        await refresh_expedition_message(main, interaction.guild, state)

    @main.bot.tree.command(
        name="healthcare_setup",
        description="Set the Patient Pool and weekly Healthcare Capacity.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def healthcare_setup(
        interaction: discord.Interaction,
        patients: app_commands.Range[int, 0, 100000],
        capacity: app_commands.Range[int, 0, 100000],
    ) -> None:
        if interaction.guild is None:
            return
        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        citizens = max(0, int(state.get("citizens", 0)))
        systems_store.configure_healthcare(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            patients=min(int(patients), citizens),
            capacity=int(capacity),
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message(
            f"Healthcare updated: **{int(enriched.get('patients', 0))} Patients**, "
            f"Capacity **{int(enriched.get('healthcare_capacity', 0))}/week**, "
            f"Sickness **{get_sickness_rating(enriched)}/100**.",
            ephemeral=True,
        )
        await main.refresh_saved_interface(interaction.guild, enriched)
        await refresh_expedition_message(main, interaction.guild, enriched)

    @main.bot.tree.command(
        name="void_exposure",
        description="Set Global Void Exposure directly.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def void_exposure(
        interaction: discord.Interaction,
        value: app_commands.Range[int, 0, 100],
    ) -> None:
        if interaction.guild is None:
            return
        state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
        systems_store.set_void_exposure(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            float(value),
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message(
            f"Global Void Exposure set to **{_format_exposure(float(value))}/100**.",
            ephemeral=True,
        )
        await main.refresh_saved_interface(interaction.guild, enriched)
        await refresh_expedition_message(main, interaction.guild, enriched)

    for command in (expedition_setup, outpost_setup, healthcare_setup, void_exposure):
        command.error(main.admin_error)
