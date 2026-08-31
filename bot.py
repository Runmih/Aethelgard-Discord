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


def load_building_catalog() -> dict:
    try:
        data = json.loads(BUILDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load building catalog: {exc}")
        return {"categories": {}}
    return data if isinstance(data, dict) else {"categories": {}}


def building_lookup() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for category in load_building_catalog().get("categories", {}).values():
        if not isinstance(category, dict):
            continue
        for building in category.get("buildings", []):
            if isinstance(building, dict) and building.get("id"):
                result[str(building["id"])] = building
    return result


def get_building(building_id: str) -> dict | None:
    return building_lookup().get(building_id)


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


def format_building_instance(instance: dict, definitions: dict[str, dict]) -> list[str]:
    definition = definitions.get(str(instance.get("building_id")), {})
    name = str(definition.get("name", instance.get("building_id", "Unknown Building")))
    slot = int(instance.get("slot", 0))
    status = str(instance.get("status", "unknown"))

    if status == "constructing":
        return [f"**Slot {slot}: 🚧 {name}**", f"Completes: **Week {instance.get('completion_week', '?')}**"]

    enabled = bool(instance.get("enabled", True))
    lines = [f"**Slot {slot}: {'✅' if enabled else '⏸️'} {name}**"]
    sustain = definition.get("sustain", [])
    effects = definition.get("effects", [])
    if sustain:
        lines.append("Sustain: " + ", ".join(str(x) for x in sustain))
    if effects:
        lines.append("Output / Effect: " + "; ".join(str(x) for x in effects))
    return lines


def make_interface_embed(guild: discord.Guild, state: dict) -> discord.Embed:
    week = int(state.get("week", DEFAULT_GAME_STATE["week"]))
    food = int(state.get("food", DEFAULT_GAME_STATE["food"]))
    materials = int(state.get("materials", DEFAULT_GAME_STATE["materials"]))
    citizens = int(state.get("citizens", DEFAULT_GAME_STATE["citizens"]))
    faith = int(state.get("faith", DEFAULT_GAME_STATE["faith"]))
    corruption = int(state.get("corruption", DEFAULT_GAME_STATE["corruption"]))

    lines = [
        f"**Food:** {food}",
        f"**Materials:** {materials}",
        f"**Citizens:** {citizens}",
        "",
        SEPARATOR,
        "### Faith",
        f"**Current:** {faith}/100",
        f"**Weekly:** {format_change(10)}",
        progress_bar(faith, filled="⬜"),
        "",
        SEPARATOR,
        "### Corruption",
        f"**Current:** {corruption}/100",
        f"**Weekly:** {format_change(10)}",
        progress_bar(corruption, filled="🟪"),
        "",
        SEPARATOR,
        "### Buildings",
    ]

    definitions = building_lookup()
    buildings = state.get("buildings", [])
    if not buildings:
        lines.append("*No building slots occupied.*")
    else:
        for instance in buildings:
            if not isinstance(instance, dict):
                continue
            lines.extend(format_building_instance(instance, definitions))
            lines.append("")

    embed = discord.Embed(
        title=f"Aethelgard Interface • Week {week}",
        description="\n".join(lines),
    )
    embed.set_footer(text=f"Guild: {guild.name} • Food upkeep: 10 per citizen each week")
    return embed


def make_building_embed(category_id: str) -> discord.Embed:
    categories = load_building_catalog().get("categories", {})
    category = categories.get(category_id)
    if not isinstance(category, dict):
        return discord.Embed(title="Aethelgard Buildings", description="Building catalog could not be loaded.")

    category_name = str(category.get("name", category_id.title()))
    lines = [f"Browse the **{category_name}** building catalog.", ""]
    for building in category.get("buildings", []):
        if not isinstance(building, dict):
            continue
        name = str(building.get("name", "Unnamed Building"))
        description = str(building.get("description", ""))
        cost = building.get("cost", {})
        materials = cost.get("materials") if isinstance(cost, dict) else None
        build_time = building.get("build_time_weeks")
        sustain = building.get("sustain", [])
        effects = building.get("effects", [])

        lines.extend([SEPARATOR, f"### {name}"])
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

    embed = discord.Embed(title=f"Aethelgard Buildings • {category_name}", description="\n".join(lines))
    embed.set_footer(text="Change faction pages or select a building to propose below.")
    return embed


def proposal_ratio(proposal: dict) -> tuple[int, int, float]:
    pro = len(proposal.get("pro_votes", []))
    con = len(proposal.get("con_votes", []))
    total = pro + con
    return pro, con, (pro / total if total else 0.0)


def make_proposal_embed(state: dict, proposal: dict, building: dict) -> discord.Embed:
    pro, con, ratio = proposal_ratio(proposal)
    status = str(proposal.get("status", "proposed"))
    cost = int(building.get("cost", {}).get("materials", 0))
    current_materials = int(state.get("materials", 0))
    build_time = building.get("build_time_weeks")

    lines = [
        str(building.get("description", "")),
        "",
        f"**Cost:** {cost} Materials",
        f"**Building Time:** {build_time} week{'s' if build_time != 1 else ''}" if isinstance(build_time, int) else "**Building Time:** Not specified",
        f"**Current Materials:** {current_materials}",
        "✅ Affordable" if current_materials >= cost else "⚠️ Not currently affordable",
        "",
        f"**Pro:** {pro}",
        f"**Con:** {con}",
        f"**Approval:** {ratio * 100:.0f}%",
        "**Required:** 60%",
    ]

    if status == "proposed":
        lines.extend(["", "🗳️ **Voting Open**"])
    elif status == "approved":
        lines.extend(["", "✅ **Approved**", f"⏳ {proposal.get('waiting_reason', 'Awaiting construction.')}" ])
    elif status == "rejected":
        lines.extend(["", "❌ **Proposal Rejected**"])
    elif status == "constructing":
        lines.extend(["", "🚧 **Construction Started**", f"Completes: **Week {proposal.get('completion_week', '?')}**"])
    elif status == "active":
        lines.extend(["", "✅ **Construction Complete • Building Active**"])

    embed = discord.Embed(
        title=f"Building Proposal • {building.get('name', 'Unknown Building')}",
        description="\n".join(lines),
    )
    return embed


async def get_saved_interface_channel(guild: discord.Guild, state: dict) -> discord.TextChannel | None:
    channel_id = state.get("channel_id")
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    if isinstance(channel, discord.TextChannel):
        return channel
    try:
        fetched = await guild.fetch_channel(int(channel_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
    return fetched if isinstance(fetched, discord.TextChannel) else None


async def refresh_saved_interface(guild: discord.Guild, state: dict) -> None:
    channel = await get_saved_interface_channel(guild, state)
    message_id = state.get("message_id")
    if channel is None or not message_id:
        return
    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=make_interface_embed(guild, state), view=InterfaceView())
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def refresh_proposal_messages(guild: discord.Guild, state: dict) -> None:
    channel = await get_saved_interface_channel(guild, state)
    if channel is None:
        return
    definitions = building_lookup()
    for message_id, proposal in state.get("proposals", {}).items():
        if not isinstance(proposal, dict):
            continue
        building = definitions.get(str(proposal.get("building_id")))
        if not building:
            continue
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(
                embed=make_proposal_embed(state, proposal, building),
                view=ProposalView(str(proposal.get("status", "proposed"))),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            continue


class ResetGameModal(discord.ui.Modal, title="Start a New Aethelgard Game"):
    food = discord.ui.TextInput(label="Starting Food", default=str(DEFAULT_GAME_STATE["food"]), required=True, max_length=9)
    materials = discord.ui.TextInput(label="Starting Materials", default=str(DEFAULT_GAME_STATE["materials"]), required=True, max_length=9)
    citizens = discord.ui.TextInput(label="Starting Citizens", default=str(DEFAULT_GAME_STATE["citizens"]), required=True, max_length=7)
    faith = discord.ui.TextInput(label="Starting Faith (0-100)", default=str(DEFAULT_GAME_STATE["faith"]), required=True, max_length=3)
    corruption = discord.ui.TextInput(label="Starting Corruption (0-100)", default=str(DEFAULT_GAME_STATE["corruption"]), required=True, max_length=3)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not user_can_manage_guild(interaction):
            await interaction.response.send_message("You need the **Manage Server** permission to reset the game.", ephemeral=True)
            return
        try:
            food = int(str(self.food))
            materials = int(str(self.materials))
            citizens = int(str(self.citizens))
            faith = int(str(self.faith))
            corruption = int(str(self.corruption))
        except ValueError:
            await interaction.response.send_message("All starting variables must be whole numbers.", ephemeral=True)
            return
        if food < 0 or materials < 0 or citizens < 0:
            await interaction.response.send_message("Food, Materials, and Citizens cannot be negative.", ephemeral=True)
            return
        if not 0 <= faith <= 100 or not 0 <= corruption <= 100:
            await interaction.response.send_message("Faith and Corruption must be between 0 and 100.", ephemeral=True)
            return

        state = store.reset_game(
            interaction.guild.id,
            food=food,
            materials=materials,
            citizens=citizens,
            faith=faith,
            corruption=corruption,
        )
        await interaction.response.send_message("New game started at **Week 1** with the supplied starting values.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class ResetConfirmView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This reset confirmation belongs to another user.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Continue Reset", style=discord.ButtonStyle.danger)
    async def continue_reset(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await interaction.response.send_modal(ResetGameModal())

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="Reset cancelled.", view=self)
        self.stop()


class ProposalView(discord.ui.View):
    def __init__(self, status: str = "proposed") -> None:
        super().__init__(timeout=None)
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if child.custom_id in {"aethelgard:proposal:pro", "aethelgard:proposal:con"}:
                child.disabled = status != "proposed"
            elif child.custom_id == "aethelgard:proposal:conclude":
                child.disabled = status in {"rejected", "constructing", "active"}

    async def cast(self, interaction: discord.Interaction, vote: str) -> None:
        if interaction.guild is None or interaction.message is None:
            return
        proposal = store.cast_vote(interaction.guild.id, interaction.message.id, interaction.user.id, vote)
        if proposal is None:
            await interaction.response.send_message("Voting on this proposal is closed.", ephemeral=True)
            return
        state = store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)
        building = get_building(str(proposal.get("building_id")))
        if not building:
            await interaction.response.send_message("That building no longer exists in the catalog.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=make_proposal_embed(state, proposal, building), view=ProposalView("proposed"))

    @discord.ui.button(label="Pro", style=discord.ButtonStyle.success, custom_id="aethelgard:proposal:pro")
    async def pro(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.cast(interaction, "pro")

    @discord.ui.button(label="Con", style=discord.ButtonStyle.danger, custom_id="aethelgard:proposal:con")
    async def con(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.cast(interaction, "con")

    @discord.ui.button(label="Conclude Vote", style=discord.ButtonStyle.primary, custom_id="aethelgard:proposal:conclude")
    async def conclude(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or interaction.message is None:
            return
        if not user_can_manage_guild(interaction):
            await interaction.response.send_message("You need the **Manage Server** permission to conclude a vote.", ephemeral=True)
            return

        proposal = store.get_proposal(interaction.guild.id, interaction.message.id)
        if not proposal:
            await interaction.response.send_message("This proposal is no longer available.", ephemeral=True)
            return
        building = get_building(str(proposal.get("building_id")))
        if not building:
            await interaction.response.send_message("That building no longer exists in the catalog.", ephemeral=True)
            return

        pro, con, ratio = proposal_ratio(proposal)
        passed = (pro + con) > 0 and ratio >= 0.60
        proposal, state = store.conclude_proposal(
            interaction.guild.id,
            interaction.message.id,
            passed=passed,
            building=building,
        )
        if proposal is None:
            await interaction.response.send_message("Could not conclude this proposal.", ephemeral=True)
            return

        status = str(proposal.get("status", "proposed"))
        await interaction.response.edit_message(
            embed=make_proposal_embed(state, proposal, building),
            view=ProposalView(status),
        )
        await refresh_saved_interface(interaction.guild, state)


class BuildingSelect(discord.ui.Select):
    def __init__(self, category_id: str) -> None:
        category = load_building_catalog().get("categories", {}).get(category_id, {})
        options: list[discord.SelectOption] = []
        if isinstance(category, dict):
            for building in category.get("buildings", [])[:25]:
                if not isinstance(building, dict):
                    continue
                options.append(
                    discord.SelectOption(
                        label=str(building.get("name", "Unnamed Building"))[:100],
                        value=str(building.get("id", "")),
                        description="Propose this building for a vote",
                    )
                )
        if not options:
            options = [discord.SelectOption(label="No buildings available", value="none")]
        super().__init__(
            placeholder="Propose a building...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aethelgard:buildings:propose",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        building_id = self.values[0]
        building = get_building(building_id)
        if not building:
            await interaction.response.send_message("That building could not be found.", ephemeral=True)
            return

        state = store.get(interaction.guild.id)
        if not state or not state.get("channel_id"):
            await interaction.response.send_message("Set up the main interface first with `/setup_interface`.", ephemeral=True)
            return
        channel = await get_saved_interface_channel(interaction.guild, state)
        if channel is None:
            await interaction.response.send_message("The saved interface channel could not be accessed.", ephemeral=True)
            return

        proposal = {
            "building_id": building_id,
            "proposer_id": interaction.user.id,
            "created_week": int(state.get("week", 1)),
            "status": "proposed",
            "pro_votes": [],
            "con_votes": [],
        }
        message = await channel.send(embed=make_proposal_embed(state, proposal, building), view=ProposalView())
        store.save_proposal(interaction.guild.id, message.id, proposal)
        await interaction.response.send_message(
            f"Proposal created for **{building.get('name')}** in {channel.mention}.",
            ephemeral=True,
        )


class BuildingCatalogView(discord.ui.View):
    def __init__(self, active_category: str = "estrus") -> None:
        super().__init__(timeout=None)
        self.add_item(BuildingSelect(active_category))
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = child.custom_id == f"aethelgard:buildings:{active_category}"

    async def show_category(self, interaction: discord.Interaction, category_id: str) -> None:
        await interaction.response.edit_message(
            embed=make_building_embed(category_id),
            view=BuildingCatalogView(category_id),
        )

    @discord.ui.button(label="Purist", style=discord.ButtonStyle.secondary, custom_id="aethelgard:buildings:purist", row=0)
    async def purist(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.show_category(interaction, "purist")

    @discord.ui.button(label="Evolutionist", style=discord.ButtonStyle.secondary, custom_id="aethelgard:buildings:evolutionist", row=0)
    async def evolutionist(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.show_category(interaction, "evolutionist")

    @discord.ui.button(label="Estrus Alliance", style=discord.ButtonStyle.secondary, custom_id="aethelgard:buildings:estrus", row=0)
    async def estrus(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.show_category(interaction, "estrus")


class InterfaceView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Advance Week", style=discord.ButtonStyle.primary, custom_id="aethelgard:advance_week")
    async def advance_week(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None:
            await interaction.response.send_message("This button only works inside a Discord server.", ephemeral=True)
            return
        if not user_can_manage_guild(interaction):
            await interaction.response.send_message("You need the **Manage Server** permission to advance the week.", ephemeral=True)
            return

        state, summary = store.advance_week(interaction.guild.id, building_lookup())
        await interaction.response.edit_message(embed=make_interface_embed(interaction.guild, state), view=self)
        await refresh_proposal_messages(interaction.guild, state)

        details = [
            f"Week advanced to **{state['week']}**.",
            f"Food consumed: **{summary['food_consumed']}**.",
        ]
        if summary.get("food_produced"):
            details.append(f"Building food production: **+{summary['food_produced']}**.")
        if summary.get("completed"):
            names = [str(get_building(bid).get("name", bid)) if get_building(bid) else bid for bid in summary["completed"]]
            details.append("Completed: **" + ", ".join(names) + "**.")
        await interaction.followup.send("\n".join(details), ephemeral=True)

    @discord.ui.button(label="Reset Game", style=discord.ButtonStyle.danger, custom_id="aethelgard:reset_game")
    async def reset_game(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.guild is None or not user_can_manage_guild(interaction):
            await interaction.response.send_message("You need the **Manage Server** permission to reset the game.", ephemeral=True)
            return
        await interaction.response.send_message(
            "**Reset the Aethelgard game?**\nThis will replace the current game state. The interface and building-catalog locations will be kept.",
            view=ResetConfirmView(interaction.user.id),
            ephemeral=True,
        )


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")


@bot.event
async def setup_hook() -> None:
    bot.add_view(InterfaceView())
    bot.add_view(BuildingCatalogView())
    bot.add_view(ProposalView())

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


@bot.tree.command(name="setup_interface", description="Create or move the Aethelgard interface panel to a channel.")
@app_commands.describe(channel="Channel that should contain the Aethelgard interface panel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_interface(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used inside a Discord server.", ephemeral=True)
        return
    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("Please run this in a text channel or choose a text channel explicitly.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    existing = store.get(interaction.guild.id)
    state = existing or dict(DEFAULT_GAME_STATE)
    message: discord.Message | None = None
    view = InterfaceView()

    if existing and existing.get("channel_id") == target_channel.id:
        try:
            message = await target_channel.fetch_message(int(existing["message_id"]))
            await message.edit(embed=make_interface_embed(interaction.guild, state), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError, ValueError):
            message = None
    if message is None:
        message = await target_channel.send(embed=make_interface_embed(interaction.guild, state), view=view)

    store.set(interaction.guild.id, target_channel.id, message.id)
    await interaction.followup.send(
        f"Interface panel ready in {target_channel.mention}.\nSaved message ID: `{message.id}`",
        ephemeral=True,
    )


@bot.tree.command(name="setup_buildings", description="Create or move the Aethelgard building catalog to a channel.")
@app_commands.describe(channel="Channel that should contain the building catalog")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_buildings(interaction: discord.Interaction, channel: discord.TextChannel | None = None) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used inside a Discord server.", ephemeral=True)
        return
    target_channel = channel or interaction.channel
    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("Please run this in a text channel or choose a text channel explicitly.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    existing = store.get(interaction.guild.id)
    default_category = "estrus"
    view = BuildingCatalogView(default_category)
    message: discord.Message | None = None

    if existing and existing.get("building_channel_id") == target_channel.id:
        try:
            message = await target_channel.fetch_message(int(existing["building_message_id"]))
            await message.edit(embed=make_building_embed(default_category), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError, ValueError):
            message = None
    if message is None:
        message = await target_channel.send(embed=make_building_embed(default_category), view=view)

    store.set_building_panel(interaction.guild.id, target_channel.id, message.id)
    await interaction.followup.send(
        f"Building catalog ready in {target_channel.mention}.\nSaved message ID: `{message.id}`",
        ephemeral=True,
    )


async def setup_error(interaction: discord.Interaction, error: app_commands.AppCommandError, label: str) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the **Manage Server** permission to use this command."
    else:
        print(f"/{label} error: {error!r}")
        message = f"The {label} setup failed. Check the bot console for details."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@setup_interface.error
async def setup_interface_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    await setup_error(interaction, error, "setup_interface")


@setup_buildings.error
async def setup_buildings_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    await setup_error(interaction, error, "setup_buildings")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is empty. Open the generated .env file and add your bot token.")
    bot.run(TOKEN)
