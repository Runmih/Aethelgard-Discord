from __future__ import annotations

from typing import Any

import discord

from systems_store import systems_store


_INSTALLED = False


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
        self.cum_capacity = discord.ui.TextInput(
            label="Cum storage maximum",
            default=str(int(state.get("cum_capacity", 0))),
            required=True,
        )
        for item in (self.food, self.materials, self.cum_weekly, self.cum_capacity):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            food = int(str(self.food))
            materials = int(str(self.materials))
            cum_weekly = int(str(self.cum_weekly))
            cum_capacity = max(0, int(str(self.cum_capacity)))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.set_weekly_group(
            interaction.guild.id,
            food=food,
            materials=materials,
            cum=cum_weekly,
        )

        def mutate(entry: dict[str, Any]) -> None:
            entry["cum_capacity"] = cum_capacity
            entry["cum"] = min(max(0, int(entry.get("cum", 0))), cum_capacity)

        state = self.main.store._update(interaction.guild.id, mutate)
        await interaction.response.send_message("Resources updated.", ephemeral=True)
        await self.main.refresh_saved_interface(interaction.guild, state)


class PopulationRecoveryCrimeModal(discord.ui.Modal, title="Population"):
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
        self.crime = discord.ui.TextInput(
            label="Crime / week",
            default=str(int(weekly.get("crime", -20)) if int(weekly.get("crime", 0)) != 0 else -20),
            required=True,
        )
        for item in (self.birthrate, self.growth, self.recovery, self.crime):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            birthrate = int(str(self.birthrate))
            growth = int(str(self.growth))
            recovery = max(0, int(str(self.recovery)))
            crime = int(str(self.crime))
        except ValueError:
            await interaction.response.send_message("Values must be whole numbers.", ephemeral=True)
            return

        state = self.main.store.set_weekly_group(
            interaction.guild.id,
            birthrate=birthrate,
            growth=growth,
            crime=crime,
        )
        ext = systems_store.get(interaction.guild.id, str(state.get("difficulty", "normal")))
        systems_store.configure_healthcare(
            interaction.guild.id,
            str(state.get("difficulty", "normal")),
            patients=max(0, int(ext.get("patients", 0))),
            capacity=recovery,
        )
        enriched = systems_store.enrich(interaction.guild.id, state)
        await interaction.response.send_message(
            "Population, Recovery Speed, and Crime updated.",
            ephemeral=True,
        )
        await self.main.refresh_saved_interface(interaction.guild, enriched)
        await self.main.refresh_event_message(interaction.guild, enriched)


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Persist a Cum storage ceiling alongside the existing Cum stockpile.
    previous_normalize = main.store._normalize

    def normalize_with_cum_capacity(entry: dict[str, Any] | None) -> dict[str, Any]:
        result = previous_normalize(entry)
        source = entry if isinstance(entry, dict) else {}
        capacity = max(0, int(source.get("cum_capacity", result.get("cum_capacity", 0))))
        result["cum_capacity"] = capacity
        result["cum"] = min(max(0, int(result.get("cum", 0))), capacity)
        return result

    main.store._normalize = normalize_with_cum_capacity

    # Clamp weekly Cum production to the configured storage maximum.
    previous_advance_week = main.store.advance_week

    def advance_week_with_cum_capacity(guild_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
        state, summary = previous_advance_week(guild_id)
        capacity = max(0, int(state.get("cum_capacity", 0)))
        current = max(0, int(state.get("cum", 0)))
        if current > capacity:
            def mutate(entry: dict[str, Any]) -> None:
                entry["cum"] = capacity
            state = main.store._update(guild_id, mutate)
        return state, summary

    main.store.advance_week = advance_week_with_cum_capacity

    # Add the missing weekly display values and show Cum stock against capacity.
    previous_make_interface = main.make_interface_embed

    def make_interface_embed(guild: discord.Guild, state: dict[str, Any]) -> discord.Embed:
        embed = previous_make_interface(guild, state)
        weekly = state.get("weekly", {})
        ext = systems_store.get(guild.id, str(state.get("difficulty", "normal")))
        recovery = max(0, int(ext.get("healthcare_capacity", 0)))
        nourishment_weekly = int(weekly.get("nourishment", 0))
        cum = max(0, int(state.get("cum", 0)))
        cum_capacity = max(0, int(state.get("cum_capacity", 0)))
        cum_weekly = int(weekly.get("cum", 7))

        lines: list[str] = []
        for line in (embed.description or "").splitlines():
            if line.startswith("**Cum:**"):
                lines.append(
                    f"**Cum:** {cum}/{cum_capacity} ({_format_change(cum_weekly)}/week)"
                )
                continue
            if line.startswith("**Nourishment:**"):
                if " • " in line:
                    left, right = line.split(" • ", 1)
                    lines.append(
                        f"{left} ({_format_change(nourishment_weekly)}/week) • {right}"
                    )
                else:
                    lines.append(
                        f"{line} ({_format_change(nourishment_weekly)}/week)"
                    )
                continue
            if line.startswith("**Sickness:**"):
                sickness_change = -recovery
                if " • " in line:
                    left, right = line.split(" • ", 1)
                    lines.append(
                        f"{left} ({_format_change(sickness_change)}/week) • {right}"
                    )
                else:
                    lines.append(
                        f"{line} ({_format_change(sickness_change)}/week)"
                    )
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
                    "aethelgard:v2:manage_resources",
                    "aethelgard:v2:manage_population",
                }:
                    self.remove_item(item)

            resources = discord.ui.Button(
                label="Resources",
                style=discord.ButtonStyle.secondary,
                custom_id="aethelgard:v3:manage_resources",
                row=1,
            )
            resources.callback = self._resources
            self.add_item(resources)

            population = discord.ui.Button(
                label="Population",
                style=discord.ButtonStyle.secondary,
                custom_id="aethelgard:v3:manage_population",
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
                PopulationRecoveryCrimeModal(main, state, interaction.guild.id)
            )

    main.InterfaceView = AdjustedInterfaceView

    original_setup_hook = main.bot.setup_hook

    async def setup_hook() -> None:
        await original_setup_hook()
        main.bot.add_view(AdjustedInterfaceView())

    main.bot.setup_hook = setup_hook
