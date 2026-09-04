from __future__ import annotations

import random
from typing import Any

import discord

from crime_store import crime_store
from systems_store import RISK_MODES, systems_store
import extended_systems
import weekly_systems


_INSTALLED = False


def _can_manage(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


async def _require_manage(interaction: discord.Interaction) -> bool:
    if _can_manage(interaction):
        return True
    await interaction.response.send_message(
        "You need the **Manage Server** permission to use this control.",
        ephemeral=True,
    )
    return False


def _format_modifier(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def _roll_dice(dice: list[int] | tuple[int, int]) -> int:
    count = max(1, int(dice[0]))
    sides = max(1, int(dice[1]))
    return sum(random.randint(1, sides) for _ in range(count))


def _available_unstationed_warriors(guild_id: int, state: dict[str, Any]) -> int:
    total = max(0, int(state.get("workforce", {}).get("warriors", 0)))
    ext = systems_store.get(guild_id, str(state.get("difficulty", "normal")))
    outposts = ext.get("outposts", {})
    count = max(0, int(outposts.get("count", 0)))
    warriors_per = max(1, int(outposts.get("warriors_per_outpost", 5)))
    active = min(count, total // warriors_per)
    return max(0, total - (active * warriors_per))


class HealthcareModal(discord.ui.Modal, title="Healthcare"):
    def __init__(self, main: Any, state: dict[str, Any]) -> None:
        super().__init__()
        self.main = main
        self.patients = discord.ui.TextInput(
            label="Patients",
            default=str(int(state.get("patients", 0))),
            required=True,
        )
        self.capacity = discord.ui.TextInput(
            label="Healthcare Capacity / week",
            default=str(int(state.get("healthcare_capacity", 0))),
            required=True,
        )
        self.add_item(self.patients)
        self.add_item(self.capacity)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            patients = max(0, int(str(self.patients)))
            capacity = max(0, int(str(self.capacity)))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        citizens = max(0, int(state.get("citizens", 0)))
        systems_store.configure_healthcare(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            patients=min(patients, citizens),
            capacity=capacity,
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message("Healthcare updated.", ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, enriched)
        await self.main.refresh_event_message(interaction.guild, enriched)


class WeeklyVoidCombinedModal(discord.ui.Modal, title="Weekly Barrier & Void"):
    def __init__(self, main: Any, state: dict[str, Any]) -> None:
        super().__init__()
        self.main = main
        weekly = state.get("weekly", {})
        ext = systems_store.get(
            int(state.get("_guild_id", 0)),
            str(state.get("difficulty", "normal")),
        ) if state.get("_guild_id") else {}

        self.barrier = discord.ui.TextInput(
            label="Barrier / week",
            default=str(int(weekly.get("barrier", 0))),
            required=True,
        )
        self.pressure = discord.ui.TextInput(
            label="Void Pressure / week",
            default=str(int(weekly.get("void_pressure", 0))),
            required=True,
        )
        self.corruption = discord.ui.TextInput(
            label="Corruption / week",
            default=str(int(weekly.get("corruption", 0))),
            required=True,
        )
        self.exposure = discord.ui.TextInput(
            label="Void Exposure / week",
            default=str(int(ext.get("weekly_void_exposure", 0))),
            required=True,
        )
        for item in (self.barrier, self.pressure, self.corruption, self.exposure):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            barrier = int(str(self.barrier))
            pressure = int(str(self.pressure))
            corruption = int(str(self.corruption))
            exposure = int(str(self.exposure))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.set_weekly_group(
            interaction.guild.id,
            barrier=barrier,
            void_pressure=pressure,
            corruption=corruption,
        )
        systems_store.set_weekly_void_exposure(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            exposure,
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message("Weekly Barrier & Void values updated.", ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, enriched)


class ExpeditionManageModal(discord.ui.Modal, title="Manage Expedition"):
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
        self.risk = discord.ui.TextInput(
            label="Risk: safe / default / risky",
            default=str(expedition.get("risk_mode", "default")),
            required=True,
        )
        self.modifier = discord.ui.TextInput(
            label="Roll modifier",
            default=str(int(expedition.get("roll_modifier", 0))),
            required=True,
        )
        for item in (self.warriors, self.risk, self.modifier):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            warriors = max(1, int(str(self.warriors)))
            modifier = int(str(self.modifier))
        except ValueError:
            await interaction.response.send_message("Warriors and modifier must be whole numbers.", ephemeral=True)
            return
        risk = str(self.risk).strip().lower()
        if risk not in RISK_MODES:
            await interaction.response.send_message(
                "Risk must be **safe**, **default**, or **risky**.",
                ephemeral=True,
            )
            return

        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        systems_store.configure_expeditions(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            warriors=warriors,
            risk_mode=risk,
            roll_modifier=modifier,
        )
        await interaction.response.send_message(
            f"Expedition updated: **{warriors} Warriors**, **{risk.title()}**, "
            f"roll **1d20 {_format_modifier(modifier)}**.",
            ephemeral=True,
        )
        await extended_systems.refresh_expedition_message(self.main, interaction.guild, state)


class OutpostsModal(discord.ui.Modal, title="Manage Outposts"):
    def __init__(self, main: Any, state: dict[str, Any], guild_id: int) -> None:
        super().__init__()
        self.main = main
        ext = systems_store.get(guild_id, str(state.get("difficulty", "normal")))
        outposts = ext.get("outposts", {})
        self.count = discord.ui.TextInput(
            label="Number of Outposts",
            default=str(int(outposts.get("count", 0))),
            required=True,
        )
        self.warriors = discord.ui.TextInput(
            label="Warriors / Outpost",
            default=str(int(outposts.get("warriors_per_outpost", 5))),
            required=True,
        )
        self.risk = discord.ui.TextInput(
            label="Risk: safe / default / risky",
            default=str(outposts.get("risk_mode", "default")),
            required=True,
        )
        for item in (self.count, self.warriors, self.risk):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            count = max(0, int(str(self.count)))
            warriors = max(1, int(str(self.warriors)))
        except ValueError:
            await interaction.response.send_message("Outpost values must be whole numbers.", ephemeral=True)
            return
        risk = str(self.risk).strip().lower()
        if risk not in RISK_MODES:
            await interaction.response.send_message(
                "Risk must be **safe**, **default**, or **risky**.",
                ephemeral=True,
            )
            return

        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        systems_store.configure_outposts(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            count=count,
            warriors_per_outpost=warriors,
            risk_mode=risk,
        )
        await interaction.response.send_message(
            "Outposts removed." if count == 0 else f"Outposts updated: **{count}**, **{warriors} Warriors each**, **{risk.title()}** risk.",
            ephemeral=True,
        )
        await extended_systems.refresh_expedition_message(self.main, interaction.guild, state)


class CrimeChoiceView(discord.ui.View):
    def __init__(self, main: Any) -> None:
        super().__init__(timeout=180)
        self.main = main

    async def _resolve(self, interaction: discord.Interaction, outcome: str) -> None:
        if interaction.guild is None:
            return
        pending = crime_store.get(interaction.guild.id).get("pending")
        if not isinstance(pending, dict) or pending.get("type") != "crime_choice":
            await interaction.response.send_message("This Crime event is no longer pending.", ephemeral=True)
            return

        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        if outcome == "deaths":
            death_dice = list(pending.get("death_dice", [1, 3]))
            requested = _roll_dice(death_dice)
            state, deaths = weekly_systems._remove_random_citizens(
                self.main.store,
                interaction.guild.id,
                requested,
            )
            if deaths:
                self.main.event_store.add_deaths(interaction.guild.id, deaths)
            result = f"☠️ **{deaths} Citizens died**."
        else:
            damage = max(0, int(pending.get("barrier_damage", 0)))
            before = max(0, int(state.get("barrier", 0)))
            state, _ = self.main.store.add_resource(interaction.guild.id, "barrier", -damage)
            after = max(0, int(state.get("barrier", 0)))
            result = f"🛡️ Barrier sabotage: **{before} → {after}**."

        crime_store.clear_pending(interaction.guild.id)
        await interaction.response.send_message(result, ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, state)
        await self.main.refresh_event_message(interaction.guild, state)

    @discord.ui.button(label="Citizen deaths", style=discord.ButtonStyle.danger)
    async def deaths(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._resolve(interaction, "deaths")

    @discord.ui.button(label="Barrier sabotage", style=discord.ButtonStyle.secondary)
    async def sabotage(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._resolve(interaction, "sabotage")


class KidnappingChoiceView(discord.ui.View):
    def __init__(self, main: Any) -> None:
        super().__init__(timeout=180)
        self.main = main

    async def _resolve(self, interaction: discord.Interaction, method: str) -> None:
        if interaction.guild is None:
            return
        pending = crime_store.get(interaction.guild.id).get("pending")
        if not isinstance(pending, dict) or pending.get("type") != "kidnapping":
            await interaction.response.send_message("This kidnapping is no longer pending.", ephemeral=True)
            return

        state = self.main.store.get(interaction.guild.id) or dict(self.main.DEFAULT_GAME_STATE)
        if method == "rescue":
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
                self.main.store,
                interaction.guild.id,
                casualties,
            )
            if deaths:
                self.main.event_store.add_deaths(interaction.guild.id, deaths)
            result = f"⚔️ Rescue successful. **{deaths} Warriors died**."
        else:
            ransom = max(0, int(pending.get("ransom_food", 500)))
            food = max(0, int(state.get("food", 0)))
            if food < ransom:
                await interaction.response.send_message(
                    f"Ransom requires **{ransom} Food**. Only **{food}** is available.",
                    ephemeral=True,
                )
                return
            state, _ = self.main.store.add_resource(interaction.guild.id, "food", -ransom)
            result = f"💰 Ransom paid. **{ransom} Food** spent."

        reduction = max(0, int(pending.get("crime_reduction", 30)))
        before = max(0, int(state.get("crime", 0)))
        state, _ = self.main.store.add_resource(interaction.guild.id, "crime", -reduction)
        after = max(0, int(state.get("crime", 0)))
        crime_store.clear_pending(interaction.guild.id)

        await interaction.response.send_message(
            f"{result}\nCrime: **{before} → {after}**.",
            ephemeral=True,
        )
        await self.main.refresh_saved_interface(interaction.guild, state)
        await self.main.refresh_event_message(interaction.guild, state)

    @discord.ui.button(label="Rescue Operation", style=discord.ButtonStyle.primary)
    async def rescue(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._resolve(interaction, "rescue")

    @discord.ui.button(label="Pay Ransom", style=discord.ButtonStyle.secondary)
    async def ransom(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self._resolve(interaction, "ransom")


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Add a true weekly Void Exposure modifier without changing the direct value.
    original_resolve_void_exposure = weekly_systems._resolve_void_exposure

    def resolve_void_exposure(
        main_store: Any,
        guild_id: int,
        state: dict[str, Any],
        ext: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        weekly_change = int(ext.get("weekly_void_exposure", 0))
        before = max(0.0, min(100.0, float(ext.get("void_exposure", 0.0))))
        if weekly_change:
            ext["void_exposure"] = max(0.0, min(100.0, before + weekly_change))
        state, summary = original_resolve_void_exposure(main_store, guild_id, state, ext)
        summary["weekly_modifier"] = weekly_change
        summary["weekly_modifier_actual"] = float(ext.get("void_exposure", 0.0)) - before
        return state, summary

    weekly_systems._resolve_void_exposure = resolve_void_exposure

    PreviousInterfaceView = main.InterfaceView

    class ConsolidatedInterfaceView(PreviousInterfaceView):
        @discord.ui.button(
            label="Resources",
            style=discord.ButtonStyle.secondary,
            custom_id="aethelgard:manage_resources",
            row=1,
        )
        async def resources(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(main.WeeklyResourcesModal(state))

        @discord.ui.button(
            label="Population",
            style=discord.ButtonStyle.secondary,
            custom_id="aethelgard:manage_population",
            row=1,
        )
        async def population(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(main.WeeklyPopulationModal(state))

        @discord.ui.button(
            label="Healthcare",
            style=discord.ButtonStyle.secondary,
            custom_id="aethelgard:manage_healthcare",
            row=1,
        )
        async def healthcare(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            enriched = systems_store.enrich(interaction.guild.id, state)
            await interaction.response.send_modal(HealthcareModal(main, enriched))

        @discord.ui.button(
            label="Void",
            style=discord.ButtonStyle.secondary,
            custom_id="aethelgard:manage_void",
            row=1,
        )
        async def void(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            modal_state = dict(state)
            modal_state["_guild_id"] = interaction.guild.id
            await interaction.response.send_modal(WeeklyVoidCombinedModal(main, modal_state))

    main.InterfaceView = ConsolidatedInterfaceView

    class EventPanelView(discord.ui.View):
        def __init__(self, has_pending: bool = True) -> None:
            super().__init__(timeout=None)
            if self.children:
                self.children[0].disabled = not has_pending

        @discord.ui.button(
            label="Resolve Event",
            style=discord.ButtonStyle.primary,
            custom_id="aethelgard:resolve_event",
        )
        async def resolve_event(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            pending = crime_store.get(interaction.guild.id).get("pending")
            if not isinstance(pending, dict):
                await interaction.response.send_message("There is no unresolved event.", ephemeral=True)
                return
            if pending.get("type") == "crime_choice":
                await interaction.response.send_message(
                    "Choose the Crime consequence:",
                    view=CrimeChoiceView(main),
                    ephemeral=True,
                )
                return
            if pending.get("type") == "kidnapping":
                await interaction.response.send_message(
                    "Choose how to resolve the kidnapping:",
                    view=KidnappingChoiceView(main),
                    ephemeral=True,
                )
                return
            await interaction.response.send_message("This event has no button resolution yet.", ephemeral=True)

    class ExpeditionPanelView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=None)

        @discord.ui.button(
            label="Manage",
            style=discord.ButtonStyle.secondary,
            custom_id="aethelgard:manage_expedition",
        )
        async def manage(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(
                ExpeditionManageModal(main, state, interaction.guild.id)
            )

        @discord.ui.button(
            label="Outposts",
            style=discord.ButtonStyle.secondary,
            custom_id="aethelgard:manage_outposts",
        )
        async def outposts(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
            del button
            if not await _require_manage(interaction) or interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(
                OutpostsModal(main, state, interaction.guild.id)
            )

    base_make_expedition_embed = extended_systems.make_expedition_embed

    def make_expedition_embed(guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
        embed = base_make_expedition_embed(main, guild, state)
        ext = systems_store.get(guild.id, str(state.get("difficulty", "normal")))
        count = max(0, int(ext.get("outposts", {}).get("count", 0)))
        if count == 0:
            description = embed.description or ""
            marker = f"\n\n{main.SEPARATOR}\n\n### 🏕️ Outposts"
            if marker in description:
                description = description.split(marker, 1)[0]
                description += marker + "\n**No Outposts available at the moment.**"
                embed.description = description
        return embed

    async def refresh_expedition_message(
        main_module: Any,
        guild: discord.Guild,
        state: dict[str, Any],
        target_channel: discord.TextChannel | None = None,
    ) -> None:
        del target_channel
        difficulty_id = str(state.get("difficulty", "normal"))
        ext = systems_store.get(guild.id, difficulty_id)
        saved_channel = await main_module._get_text_channel(guild, ext.get("channel_id"))
        message_id = ext.get("message_id")
        desired_channel = await main_module._get_text_channel(guild, state.get("channel_id"))
        embed = make_expedition_embed(guild, state)
        view = ExpeditionPanelView()

        if saved_channel is not None and message_id and (
            desired_channel is None or saved_channel.id == desired_channel.id
        ):
            try:
                message = await saved_channel.fetch_message(int(message_id))
                await message.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        if saved_channel is not None and desired_channel is not None and saved_channel.id != desired_channel.id and message_id:
            try:
                old = await saved_channel.fetch_message(int(message_id))
                await old.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        channel = desired_channel or saved_channel
        if channel is None:
            return
        try:
            message = await channel.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            return
        systems_store.set_message(guild.id, channel.id, message.id, difficulty_id)

    extended_systems.refresh_expedition_message = refresh_expedition_message

    async def refresh_event_message(
        guild: discord.Guild,
        state: dict,
        summary: dict | None = None,
        target_channel: discord.TextChannel | None = None,
    ) -> None:
        del target_channel
        meta = main.event_store.get(guild.id)
        saved_channel = await main._get_text_channel(guild, meta.get("channel_id"))
        message_id = meta.get("message_id")
        desired_channel = await main._get_text_channel(guild, state.get("channel_id"))
        pending = crime_store.get(guild.id).get("pending")
        view = EventPanelView(has_pending=isinstance(pending, dict))
        embed = main.make_events_embed(guild, state, summary)

        if saved_channel is not None and message_id and (
            desired_channel is None or saved_channel.id == desired_channel.id
        ):
            try:
                message = await saved_channel.fetch_message(int(message_id))
                await message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None
            else:
                await refresh_expedition_message(main, guild, state)
                return

        if saved_channel is not None and desired_channel is not None and saved_channel.id != desired_channel.id and message_id:
            try:
                old = await saved_channel.fetch_message(int(message_id))
                await old.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        channel = desired_channel or saved_channel
        if channel is None:
            return
        try:
            message = await channel.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            return
        main.event_store.set_message(guild.id, channel.id, message.id)
        await refresh_expedition_message(main, guild, state)

    main.refresh_event_message = refresh_event_message

    # Remove the superseded slash commands. The remaining controls are panel buttons.
    for command_name in (
        "weekly_resources",
        "weekly_population",
        "weekly_void",
        "expedition_setup",
        "healthcare_setup",
        "outpost_setup",
        "void_exposure",
        "crime_resolve",
        "kidnapping_resolve",
    ):
        main.bot.tree.remove_command(command_name)

    original_setup_hook = main.bot.setup_hook

    async def setup_hook() -> None:
        await original_setup_hook()
        main.bot.add_view(EventPanelView())
        main.bot.add_view(ExpeditionPanelView())

    main.bot.setup_hook = setup_hook
