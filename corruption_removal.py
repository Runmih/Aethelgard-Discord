from __future__ import annotations

from typing import Any

import discord
from discord import app_commands

import crime_system
from systems_store import systems_store


_INSTALLED = False


def _format_change(value: int | float) -> str:
    return f"+{value:g}" if value > 0 else f"{value:g}"


class WeeklyVoidModal(discord.ui.Modal, title="Weekly Barrier & Void"):
    def __init__(self, main: Any, state: dict[str, Any], guild_id: int) -> None:
        super().__init__()
        self.main = main
        weekly = state.get("weekly", {})
        ext = systems_store.get(guild_id, str(state.get("difficulty", "normal")))

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
        self.exposure = discord.ui.TextInput(
            label="Void Exposure / week",
            default=str(int(ext.get("weekly_void_exposure", 0))),
            required=True,
        )
        for item in (self.barrier, self.pressure, self.exposure):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            barrier = int(str(self.barrier))
            pressure = int(str(self.pressure))
            exposure = int(str(self.exposure))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.set_weekly_group(
            interaction.guild.id,
            barrier=barrier,
            void_pressure=pressure,
        )
        systems_store.set_weekly_void_exposure(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            exposure,
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message("Weekly Barrier & Void values updated.", ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, enriched)


def _barrier_collapse_to_exposure(
    main_store: Any,
    guild_id: int,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if int(state.get("barrier", 0)) > 0:
        return state, None

    citizens = max(0, int(state.get("citizens", 0)))
    if citizens <= 0:
        return state, None

    difficulty_id = str(state.get("difficulty", "normal"))
    ext = systems_store.get(guild_id, difficulty_id)
    before = max(0.0, min(100.0, float(ext.get("void_exposure", 0.0))))
    gain = 50.0
    after = min(100.0, before + gain)
    systems_store.set_void_exposure(guild_id, difficulty_id, after)

    return state, {
        "citizens_affected": citizens,
        "citizens_total": citizens,
        "formula_gain": 50,
        "actual_gain": after - before,
        # Legacy field names are retained only for the older event renderer.
        # The final renderer below relabels them as Void Exposure.
        "corruption_before": before,
        "corruption_after": after,
    }


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Remove Corruption from all normalized game state and weekly configuration.
    previous_normalize = main.store._normalize

    def normalize_without_corruption(entry: dict[str, Any] | None) -> dict[str, Any]:
        result = previous_normalize(entry)
        result.pop("corruption", None)
        weekly = dict(result.get("weekly", {}))
        weekly.pop("corruption", None)
        result["weekly"] = weekly
        return result

    main.store._normalize = normalize_without_corruption

    # InterfaceStore._update saves the mutated entry before normalizing its return
    # value. Strip legacy Corruption there too so it cannot reappear in state.json.
    def update_without_corruption(guild_id: int, mutator: Any) -> dict[str, Any]:
        data = main.store._load_all()
        key = str(guild_id)
        entry = main.store._normalize(data.get(key))
        mutator(entry)
        entry.pop("corruption", None)
        weekly = dict(entry.get("weekly", {}))
        weekly.pop("corruption", None)
        entry["weekly"] = weekly
        data[key] = entry
        main.store._save_all(data)
        return main.store._normalize(entry)

    main.store._update = update_without_corruption

    main.DEFAULT_GAME_STATE.pop("corruption", None)
    if isinstance(main.DEFAULT_GAME_STATE.get("weekly"), dict):
        main.DEFAULT_GAME_STATE["weekly"].pop("corruption", None)
    if hasattr(main, "DEFAULT_WEEKLY_CHANGES"):
        main.DEFAULT_WEEKLY_CHANGES.pop("corruption", None)

    # Old internal code can still attempt to touch Corruption. Make those calls inert
    # so old save migrations and wrapped weekly functions remain safe.
    previous_add_resource = main.store.add_resource

    def add_resource_without_corruption(
        guild_id: int,
        resource_type: str,
        value: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if resource_type.strip().lower() == "corruption":
            state = main.store.get(guild_id) or dict(main.DEFAULT_GAME_STATE)
            return state, {
                "births": 0,
                "matured": 0,
                "workforce_added": {},
            }
        return previous_add_resource(guild_id, resource_type, value)

    main.store.add_resource = add_resource_without_corruption

    # Barrier collapse now exposes the whole population directly to the Void.
    crime_system._resolve_barrier_collapse = _barrier_collapse_to_exposure

    # Apply Nourishment's positive tiers as percentage-based recovery from current
    # Void Exposure. This runs after the rest of the week's exposure changes.
    previous_apply_nourishment = main.apply_food_nourishment_week

    def apply_food_nourishment_week(
        store: Any,
        guild_id: int,
        before_state: dict[str, Any],
        state: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        updated_state, summary = previous_apply_nourishment(
            store,
            guild_id,
            before_state,
            state,
        )
        tier = summary.get("tier", {}) if isinstance(summary, dict) else {}
        reduction_percent = (
            float(tier.get("void_exposure_reduction_percent", 0))
            if isinstance(tier, dict)
            else 0.0
        )

        if reduction_percent > 0:
            difficulty_id = str(updated_state.get("difficulty", "normal"))
            ext = systems_store.get(guild_id, difficulty_id)
            before = max(0.0, min(100.0, float(ext.get("void_exposure", 0.0))))
            reduction = before * reduction_percent / 100.0
            after = max(0.0, before - reduction)
            systems_store.set_void_exposure(guild_id, difficulty_id, after)
            summary["void_exposure_recovery"] = {
                "percent": reduction_percent,
                "before": before,
                "reduction": reduction,
                "after": after,
            }
            updated_state = systems_store.enrich(guild_id, updated_state)

        effects = summary.get("effects") if isinstance(summary, dict) else None
        if isinstance(effects, dict):
            effects.pop("corruption", None)
        return updated_state, summary

    main.apply_food_nourishment_week = apply_food_nourishment_week

    # Remove Corruption from the visible interface and relabel the legacy Barrier
    # collapse event output to the mechanic it now actually changes.
    previous_make_interface = main.make_interface_embed

    def make_interface_embed(guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
        embed = previous_make_interface(guild, state)
        lines = (embed.description or "").splitlines()
        cleaned: list[str] = []
        skip_progress = False
        for line in lines:
            if line.startswith("**Corruption:**"):
                skip_progress = True
                continue
            if skip_progress:
                skip_progress = False
                if line and set(line) <= {"🟪", "⬛"}:
                    continue
            cleaned.append(line)
        embed.description = "\n".join(cleaned)
        return embed

    main.make_interface_embed = make_interface_embed

    previous_make_events = main.make_events_embed

    def make_events_embed(
        guild: discord.Guild,
        state: dict[str, Any],
        summary: dict[str, Any] | None = None,
    ) -> discord.Embed:
        embed = previous_make_events(guild, state, summary)
        description = embed.description or ""
        description = description.replace("This week: Corruption", "This week: Void Exposure")
        description = description.replace("Corruption pressure:", "Void Exposure pressure:")
        embed.description = description
        return embed

    main.make_events_embed = make_events_embed

    # Replace the Void button so the modal contains only mechanics that still exist.
    PreviousInterfaceView = main.InterfaceView

    class InterfaceViewWithoutCorruption(PreviousInterfaceView):
        def __init__(self) -> None:
            super().__init__()
            for item in list(self.children):
                if getattr(item, "custom_id", None) == "aethelgard:manage_void":
                    self.remove_item(item)

            void_button = discord.ui.Button(
                label="Void",
                style=discord.ButtonStyle.secondary,
                custom_id="aethelgard:v4:manage_void",
                row=1,
            )
            void_button.callback = self._void
            self.add_item(void_button)

        async def _void(self, interaction: discord.Interaction) -> None:
            permissions = getattr(interaction.user, "guild_permissions", None)
            if not (permissions and permissions.manage_guild):
                await interaction.response.send_message(
                    "You need the **Manage Server** permission to use this control.",
                    ephemeral=True,
                )
                return
            if interaction.guild is None:
                return
            state = main.store.get(interaction.guild.id) or dict(main.DEFAULT_GAME_STATE)
            await interaction.response.send_modal(
                WeeklyVoidModal(main, state, interaction.guild.id)
            )

    main.InterfaceView = InterfaceViewWithoutCorruption

    # Re-register /addresource without the removed Corruption choice.
    main.bot.tree.remove_command("addresource")
    resource_choices = [
        app_commands.Choice(name="Food", value="food"),
        app_commands.Choice(name="Materials", value="materials"),
        app_commands.Choice(name="Faith", value="faith"),
        app_commands.Choice(name="Citizens", value="citizens"),
        app_commands.Choice(name="Children", value="children"),
        app_commands.Choice(name="Birthrate", value="birthrate"),
        app_commands.Choice(name="Growth", value="growth"),
        app_commands.Choice(name="Barrier", value="barrier"),
        app_commands.Choice(name="Void Pressure", value="void_pressure"),
        app_commands.Choice(name="Nourishment", value="nourishment"),
        app_commands.Choice(name="Crime", value="crime"),
    ]

    @main.bot.tree.command(
        name="addresource",
        description="Admin helper to directly add or subtract a game value.",
    )
    @app_commands.choices(resource_type=resource_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def addresource(
        interaction: discord.Interaction,
        resource_type: app_commands.Choice[str],
        value: int,
    ) -> None:
        if interaction.guild is None:
            return
        state, result = main.store.add_resource(
            interaction.guild.id,
            resource_type.value,
            value,
        )
        await main.refresh_saved_interface(interaction.guild, state)
        await main.refresh_event_message(interaction.guild, state)

        text = (
            f"**{resource_type.name}** changed by **{main.format_change(value)}**. "
            f"Current: **{state[resource_type.value]}**."
        )
        if result.get("births"):
            text += f" Created {result['births']} child(ren)."
        if result.get("matured"):
            text += f" Matured {result['matured']} child(ren)."
        await interaction.response.send_message(text, ephemeral=True)

    addresource.error(main.admin_error)

    original_setup_hook = main.bot.setup_hook

    async def setup_hook() -> None:
        await original_setup_hook()
        main.bot.add_view(InterfaceViewWithoutCorruption())

    main.bot.setup_hook = setup_hook
