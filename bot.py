from __future__ import annotations

import json
import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from config_store import DEFAULT_GAME_STATE, InterfaceStore

ENV_PATH = Path(".env")
BUILDINGS_PATH = Path("content/buildings.json")
ENV_TEMPLATE = """# Discord bot token from the Discord Developer Portal
DISCORD_TOKEN=

# Optional: your Discord test server ID for near-instant slash-command syncing
DISCORD_GUILD_ID=
"""


def ensure_env_file() -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text(ENV_TEMPLATE, encoding="utf-8")
        print("Created .env. Fill in DISCORD_TOKEN before starting the bot.")


ensure_env_file()
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID_RAW = os.getenv("DISCORD_GUILD_ID", "").strip()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
store = InterfaceStore()

SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"


def progress_bar(
    value: int,
    maximum: int = 100,
    segments: int = 10,
    filled: str = "⬜",
    empty: str = "⬛",
) -> str:
    if maximum <= 0:
        maximum = 1

    value = max(0, min(value, maximum))
    filled_segments = round((value / maximum) * segments)
    empty_segments = segments - filled_segments
    return f"{filled * filled_segments}{empty * empty_segments}"


def format_change(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def load_building_catalog() -> dict:
    try:
        data = json.loads(BUILDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load building catalog: {exc}")
        return {"categories": {}}
    return data if isinstance(data, dict) else {"categories": {}}


def make_interface_embed(guild: discord.Guild, state: dict) -> discord.Embed:
    week = int(state.get("week", DEFAULT_GAME_STATE["week"]))
    food = int(state.get("food", DEFAULT_GAME_STATE["food"]))
    materials = int(state.get("materials", DEFAULT_GAME_STATE["materials"]))
    citizens = int(state.get("citizens", DEFAULT_GAME_STATE["citizens"]))
    faith = int(state.get("faith", DEFAULT_GAME_STATE["faith"]))
    corruption = int(state.get("corruption", DEFAULT_GAME_STATE["corruption"]))

    faith_weekly_change = 10
    corruption_weekly_change = 10

    embed = discord.Embed(
        title=f"Aethelgard Interface • Week {week}",
        description=(
            f"**Food:** {food}\n"
            f"**Materials:** {materials}\n"
            f"**Citizens:** {citizens}\n\n"
            f"{SEPARATOR}\n"
            f"### Faith\n"
            f"**Current:** {faith}/100\n"
            f"**Weekly:** {format_change(faith_weekly_change)}\n"
            f"{progress_bar(faith, filled='⬜')}\n\n"
            f"{SEPARATOR}\n"
            f"### Corruption\n"
            f"**Current:** {corruption}/100\n"
            f"**Weekly:** {format_change(corruption_weekly_change)}\n"
            f"{progress_bar(corruption, filled='🟪')}"
        ),
    )

    embed.set_footer(
        text=f"Guild: {guild.name} • Food upkeep: 10 per citizen each week"
    )
    return embed


def make_building_embed(category_id: str) -> discord.Embed:
    catalog = load_building_catalog()
    categories = catalog.get("categories", {})
    category = categories.get(category_id)

    if not isinstance(category, dict):
        return discord.Embed(
            title="Aethelgard Buildings",
            description="Building catalog could not be loaded.",
        )

    category_name = str(category.get("name", category_id.title()))
    buildings = category.get("buildings", [])

    lines: list[str] = [
        f"Browse the **{category_name}** building catalog.",
        "",
    ]

    for building in buildings:
        if not isinstance(building, dict):
            continue

        name = str(building.get("name", "Unnamed Building"))
        description = str(building.get("description", ""))
        cost = building.get("cost", {})
        materials = cost.get("materials") if isinstance(cost, dict) else None
        build_time = building.get("build_time_weeks")
        sustain = building.get("sustain", [])
        effects = building.get("effects", [])

        lines.append(SEPARATOR)
        lines.append(f"### {name}")
        if description:
            lines.append(description)
        if materials is not None:
            lines.append(f"**Building Cost:** {materials} Materials")
        lines.append(
            f"**Building Time:** {build_time} week{'s' if build_time != 1 else ''}"
            if isinstance(build_time, int)
            else "**Building Time:** Not specified"
        )

        if sustain:
            lines.append("**Sustain:**")
            lines.extend(f"• {item}" for item in sustain)

        if effects:
            lines.append("**Effects:**")
            lines.extend(f"• {item}" for item in effects)

        lines.append("")

    embed = discord.Embed(
        title=f"Aethelgard Buildings • {category_name}",
        description="\n".join(lines),
    )
    embed.set_footer(text="Use the buttons below to change faction pages.")
    return embed


def user_can_manage_guild(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


async def refresh_saved_interface(guild: discord.Guild, state: dict) -> None:
    channel_id = state.get("channel_id")
    message_id = state.get("message_id")
    if not channel_id or not message_id:
        return

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        try:
            fetched = await guild.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        if not isinstance(fetched, discord.TextChannel):
            return
        channel = fetched

    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=make_interface_embed(guild, state), view=InterfaceView())
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


class ResetGameModal(discord.ui.Modal, title="Start a New Aethelgard Game"):
    food = discord.ui.TextInput(
        label="Starting Food",
        default=str(DEFAULT_GAME_STATE["food"]),
        required=True,
        max_length=9,
    )
    materials = discord.ui.TextInput(
        label="Starting Materials",
        default=str(DEFAULT_GAME_STATE["materials"]),
        required=True,
        max_length=9,
    )
    citizens = discord.ui.TextInput(
        label="Starting Citizens",
        default=str(DEFAULT_GAME_STATE["citizens"]),
        required=True,
        max_length=7,
    )
    faith = discord.ui.TextInput(
        label="Starting Faith (0-100)",
        default=str(DEFAULT_GAME_STATE["faith"]),
        required=True,
        max_length=3,
    )
    corruption = discord.ui.TextInput(
        label="Starting Corruption (0-100)",
        default=str(DEFAULT_GAME_STATE["corruption"]),
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not user_can_manage_guild(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to reset the game.",
                ephemeral=True,
            )
            return

        try:
            food = int(str(self.food))
            materials = int(str(self.materials))
            citizens = int(str(self.citizens))
            faith = int(str(self.faith))
            corruption = int(str(self.corruption))
        except ValueError:
            await interaction.response.send_message(
                "All starting variables must be whole numbers.",
                ephemeral=True,
            )
            return

        if food < 0 or materials < 0 or citizens < 0:
            await interaction.response.send_message(
                "Food, Materials, and Citizens cannot be negative.",
                ephemeral=True,
            )
            return

        if not 0 <= faith <= 100 or not 0 <= corruption <= 100:
            await interaction.response.send_message(
                "Faith and Corruption must be between 0 and 100.",
                ephemeral=True,
            )
            return

        state = store.reset_game(
            interaction.guild.id,
            food=food,
            materials=materials,
            citizens=citizens,
            faith=faith,
            corruption=corruption,
        )

        await interaction.response.send_message(
            "New game started at **Week 1** with the supplied starting values.",
            ephemeral=True,
        )
        await refresh_saved_interface(interaction.guild, state)


class ResetConfirmView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This reset confirmation belongs to another user.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Continue Reset", style=discord.ButtonStyle.danger)
    async def continue_reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.send_modal(ResetGameModal())

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Reset cancelled.", view=self)
        self.stop()


class InterfaceView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Advance Week",
        style=discord.ButtonStyle.primary,
        custom_id="aethelgard:advance_week",
    )
    async def advance_week(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button

        if interaction.guild is None:
            await interaction.response.send_message(
                "This button only works inside a Discord server.",
                ephemeral=True,
            )
            return

        if not user_can_manage_guild(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to advance the week.",
                ephemeral=True,
            )
            return

        state, food_cost = store.advance_week(interaction.guild.id)

        await interaction.response.edit_message(
            embed=make_interface_embed(interaction.guild, state),
            view=self,
        )

        await interaction.followup.send(
            f"Week advanced to **{state['week']}**. "
            f"Consumed **{food_cost} Food** for {state['citizens']} citizens.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Reset Game",
        style=discord.ButtonStyle.danger,
        custom_id="aethelgard:reset_game",
    )
    async def reset_game(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button

        if interaction.guild is None or not user_can_manage_guild(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to reset the game.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "**Reset the Aethelgard game?**\n"
            "This will replace the current game state. The interface channel and message will be kept.",
            view=ResetConfirmView(interaction.user.id),
            ephemeral=True,
        )


class BuildingCatalogView(discord.ui.View):
    def __init__(self, active_category: str = "estrus") -> None:
        super().__init__(timeout=None)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = child.custom_id == f"aethelgard:buildings:{active_category}"

    async def show_category(self, interaction: discord.Interaction, category_id: str) -> None:
        await interaction.response.edit_message(
            embed=make_building_embed(category_id),
            view=BuildingCatalogView(category_id),
        )

    @discord.ui.button(
        label="Purist",
        style=discord.ButtonStyle.secondary,
        custom_id="aethelgard:buildings:purist",
    )
    async def purist(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.show_category(interaction, "purist")

    @discord.ui.button(
        label="Evolutionist",
        style=discord.ButtonStyle.secondary,
        custom_id="aethelgard:buildings:evolutionist",
    )
    async def evolutionist(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.show_category(interaction, "evolutionist")

    @discord.ui.button(
        label="Estrus Alliance",
        style=discord.ButtonStyle.secondary,
        custom_id="aethelgard:buildings:estrus",
    )
    async def estrus(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.show_category(interaction, "estrus")


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")


@bot.event
async def setup_hook() -> None:
    bot.add_view(InterfaceView())
    bot.add_view(BuildingCatalogView())

    if GUILD_ID_RAW:
        try:
            guild = discord.Object(id=int(GUILD_ID_RAW))
        except ValueError as exc:
            raise RuntimeError("DISCORD_GUILD_ID must be a numeric Discord server ID.") from exc

        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"Synced {len(synced)} command(s) to guild {GUILD_ID_RAW}.")
    else:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} global command(s).")


@bot.tree.command(
    name="setup_interface",
    description="Create or move the Aethelgard interface panel to a channel.",
)
@app_commands.describe(channel="Channel that should contain the Aethelgard interface panel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_interface(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(
            "Please run this in a text channel or choose a text channel explicitly.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    existing = store.get(interaction.guild.id)
    state = existing or dict(DEFAULT_GAME_STATE)
    message: discord.Message | None = None
    view = InterfaceView()

    if existing and existing.get("channel_id") == target_channel.id:
        try:
            message = await target_channel.fetch_message(int(existing["message_id"]))
            await message.edit(
                embed=make_interface_embed(interaction.guild, state),
                view=view,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError, ValueError):
            message = None

    if message is None:
        message = await target_channel.send(
            embed=make_interface_embed(interaction.guild, state),
            view=view,
        )

    store.set(
        guild_id=interaction.guild.id,
        channel_id=target_channel.id,
        message_id=message.id,
    )

    await interaction.followup.send(
        f"Interface panel ready in {target_channel.mention}.\nSaved message ID: `{message.id}`",
        ephemeral=True,
    )


@bot.tree.command(
    name="setup_buildings",
    description="Create or move the Aethelgard building catalog to a channel.",
)
@app_commands.describe(channel="Channel that should contain the building catalog")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_buildings(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message(
            "Please run this in a text channel or choose a text channel explicitly.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    existing = store.get(interaction.guild.id)
    message: discord.Message | None = None
    default_category = "estrus"
    view = BuildingCatalogView(default_category)

    if existing and existing.get("building_channel_id") == target_channel.id:
        try:
            message = await target_channel.fetch_message(int(existing["building_message_id"]))
            await message.edit(
                embed=make_building_embed(default_category),
                view=view,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError, ValueError):
            message = None

    if message is None:
        message = await target_channel.send(
            embed=make_building_embed(default_category),
            view=view,
        )

    store.set_building_panel(
        guild_id=interaction.guild.id,
        channel_id=target_channel.id,
        message_id=message.id,
    )

    await interaction.followup.send(
        f"Building catalog ready in {target_channel.mention}.\nSaved message ID: `{message.id}`",
        ephemeral=True,
    )


@setup_interface.error
async def setup_interface_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the **Manage Server** permission to use this command."
    else:
        print(f"/setup_interface error: {error!r}")
        message = "The interface setup failed. Check the bot console for details."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@setup_buildings.error
async def setup_buildings_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the **Manage Server** permission to use this command."
    else:
        print(f"/setup_buildings error: {error!r}")
        message = "The building catalog setup failed. Check the bot console for details."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is empty. Open the generated .env file and add your bot token."
        )

    bot.run(TOKEN)
