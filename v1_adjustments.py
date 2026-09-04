from __future__ import annotations

import random
from typing import Any

import discord

import command_consolidation as consolidation
import expedition_system
import extended_systems
import weekly_systems
from crime_store import crime_store
from healthcare_system import get_healthcare_tier
from systems_store import RISK_MODES, systems_store


_INSTALLED = False
MATERIALS_PER_EXPEDITION_WARRIOR = 30


def _format_change(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


async def _require_manage(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions and permissions.manage_guild:
        return True
    await interaction.response.send_message(
        "You need the **Manage Server** permission to use this control.",
        ephemeral=True,
    )
    return False


class ResourcesModal(discord.ui.Modal, title="Resources"):
    def __init__(self, main: Any, state: dict[str, Any]) -> None:
        super().__init__()
        self.main = main
        weekly = state.get("weekly", {})
        self.food = discord.ui.TextInput(
            label="Food / week",
            default=str(int(weekly.get("food", 0))),
            required=True,
        )
        self.materials = discord.ui.TextInput(
            label="Materials / week",
            default=str(int(weekly.get("materials", 0))),
            required=True,
        )
        self.cum_weekly = discord.ui.TextInput(
            label="Cum / week",
            default=str(int(weekly.get("cum", 7))),
            required=True,
        )
        self.cum_stock = discord.ui.TextInput(
            label="Cum stock",
            default=str(int(state.get("cum", 0))),
            required=True,
        )
        for item in (self.food, self.materials, self.cum_weekly, self.cum_stock):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            food = int(str(self.food))
            materials = int(str(self.materials))
            cum_weekly = int(str(self.cum_weekly))
            cum_stock = max(0, int(str(self.cum_stock)))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.set_weekly_group(
            interaction.guild.id,
            food=food,
            materials=materials,
            cum=cum_weekly,
        )
        current_cum = max(0, int(state.get("cum", 0)))
        state, _ = self.main.store.add_resource(
            interaction.guild.id,
            "cum",
            cum_stock - current_cum,
        )
        await interaction.response.send_message("Resources updated.", ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, state)


class PopulationRecoveryModal(discord.ui.Modal, title="Population"):
    def __init__(self, main: Any, state: dict[str, Any], guild_id: int) -> None:
        super().__init__()
        self.main = main
        weekly = state.get("weekly", {})
        ext = systems_store.get(guild_id, str(state.get("difficulty", "normal")))
        self.birthrate = discord.ui.TextInput(
            label="Birthrate / week",
            default=str(int(weekly.get("birthrate", 0))),
            required=True,
        )
        self.growth = discord.ui.TextInput(
            label="Growth / week",
            default=str(int(weekly.get("growth", 1))),
            required=True,
        )
        self.recovery = discord.ui.TextInput(
            label="Recovery Speed / week",
            default=str(int(ext.get("healthcare_capacity", 0))),
            required=True,
        )
        for item in (self.birthrate, self.growth, self.recovery):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            birthrate = int(str(self.birthrate))
            growth = int(str(self.growth))
            recovery = max(0, int(str(self.recovery)))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.set_weekly_group(
            interaction.guild.id,
            birthrate=birthrate,
            growth=growth,
        )
        ext = systems_store.get(interaction.guild.id, str(state.get("difficulty", "normal")))
        systems_store.configure_healthcare(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            patients=max(0, int(ext.get("patients", 0))),
            capacity=recovery,
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message("Population and Recovery Speed updated.", ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, enriched)
        await self.main.refresh_event_message(interaction.guild, enriched)


class ExpeditionNumbersModal(discord.ui.Modal, title="Expedition Values"):
    def __init__(self, main: Any, state: dict[str, Any], guild_id: int) -> None:
        super().__init__()
        self.main = main
        ext = systems_store.get(guild_id, str(state.get("difficulty", "normal")))
        expedition = ext.get("expeditions", {})
        self.warriors = discord.ui.TextInput(
            label="Warriors",
            default=str(int(expedition.get("warriors", 3))),
            required=True,
        )
        self.modifier = discord.ui.TextInput(
            label="Roll modifier",
            default=str(int(expedition.get("roll_modifier", 0))),
            required=True,
        )
        self.add_item(self.warriors)
        self.add_item(self.modifier)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            warriors = max(1, int(str(self.warriors)))
            modifier = int(str(self.modifier))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        ext = systems_store.get(interaction.guild.id, str(state.get("difficulty", "normal")))
        expedition = ext.get("expeditions", {})
        systems_store.configure_expeditions(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            warriors=warriors,
            risk_mode=str(expedition.get("risk_mode", "default")),
            roll_modifier=modifier,
        )
        await interaction.response.send_message(
            f"Expedition updated: **{warriors} Warriors**, roll modifier **{_format_change(modifier)}**.",
            ephemeral=True,
        )
        await refresh_expedition_message(self.main, interaction.guild, state)


class ExpeditionRiskSelect(discord.ui.Select):
    def __init__(self, main: Any, guild_id: int, state: dict[str, Any]) -> None:
        self.main = main
        self.guild_id = guild_id
        current = str(
            systems_store.get(guild_id, str(state.get("difficulty", "normal")))
            .get("expeditions", {})
            .get("risk_mode", "default")
        )
        options = [
            discord.SelectOption(label="Safe", value="safe", default=current == "safe"),
            discord.SelectOption(label="Default", value="default", default=current == "default"),
            discord.SelectOption(label="Risky", value="risky", default=current == "risky"),
        ]
        super().__init__(
            placeholder="Expedition risk",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aethelgard:v2:expedition_risk",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not await _require_manage(interaction):
            return
        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        difficulty_id = str(state.get("difficulty", "normal"))
        ext = systems_store.get(interaction.guild.id, difficulty_id)
        expedition = ext.get("expeditions", {})
        risk = self.values[0]
        systems_store.configure_expeditions(
            interaction.guild.id,
            difficulty_id,
            warriors=max(1, int(expedition.get("warriors", 3))),
            risk_mode=risk,
            roll_modifier=int(expedition.get("roll_modifier", 0)),
        )
        await interaction.response.send_message(
            f"Expedition risk set to **{RISK_MODES[risk]['label']}**.",
            ephemeral=True,
        )
        await refresh_expedition_message(self.main, interaction.guild, state)


class ExpeditionManageView(discord.ui.View):
    def __init__(self, main: Any, guild_id: int, state: dict[str, Any]) -> None:
        super().__init__(timeout=180)
        self.main = main
        self.guild_id = guild_id
        self.add_item(ExpeditionRiskSelect(main, guild_id, state))

    @discord.ui.button(label="Warriors & Modifier", style=discord.ButtonStyle.secondary)
    async def numbers(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not await _require_manage(interaction):
            return
        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        await interaction.response.send_modal(
            ExpeditionNumbersModal(self.main, state, interaction.guild.id)
        )


class EventPanelView(discord.ui.View):
    def __init__(self, main: Any, has_pending: bool = True) -> None:
        super().__init__(timeout=None)
        self.main = main
        if self.children:
            self.children[0].disabled = not has_pending

    @discord.ui.button(
        label="Resolve Event",
        style=discord.ButtonStyle.primary,
        custom_id="aethelgard:v2:resolve_event",
    )
    async def resolve_event(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not await _require_manage(interaction):
            return
        pending = crime_store.get(interaction.guild.id).get("pending")
        if not isinstance(pending, dict):
            await interaction.response.send_message("There is no unresolved event.", ephemeral=True)
            return
        if pending.get("type") == "crime_choice":
            await interaction.response.send_message(
                "Choose the Crime consequence:",
                view=consolidation.CrimeChoiceView(self.main),
                ephemeral=True,
            )
            return
        if pending.get("type") == "kidnapping":
            await interaction.response.send_message(
                "Choose how to resolve the kidnapping:",
                view=consolidation.KidnappingChoiceView(self.main),
                ephemeral=True,
            )
            return
        await interaction.response.send_message("This event has no button resolution yet.", ephemeral=True)


class ExpeditionPanelView(discord.ui.View):
    def __init__(self, main: Any) -> None:
        super().__init__(timeout=None)
        self.main = main

    @discord.ui.button(
        label="Manage",
        style=discord.ButtonStyle.secondary,
        custom_id="aethelgard:v2:manage_expedition",
    )
    async def manage(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not await _require_manage(interaction):
            return
        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        await interaction.response.send_message(
            "Manage the recurring expedition:",
            view=ExpeditionManageView(self.main, interaction.guild.id, state),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Outposts",
        style=discord.ButtonStyle.secondary,
        custom_id="aethelgard:v2:manage_outposts",
    )
    async def outposts(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not await _require_manage(interaction):
            return
        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        await interaction.response.send_modal(
            consolidation.OutpostsModal(self.main, state, interaction.guild.id)
        )


def _resolve_expeditions(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
    ext: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expedition = ext["expeditions"]
    warriors = max(1, int(expedition.get("warriors", 3)))
    roll_modifier = int(expedition.get("roll_modifier", 0))
    mode_id = str(expedition.get("risk_mode", "default"))
    risk = weekly_systems._risk_details(state, mode_id)
    health_tier = get_healthcare_tier(state)

    total_warriors, _, stationed, available = expedition_system._availability(state, ext)

    blocked_reason = None
    if bool(health_tier.get("block_new_expeditions", False)):
        blocked_reason = "Sickness 100 prevents expeditions."
    elif mode_id == "risky" and bool(health_tier.get("block_risky_expeditions", False)):
        blocked_reason = "Current sickness prevents Risky expeditions."
    elif available < warriors:
        blocked_reason = f"Not enough Warriors: {warriors} required, {available} available."

    ran = blocked_reason is None
    base_materials = MATERIALS_PER_EXPEDITION_WARRIOR * warriors
    material_gain = int(round(base_materials * float(risk["multiplier"]))) if ran else 0
    if material_gain:
        state, _ = main_store.add_resource(guild_id, "materials", material_gain)

    raw_roll = None
    total_roll = None
    failed = False
    exposure_gained = 0.0
    if ran:
        raw_roll = random.randint(1, 20)
        total_roll = raw_roll + roll_modifier
        failed = total_roll < int(risk["final_dc"])
        if failed:
            exposure_gained = weekly_systems._add_exposure(ext, warriors, total_warriors)

    return state, {
        "ran": ran,
        "warriors": warriors,
        "available_warriors": available,
        "stationed_warriors": stationed,
        "risk": risk,
        "raw_roll": raw_roll,
        "roll_modifier": roll_modifier,
        "total_roll": total_roll,
        "roll": total_roll,
        "rolls": [total_roll] if total_roll is not None else [],
        "failures": 1 if failed else 0,
        "material_per_warrior": MATERIALS_PER_EXPEDITION_WARRIOR,
        "material_base": base_materials,
        "material_gain": material_gain,
        "exposure_gained": exposure_gained,
        "blocked_reason": blocked_reason,
    }


def _expedition_embed(main: Any, guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
    embed = expedition_system.make_expedition_embed(main, guild, state)
    ext = systems_store.get(guild.id, str(state.get("difficulty", "normal")))
    expedition = ext.get("expeditions", {})
    warriors = max(1, int(expedition.get("warriors", 3)))
    risk = weekly_systems._risk_details(state, str(expedition.get("risk_mode", "default")))
    material_gain = int(round(MATERIALS_PER_EXPEDITION_WARRIOR * warriors * float(risk["multiplier"])))

    lines: list[str] = []
    for line in (embed.description or "").splitlines():
        if line.startswith("**Materials:**"):
            lines.append(
                f"**Materials:** {MATERIALS_PER_EXPEDITION_WARRIOR} × {warriors} Warriors "
                f"×{float(risk['multiplier']):.1f} = **{material_gain}**/week"
            )
        else:
            lines.append(line)
    description = "\n".join(lines)

    count = max(0, int(ext.get("outposts", {}).get("count", 0)))
    if count == 0:
        marker = f"\n\n{main.SEPARATOR}\n\n### 🏕️ Outposts"
        if marker in description:
            description = description.split(marker, 1)[0]
            description += marker + "\n**No Outposts available at the moment.**"

    embed.description = description
    return embed


async def refresh_expedition_message(
    main: Any,
    guild: discord.Guild,
    state: dict[str, Any],
    target_channel: discord.TextChannel | None = None,
) -> None:
    del target_channel
    difficulty_id = str(state.get("difficulty", "normal"))
    ext = systems_store.get(guild.id, difficulty_id)
    saved_channel = await main._get_text_channel(guild, ext.get("channel_id"))
    desired_channel = await main._get_text_channel(guild, state.get("channel_id"))
    message_id = ext.get("message_id")
    embed = _expedition_embed(main, guild, state)
    view = ExpeditionPanelView(main)

    if saved_channel is not None and message_id and (
        desired_channel is None or saved_channel.id == desired_channel.id
    ):
        try:
            message = saved_channel.get_partial_message(int(message_id))
            await message.edit(embed=embed, view=view)
            return
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"Expedition panel edit failed; refusing to create a duplicate: {exc!r}")
            return

    channel = desired_channel or saved_channel
    if channel is None:
        return

    if saved_channel is not None and desired_channel is not None and saved_channel.id != desired_channel.id and message_id:
        try:
            await saved_channel.get_partial_message(int(message_id)).delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    try:
        message = await channel.send(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        return
    systems_store.set_message(guild.id, channel.id, message.id, difficulty_id)


async def refresh_event_message(
    main: Any,
    guild: discord.Guild,
    state: dict[str, Any],
    summary: dict | None = None,
    target_channel: discord.TextChannel | None = None,
) -> None:
    del target_channel
    meta = main.event_store.get(guild.id)
    saved_channel = await main._get_text_channel(guild, meta.get("channel_id"))
    desired_channel = await main._get_text_channel(guild, state.get("channel_id"))
    message_id = meta.get("message_id")
    pending = crime_store.get(guild.id).get("pending")
    view = EventPanelView(main, has_pending=isinstance(pending, dict))
    embed = main.make_events_embed(guild, state, summary)

    if saved_channel is not None and message_id and (
        desired_channel is None or saved_channel.id == desired_channel.id
    ):
        try:
            message = saved_channel.get_partial_message(int(message_id))
            await message.edit(embed=embed, view=view)
            await refresh_expedition_message(main, guild, state)
            return
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"Event panel edit failed; refusing to create a duplicate: {exc!r}")
            return

    channel = desired_channel or saved_channel
    if channel is None:
        return

    if saved_channel is not None and desired_channel is not None and saved_channel.id != desired_channel.id and message_id:
        try:
            await saved_channel.get_partial_message(int(message_id)).delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    try:
        message = await channel.send(embed=embed, view=view)
    except (discord.Forbidden, discord.HTTPException):
        return
    main.event_store.set_message(guild.id, channel.id, message.id)
    await refresh_expedition_message(main, guild, state)


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Cum is now a real stockpile while retaining its editable weekly income.
    original_normalize = main.store._normalize

    def normalize_with_cum(entry: dict[str, Any] | None) -> dict[str, Any]:
        result = original_normalize(entry)
        source = entry if isinstance(entry, dict) else {}
        result["cum"] = max(0, int(source.get("cum", 0)))
        return result

    main.store._normalize = normalize_with_cum

    original_add_resource = main.store.add_resource

    def add_resource_with_cum(
        guild_id: int,
        resource_type: str,
        value: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if resource_type.strip().lower() == "cum":
            def mutate(entry: dict[str, Any]) -> None:
                entry["cum"] = max(0, int(entry.get("cum", 0)) + int(value))

            state = main.store._update(guild_id, mutate)
            return state, {
                "births": 0,
                "matured": 0,
                "workforce_added": {},
            }
        return original_add_resource(guild_id, resource_type, value)

    main.store.add_resource = add_resource_with_cum

    original_advance_week = main.store.advance_week

    def advance_week_with_cum(guild_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        before = main.store.get(guild_id) or dict(main.DEFAULT_GAME_STATE)
        stock_before = max(0, int(before.get("cum", 0)))
        weekly_cum = int(before.get("weekly", {}).get("cum", 7))
        state, summary = original_advance_week(guild_id)
        target = max(0, stock_before + weekly_cum)

        def mutate(entry: dict[str, Any]) -> None:
            entry["cum"] = target

        state = main.store._update(guild_id, mutate)
        return state, summary

    main.store.advance_week = advance_week_with_cum

    # Expedition Materials scale with assigned Warriors and the existing risk multiplier.
    weekly_systems._resolve_expeditions = _resolve_expeditions

    # Add lean display details that were missing from the main interface.
    previous_make_interface = main.make_interface_embed

    def make_interface_embed(guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
        embed = previous_make_interface(guild, state)
        ext = systems_store.get(guild.id, str(state.get("difficulty", "normal")))
        weekly_exposure = int(ext.get("weekly_void_exposure", 0))
        weekly_cum = int(state.get("weekly", {}).get("cum", 7))
        cum_stock = max(0, int(state.get("cum", 0)))
        lines: list[str] = []
        for line in (embed.description or "").splitlines():
            if line.startswith("**Cum:**"):
                lines.append(f"**Cum:** {cum_stock} ({_format_change(weekly_cum)}/week)")
                continue
            if line.startswith("**Void Exposure:**"):
                if " • " in line:
                    left, right = line.split(" • ", 1)
                    lines.append(f"{left} ({_format_change(weekly_exposure)}/week) • {right}")
                else:
                    lines.append(f"{line} ({_format_change(weekly_exposure)}/week)")
                continue
            lines.append(line)
        embed.description = "\n".join(lines)
        return embed

    main.make_interface_embed = make_interface_embed

    PreviousInterfaceView = main.InterfaceView

    class AdjustedInterfaceView(PreviousInterfaceView):
        def __init__(self) -> None:
            super().__init__()
            for item in list(self.children):
                if getattr(item, "custom_id", None) in {
                    "aethelgard:manage_resources",
                    "aethelgard:manage_population",
                    "aethelgard:manage_healthcare",
                }:
                    self.remove_item(item)

            resources = discord.ui.Button(
                label="Resources",
                style=discord.ButtonStyle.secondary,
                custom_id="aethelgard:v2:manage_resources",
                row=1,
            )
            resources.callback = self._resources
            self.add_item(resources)

            population = discord.ui.Button(
                label="Population",
                style=discord.ButtonStyle.secondary,
                custom_id="aethelgard:v2:manage_population",
                row=1,
            )
            population.callback = self._population
            self.add_item(population)

        async def _resources(self, interaction: discord.Interaction) -> None:
            if interaction.guild is None or not await _require_manage(interaction):
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(ResourcesModal(main, state))

        async def _population(self, interaction: discord.Interaction) -> None:
            if interaction.guild is None or not await _require_manage(interaction):
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(
                PopulationRecoveryModal(main, state, interaction.guild.id)
            )

    main.InterfaceView = AdjustedInterfaceView

    extended_systems.refresh_expedition_message = refresh_expedition_message

    async def main_refresh_event_message(
        guild: discord.Guild,
        state: dict,
        summary: dict | None = None,
        target_channel: discord.TextChannel | None = None,
    ) -> None:
        await refresh_event_message(main, guild, state, summary, target_channel)

    main.refresh_event_message = main_refresh_event_message

    original_setup_hook = main.bot.setup_hook

    async def setup_hook() -> None:
        await original_setup_hook()
        main.bot.add_view(EventPanelView(main))
        main.bot.add_view(ExpeditionPanelView(main))

    main.bot.setup_hook = setup_hook
