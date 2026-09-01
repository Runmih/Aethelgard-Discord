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
SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"


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


def progress_bar(value: int, maximum: int = 100, segments: int = 10, filled: str = "⬜", empty: str = "⬛") -> str:
    maximum = max(1, maximum)
    value = max(0, min(value, maximum))
    filled_segments = round((value / maximum) * segments)
    return f"{filled * filled_segments}{empty * (segments - filled_segments)}"


def format_change(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def user_can_manage_guild(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


def make_interface_embed(guild: discord.Guild, state: dict) -> discord.Embed:
    weekly = state.get("weekly", {})
    week = int(state.get("week", 1))
    food = int(state.get("food", 0))
    materials = int(state.get("materials", 0))
    citizens = int(state.get("citizens", 0))
    children = int(state.get("children", 0))
    birthrate = int(state.get("birthrate", 0))
    growth = int(state.get("growth", 0))
    nourishment = int(state.get("nourishment", 0))
    crime = int(state.get("crime", 0))
    faith = int(state.get("faith", 0))
    barrier = int(state.get("barrier", 0))
    void_pressure = int(state.get("void_pressure", 0))
    corruption = int(state.get("corruption", 0))

    food_income = int(weekly.get("food", 0))
    food_consumption = citizens * 10
    food_net = food_income - food_consumption

    description = (
        "### Resources\n"
        f"**Food:** {food} ({format_change(food_net)}/week)\n"
        f"↳ Income: {format_change(food_income)} | Consumption: -{food_consumption}\n"
        f"**Materials:** {materials} ({format_change(int(weekly.get('materials', 0)))}/week)\n"
        f"**Cum:** 0 ({format_change(int(weekly.get('cum', 7)))}/week, not stockpiled)\n\n"
        f"{SEPARATOR}\n"
        "### Population\n"
        f"**Citizens:** {citizens}\n"
        f"**Children:** {children}\n"
        f"**Birthrate:** {birthrate}/100 ({format_change(int(weekly.get('birthrate', 0)))}/week)\n"
        f"**Growth:** {growth}/728 ({format_change(int(weekly.get('growth', 1)))}/week while children exist)\n\n"
        f"{SEPARATOR}\n"
        "### City Stability\n"
        f"**Nourishment:** {nourishment}/100 ({format_change(int(weekly.get('nourishment', 0)))}/week)\n"
        f"{progress_bar(nourishment, filled='🟩')}\n"
        f"**Crime:** {crime}/100 ({format_change(int(weekly.get('crime', 0)))}/week)\n"
        f"{progress_bar(crime, filled='🟥')}\n"
        f"**Faith:** {faith}/100 ({format_change(int(weekly.get('faith', 0)))}/week)\n"
        f"{progress_bar(faith, filled='⬜')}\n\n"
        f"{SEPARATOR}\n"
        "### Barrier & Void\n"
        f"**Barrier:** {barrier}/100 ({format_change(int(weekly.get('barrier', 0)))}/week)\n"
        f"{progress_bar(barrier, filled='🟦')}\n"
        f"**Void Pressure:** {void_pressure}/9999 ({format_change(int(weekly.get('void_pressure', 0)))}/week)\n"
        f"**Corruption:** {corruption}/100 ({format_change(int(weekly.get('corruption', 0)))}/week)\n"
        f"{progress_bar(corruption, filled='🟪')}"
    )

    embed = discord.Embed(title=f"Aethelgard Interface • Week {week}", description=description)
    embed.set_footer(text=f"Guild: {guild.name} • Citizens consume 10 Food each per week")
    return embed


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


def vote_counts(vote: dict) -> tuple[int, int, int, float]:
    pro = len(vote.get("pro_votes", []))
    con = len(vote.get("con_votes", []))
    total = pro + con
    return pro, con, total, (pro / total * 100) if total else 0.0


def make_vote_embed(vote: dict) -> discord.Embed:
    pro, con, total, percentage = vote_counts(vote)
    required = int(vote.get("required_percentage", 60))
    status = str(vote.get("status", "open"))
    result = "✅ **PASSED**" if status == "passed" else "❌ **FAILED**" if status == "failed" else "🗳️ **Voting Open**"
    return discord.Embed(
        title="Aethelgard Vote",
        description=(
            f"### {vote.get('topic', 'Untitled Vote')}\n\n"
            f"**Pro:** {pro}\n**Con:** {con}\n**Total Votes:** {total}\n\n"
            f"**Approval:** {percentage:.1f}%\n**Required:** {required}%\n\n{result}"
        ),
    )


class WeeklyResourcesModal(discord.ui.Modal, title="Weekly Resources"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.food = discord.ui.TextInput(label="Food / week", default=str(weekly.get("food", 0)), required=True)
        self.materials = discord.ui.TextInput(label="Materials / week", default=str(weekly.get("materials", 0)), required=True)
        self.cum = discord.ui.TextInput(label="Cum / week", default=str(weekly.get("cum", 7)), required=True)
        for item in (self.food, self.materials, self.cum): self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(interaction.guild.id, food=int(str(self.food)), materials=int(str(self.materials)), cum=int(str(self.cum)))
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True); return
        await interaction.response.send_message("Weekly resources updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class WeeklyPopulationModal(discord.ui.Modal, title="Weekly Population"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.birthrate = discord.ui.TextInput(label="Birthrate / week", default=str(weekly.get("birthrate", 0)), required=True)
        self.growth = discord.ui.TextInput(label="Growth / week", default=str(weekly.get("growth", 1)), required=True)
        self.add_item(self.birthrate); self.add_item(self.growth)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(interaction.guild.id, birthrate=int(str(self.birthrate)), growth=int(str(self.growth)))
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True); return
        await interaction.response.send_message("Weekly population changes updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class WeeklyStabilityModal(discord.ui.Modal, title="Weekly City Stability"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.nourishment = discord.ui.TextInput(label="Nourishment / week", default=str(weekly.get("nourishment", 0)), required=True)
        self.crime = discord.ui.TextInput(label="Crime / week", default=str(weekly.get("crime", 0)), required=True)
        self.faith = discord.ui.TextInput(label="Faith / week", default=str(weekly.get("faith", 0)), required=True)
        for item in (self.nourishment, self.crime, self.faith): self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(interaction.guild.id, nourishment=int(str(self.nourishment)), crime=int(str(self.crime)), faith=int(str(self.faith)))
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True); return
        await interaction.response.send_message("Weekly stability changes updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class WeeklyVoidModal(discord.ui.Modal, title="Weekly Barrier & Void"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.barrier = discord.ui.TextInput(label="Barrier / week", default=str(weekly.get("barrier", 0)), required=True)
        self.void_pressure = discord.ui.TextInput(label="Void Pressure / week", default=str(weekly.get("void_pressure", 0)), required=True)
        self.corruption = discord.ui.TextInput(label="Corruption / week", default=str(weekly.get("corruption", 0)), required=True)
        for item in (self.barrier, self.void_pressure, self.corruption): self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(interaction.guild.id, barrier=int(str(self.barrier)), void_pressure=int(str(self.void_pressure)), corruption=int(str(self.corruption)))
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True); return
        await interaction.response.send_message("Weekly Barrier & Void changes updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class ResetGameModal(discord.ui.Modal, title="Start a New Aethelgard Game"):
    food = discord.ui.TextInput(label="Starting Food", default=str(DEFAULT_GAME_STATE["food"]), required=True)
    materials = discord.ui.TextInput(label="Starting Materials", default=str(DEFAULT_GAME_STATE["materials"]), required=True)
    citizens = discord.ui.TextInput(label="Starting Citizens", default=str(DEFAULT_GAME_STATE["citizens"]), required=True)
    faith = discord.ui.TextInput(label="Starting Faith (0-100)", default=str(DEFAULT_GAME_STATE["faith"]), required=True)
    corruption = discord.ui.TextInput(label="Starting Corruption (0-100)", default=str(DEFAULT_GAME_STATE["corruption"]), required=True)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            food = int(str(self.food)); materials = int(str(self.materials)); citizens = int(str(self.citizens)); faith = int(str(self.faith)); corruption = int(str(self.corruption))
        except ValueError:
            await interaction.response.send_message("All starting variables must be whole numbers.", ephemeral=True); return
        if food < 0 or materials < 0 or citizens < 0 or not 0 <= faith <= 100 or not 0 <= corruption <= 100:
            await interaction.response.send_message("Invalid starting values.", ephemeral=True); return
        state = store.reset_game(interaction.guild.id, food=food, materials=materials, citizens=citizens, faith=faith, corruption=corruption)
        await interaction.response.send_message("New game started at **Week 1**.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class ResetConfirmView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=60); self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This reset confirmation belongs to another user.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Continue Reset", style=discord.ButtonStyle.danger)
    async def continue_reset(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ResetGameModal())

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content="Reset cancelled.", view=self)


class VoteView(discord.ui.View):
    def __init__(self, status: str = "open") -> None:
        super().__init__(timeout=None)
        if status != "open":
            for child in self.children: child.disabled = True

    async def cast(self, interaction: discord.Interaction, choice: str) -> None:
        vote = store.cast_vote(interaction.guild.id, interaction.message.id, interaction.user.id, choice)
        if vote is None:
            await interaction.response.send_message("Voting on this item is closed.", ephemeral=True); return
        await interaction.response.edit_message(embed=make_vote_embed(vote), view=VoteView("open"))

    @discord.ui.button(label="Pro", style=discord.ButtonStyle.success, custom_id="aethelgard:vote:pro")
    async def pro(self, interaction: discord.Interaction, button: discord.ui.Button) -> None: await self.cast(interaction, "pro")

    @discord.ui.button(label="Con", style=discord.ButtonStyle.danger, custom_id="aethelgard:vote:con")
    async def con(self, interaction: discord.Interaction, button: discord.ui.Button) -> None: await self.cast(interaction, "con")

    @discord.ui.button(label="Conclude Vote", style=discord.ButtonStyle.primary, custom_id="aethelgard:vote:conclude")
    async def conclude(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        vote = store.get_vote(interaction.guild.id, interaction.message.id)
        if not vote:
            await interaction.response.send_message("This vote could not be found.", ephemeral=True); return
        if interaction.user.id != int(vote.get("creator_id", 0)) and not user_can_manage_guild(interaction):
            await interaction.response.send_message("Only the vote creator or someone with **Manage Server** can conclude it.", ephemeral=True); return
        _, _, total, percentage = vote_counts(vote)
        passed = total > 0 and percentage >= int(vote.get("required_percentage", 60))
        vote = store.conclude_vote(interaction.guild.id, interaction.message.id, passed)
        await interaction.response.edit_message(embed=make_vote_embed(vote), view=VoteView(vote["status"]))


class InterfaceView(discord.ui.View):
    def __init__(self) -> None: super().__init__(timeout=None)

    @discord.ui.button(label="Advance Week", style=discord.ButtonStyle.primary, custom_id="aethelgard:advance_week")
    async def advance_week(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not user_can_manage_guild(interaction):
            await interaction.response.send_message("You need the **Manage Server** permission to advance the week.", ephemeral=True); return
        state, _ = store.advance_week(interaction.guild.id)
        await interaction.response.edit_message(embed=make_interface_embed(interaction.guild, state), view=self)

    @discord.ui.button(label="Reset Game", style=discord.ButtonStyle.danger, custom_id="aethelgard:reset_game")
    async def reset_game(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not user_can_manage_guild(interaction):
            await interaction.response.send_message("You need the **Manage Server** permission to reset the game.", ephemeral=True); return
        await interaction.response.send_message("**Reset the Aethelgard game?**", view=ResetConfirmView(interaction.user.id), ephemeral=True)


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")


@bot.event
async def setup_hook() -> None:
    bot.add_view(InterfaceView()); bot.add_view(VoteView())
    if GUILD_ID_RAW:
        guild = discord.Object(id=int(GUILD_ID_RAW)); bot.tree.copy_global_to(guild=guild); synced = await bot.tree.sync(guild=guild)
    else:
        synced = await bot.tree.sync()
    print(f"Synced {len(synced)} command(s).")


@bot.tree.command(name="setup_interface", description="Create or move the Aethelgard interface panel to a channel.")
@app_commands.describe(channel="Channel that should contain the Aethelgard interface panel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_interface(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used inside a Discord server.", ephemeral=True); return
    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("Please choose a text channel.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    existing = store.get(interaction.guild.id); state = existing or dict(DEFAULT_GAME_STATE); message = None; view = InterfaceView()
    if existing and existing.get("channel_id") == target_channel.id:
        try:
            message = await target_channel.fetch_message(int(existing["message_id"])); await message.edit(embed=make_interface_embed(interaction.guild, state), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError, ValueError): message = None
    if message is None:
        message = await target_channel.send(embed=make_interface_embed(interaction.guild, state), view=view)
    store.set(interaction.guild.id, target_channel.id, message.id)
    await interaction.followup.send("Interface panel ready.", ephemeral=True)


async def open_weekly_modal(interaction: discord.Interaction, modal: discord.ui.Modal) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used inside a Discord server.", ephemeral=True); return
    await interaction.response.send_modal(modal)


@bot.tree.command(name="weekly_resources", description="Edit weekly Food, Materials, and Cum.")
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_resources(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyResourcesModal(store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)))


@bot.tree.command(name="weekly_population", description="Edit weekly Birthrate and Growth.")
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_population(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyPopulationModal(store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)))


@bot.tree.command(name="weekly_stability", description="Edit weekly Nourishment, Crime, and Faith.")
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_stability(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyStabilityModal(store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)))


@bot.tree.command(name="weekly_void", description="Edit weekly Barrier, Void Pressure, and Corruption.")
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_void(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyVoidModal(store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)))


RESOURCE_CHOICES = [
    app_commands.Choice(name="Food", value="food"), app_commands.Choice(name="Materials", value="materials"),
    app_commands.Choice(name="Faith", value="faith"), app_commands.Choice(name="Corruption", value="corruption"),
    app_commands.Choice(name="Citizens", value="citizens"), app_commands.Choice(name="Children", value="children"),
    app_commands.Choice(name="Birthrate", value="birthrate"), app_commands.Choice(name="Growth", value="growth"),
    app_commands.Choice(name="Barrier", value="barrier"), app_commands.Choice(name="Void Pressure", value="void_pressure"),
    app_commands.Choice(name="Nourishment", value="nourishment"), app_commands.Choice(name="Crime", value="crime"),
]


@bot.tree.command(name="addresource", description="Admin helper to directly add or subtract a game value.")
@app_commands.choices(resource_type=RESOURCE_CHOICES)
@app_commands.checks.has_permissions(manage_guild=True)
async def addresource(interaction: discord.Interaction, resource_type: app_commands.Choice[str], value: int) -> None:
    state, summary = store.add_resource(interaction.guild.id, resource_type.value, value)
    await refresh_saved_interface(interaction.guild, state)
    text = f"**{resource_type.name}** changed by **{format_change(value)}**. Current: **{state[resource_type.value]}**."
    if summary["births"]: text += f" Created {summary['births']} child(ren)."
    if summary["matured"]: text += f" Matured {summary['matured']} child(ren)."
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="vote", description="Create a simple Pro/Con vote with a required approval percentage.")
async def vote(interaction: discord.Interaction, topic: str, required_percentage: app_commands.Range[int, 1, 100] = 60) -> None:
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command can only be used in a server text channel.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    vote_data = {"topic": topic, "required_percentage": int(required_percentage), "creator_id": interaction.user.id, "status": "open", "pro_votes": [], "con_votes": []}
    message = await interaction.channel.send(embed=make_vote_embed(vote_data), view=VoteView())
    store.save_vote(interaction.guild.id, message.id, vote_data)
    await interaction.followup.send("Vote created.", ephemeral=True)


for command in (setup_interface, weekly_resources, weekly_population, weekly_stability, weekly_void, addresource):
    @command.error
    async def admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        message = "You need the **Manage Server** permission to use this command." if isinstance(error, app_commands.MissingPermissions) else "The command failed. Check the bot console for details."
        if interaction.response.is_done(): await interaction.followup.send(message, ephemeral=True)
        else: await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is empty. Open the generated .env file and add your bot token.")
    bot.run(TOKEN)
