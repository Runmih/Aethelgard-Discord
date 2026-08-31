from __future__ import annotations

import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from config_store import InterfaceStore

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

    return f"{filled * filled_segments}{empty * empty_segments}  **{value}/{maximum}**"


def make_interface_embed(guild: discord.Guild) -> discord.Embed:
    """Temporary interface panel. Replace these placeholders with live game variables later."""
    faith = 50
    corruption = 20

    embed = discord.Embed(
        title="Aethelgard Interface",
        description="City management interface placeholder.",
    )

    embed.add_field(name="Food", value="500", inline=True)
    embed.add_field(name="Materials", value="500", inline=True)
    embed.add_field(name="Citizens", value="20", inline=True)

    embed.add_field(
        name="Faith",
        value=progress_bar(faith, filled="⬜"),
        inline=False,
    )
    embed.add_field(
        name="Corruption",
        value=progress_bar(corruption, filled="🟪"),
        inline=False,
    )

    embed.set_footer(
        text=f"Guild: {guild.name} • This panel will later update automatically"
    )
    return embed


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")


@bot.event
async def setup_hook() -> None:
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
    message: discord.Message | None = None

    if existing and existing["channel_id"] == target_channel.id:
        try:
            message = await target_channel.fetch_message(existing["message_id"])
            await message.edit(embed=make_interface_embed(interaction.guild))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None

    if message is None:
        message = await target_channel.send(embed=make_interface_embed(interaction.guild))

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
