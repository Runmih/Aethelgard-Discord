from __future__ import annotations

import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from config_store import DEFAULT_GAME_STATE, InterfaceStore

ENV_PATH = Path(".env")
ENV_TEMPLATE = """# Discord bot token from the Discord Developer Portal
DISCORD_TOKEN=

# Optional: your Discord test server ID for near-instant slash-command syncing
DISCORD_GUILD_ID=
"""


def ensure_env_file() -> None:
    """Create a blank .env template locally if one does not exist."""
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


def progress_bar(
    value: int,
    maximum: int = 100,
    segments: int = 10,
    filled: str = "⬜",
    empty: str = "⬛",
) -> str:
    """Build a compact emoji progress bar for Discord embeds."""
    if maximum <= 0:
        maximum = 1

    value = max(0, min(value, maximum))
    filled_segments = round((value / maximum) * segments)
    empty_segments = segments - filled_segments

    return f"{filled * filled_segments}{empty * empty_segments}"


def format_change(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def make_interface_embed(guild: discord.Guild, state: dict) -> discord.Embed:
    week = int(state.get("week", DEFAULT_GAME_STATE["week"]))
    food = int(state.get("food", DEFAULT_GAME_STATE["food"]))
    materials = int(state.get("materials", DEFAULT_GAME_STATE["materials"]))
    citizens = int(state.get("citizens", DEFAULT_GAME_STATE["citizens"]))
    faith = int(state.get("faith", DEFAULT_GAME_STATE["faith"]))
    corruption = int(state.get("corruption", DEFAULT_GAME_STATE["corruption"]))

    # Placeholder weekly modifiers until the actual game rules are implemented.
    faith_weekly_change = 10
    corruption_weekly_change = 10

    embed = discord.Embed(
        title=f"Aethelgard Interface • Week {week}",
        description="City management interface placeholder.",
    )

    embed.add_field(name="Food", value=f"{food}", inline=True)
    embed.add_field(name="Materials", value=f"{materials}", inline=True)
    embed.add_field(name="Citizens", value=f"{citizens}", inline=True)

    embed.add_field(
        name="Faith",
        value=(
            f"**Current:** {faith}/100\n"
            f"**Weekly:** {format_change(faith_weekly_change)}\n"
            f"{progress_bar(faith, filled='⬜')}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Corruption",
        value=(
            f"**Current:** {corruption}/100\n"
            f"**Weekly:** {format_change(corruption_weekly_change)}\n"
            f"{progress_bar(corruption, filled='🟪')}"
        ),
        inline=True,
    )

    embed.set_footer(
        text=f"Guild: {guild.name} • Food upkeep: 10 per citizen each week"
    )
    return embed


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

        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions is None or not permissions.manage_guild:
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


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")


@bot.event
async def setup_hook() -> None:
    bot.add_view(InterfaceView())

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


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is empty. Open the generated .env file and add your bot token."
        )

    bot.run(TOKEN)
