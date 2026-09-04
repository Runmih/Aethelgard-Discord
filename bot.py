from __future__ import annotations

import os
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from config_store import DEFAULT_GAME_STATE, WORKFORCE_ROLES, InterfaceStore
from difficulty_store import list_difficulties
from event_store import EventStore
from nourishment_system import apply_food_nourishment_week, get_nourishment_tier
from productivity_system import (
    get_effective_weekly_food,
    get_faith_tier,
    get_workforce_multiplier_breakdown,
)

ENV_PATH = Path(".env")
ENV_TEMPLATE = """# Discord bot token from the Discord Developer Portal
DISCORD_TOKEN=

# Optional: your Discord test server ID for near-instant slash-command syncing
DISCORD_GUILD_ID=
"""
SEPARATOR = "━━━━━━━━━━━━━━━━━━━━"

ROLE_LABELS = {
    "scientists": "Scientists",
    "priestesses": "Priestesses",
    "engineers": "Engineers",
    "warriors": "Warriors",
}


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
event_store = EventStore()


def progress_bar(
    value: int,
    maximum: int = 100,
    segments: int = 10,
    filled: str = "⬜",
    empty: str = "⬛",
) -> str:
    maximum = max(1, maximum)
    value = max(0, min(value, maximum))
    filled_segments = round((value / maximum) * segments)
    return f"{filled * filled_segments}{empty * (segments - filled_segments)}"


def format_change(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def format_risk(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def user_can_manage_guild(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


def make_interface_embed(guild: discord.Guild, state: dict) -> discord.Embed:
    weekly = state.get("weekly", {})
    workforce = state.get("workforce", {})
    active_surge = state.get("active_void_surge")
    deaths = int(event_store.get(guild.id).get("deaths", 0))

    nourishment_tier = get_nourishment_tier(state)
    faith_tier = get_faith_tier(state)
    food_info = get_effective_weekly_food(state)
    multiplier_breakdown = get_workforce_multiplier_breakdown(state)

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

    food_base = int(food_info.get("base", 0))
    food_income = int(food_info.get("effective", 0))
    workforce_multiplier = float(food_info.get("multiplier", 1.0))
    food_consumption = citizens * 10
    food_net = food_income - food_consumption

    multiplier_sources = " • ".join(
        f"{item.get('source', 'Source')} ×{float(item.get('multiplier', 1.0)):.2f}"
        for item in multiplier_breakdown
    )

    barrier_generation = int(weekly.get("barrier", 0))
    barrier_net = barrier_generation - void_pressure

    surge_line = ""
    if isinstance(active_surge, dict):
        surge_line = (
            f"⚠️ **Void Surge Active:** ×{float(active_surge.get('multiplier', 1.0)):.2f} "
            f"through Week {int(active_surge.get('end_week', week))}\n"
        )

    nourishment_label = (
        f"{nourishment_tier.get('emoji', '')} {nourishment_tier.get('label', 'Stable')}"
    ).strip()
    faith_label = f"{faith_tier.get('emoji', '')} {faith_tier.get('label', 'Steady')}".strip()
    faith_workforce = float(faith_tier.get("workforce_multiplier", 1.0))
    faith_void_risk = int(faith_tier.get("void_exposure_risk", 0))
    ritual_power = float(faith_tier.get("ritual_power", 1.0))

    description = (
        "### Resources\n"
        f"**Food:** {food} ({format_change(food_net)}/week)\n"
        f"↳ Base income: {format_change(food_base)} ×{workforce_multiplier:.2f} = "
        f"{format_change(food_income)} | Consumption: -{food_consumption}\n"
        f"**Materials:** {materials} ({format_change(int(weekly.get('materials', 0)))}/week)\n"
        f"**Cum:** 0 ({format_change(int(weekly.get('cum', 7)))}/week, not stockpiled)\n\n"
        f"{SEPARATOR}\n"
        "### Population\n"
        f"**Citizens:** {citizens}\n"
        f"☠️ **Deaths:** {deaths}\n"
        "**Workforce**\n"
        f"🔬 Scientists: {int(workforce.get('scientists', 0))}\n"
        f"🙏 Priestesses: {int(workforce.get('priestesses', 0))}\n"
        f"⚙️ Engineers: {int(workforce.get('engineers', 0))}\n"
        f"⚔️ Warriors: {int(workforce.get('warriors', 0))}\n"
        f"**Total Workforce Multiplier:** ×{workforce_multiplier:.2f}\n"
        f"↳ {multiplier_sources}\n"
        f"**Children:** {children}\n"
        f"**Birthrate:** {birthrate}/100 ({format_change(int(weekly.get('birthrate', 0)))}/week)\n"
        f"**Growth:** {growth}/728 ({format_change(int(weekly.get('growth', 1)))}/week while children exist)\n\n"
        f"{SEPARATOR}\n"
        "### City Stability\n"
        f"**Nourishment:** {nourishment}/100 • {nourishment_label}\n"
        f"↳ Workforce ×{float(nourishment_tier.get('workforce_multiplier', 1.0)):.2f} • "
        f"Manual modifier {format_change(int(weekly.get('nourishment', 0)))}/week\n"
        f"{progress_bar(nourishment, filled='🟩')}\n"
        f"**Crime:** {crime}/100 ({format_change(int(weekly.get('crime', 0)))}/week)\n"
        f"{progress_bar(crime, filled='🟥')}\n"
        f"**Faith:** {faith}/100 ({format_change(int(weekly.get('faith', 0)))}/week) • {faith_label}\n"
        f"↳ Workforce ×{faith_workforce:.2f} • Void Risk {format_risk(faith_void_risk)} • "
        f"Ritual ×{ritual_power:.2f}\n"
        f"{progress_bar(faith, filled='⬜')}\n\n"
        f"{SEPARATOR}\n"
        "### Barrier & Void\n"
        f"**Barrier:** {barrier}/100 ({format_change(barrier_net)}/week)\n"
        f"↳ Generation: {format_change(barrier_generation)} | Void Pressure: -{void_pressure}\n"
        f"{progress_bar(barrier, filled='🟦')}\n"
        f"**Void Pressure:** {void_pressure}/9999\n"
        f"{surge_line}"
        f"**Corruption:** {corruption}/100 ({format_change(int(weekly.get('corruption', 0)))}/week)\n"
        f"{progress_bar(corruption, filled='🟪')}"
    )

    difficulty_name = str(state.get("difficulty", "normal")).title()
    embed = discord.Embed(title=f"Aethelgard Interface • Week {week}", description=description)
    embed.set_footer(
        text=f"Difficulty: {difficulty_name} • Food income is modified by total workforce efficiency"
    )
    return embed


def _effect_text(effects: dict) -> str:
    labels = {
        "crime": "Crime",
        "faith": "Faith",
        "corruption": "Corruption",
        "birthrate": "Birthrate",
        "growth": "Growth",
    }
    parts = []
    for key in ("crime", "faith", "corruption", "birthrate", "growth"):
        value = int(effects.get(key, 0))
        if value:
            parts.append(f"{labels[key]} {format_change(value)}")
    return " • ".join(parts)


def make_events_embed(guild: discord.Guild, state: dict, summary: dict | None = None) -> discord.Embed:
    week = int(state.get("week", 1))
    sections: list[str] = []
    summary = summary or {}

    active_surge = state.get("active_void_surge")
    if isinstance(active_surge, dict):
        end_week = int(active_surge.get("end_week", week))
        remaining = max(1, end_week - week + 1)
        surge_started = summary.get("void_surge")
        initial_line = ""
        if isinstance(surge_started, dict):
            initial_line = (
                f"\n**Initial surge:** {surge_started.get('before', 0)} → "
                f"**{surge_started.get('after', 0)}**"
            )
        sections.append(
            f"### {active_surge.get('title', '🌑 MAJOR VOID SURGE')}\n"
            f"{active_surge.get('text', '')}\n\n"
            f"**Surge #{active_surge.get('number', '?')}** • "
            f"Week {active_surge.get('start_week', '?')}–{end_week}\n"
            f"**Void Pressure ×{float(active_surge.get('multiplier', 1.0)):.2f}** • "
            f"{remaining} week{'s' if remaining != 1 else ''} remaining"
            f"{initial_line}"
        )

    nourishment_summary = summary.get("nourishment")
    tier = get_nourishment_tier(state)
    tier_id = str(tier.get("id", "stable"))

    if isinstance(nourishment_summary, dict):
        unfed = float(nourishment_summary.get("unfed_percent", 0.0))
        fed = float(nourishment_summary.get("fed_percent", 100.0))
        nourishment_change = int(nourishment_summary.get("nourishment_change", 0))
        if unfed > 0:
            base_food = int(nourishment_summary.get("food_base_income", 0))
            effective_food = int(nourishment_summary.get("food_effective_income", base_food))
            workforce_multiplier = float(nourishment_summary.get("workforce_multiplier", 1.0))
            sections.append(
                "### 🍽️ FOOD SHORTAGE\n"
                f"Only **{fed:.1f}%** of the population was fed this week.\n"
                f"**{unfed:.1f}% unfed** • Nourishment {format_change(nourishment_change)}\n"
                f"Food production: {format_change(base_food)} ×{workforce_multiplier:.2f} = "
                f"**{format_change(effective_food)}**"
            )

    if tier_id != "stable":
        effect_line = _effect_text(dict(tier))
        lines = [
            f"### {tier.get('emoji', '')} {tier.get('label', 'Nourishment')}".rstrip(),
            f"Nourishment is currently **{int(state.get('nourishment', 0))}/100**.",
        ]
        if effect_line:
            lines.append(f"**Weekly effects:** {effect_line}")

        if isinstance(nourishment_summary, dict):
            starvation = nourishment_summary.get("starvation")
            if isinstance(starvation, dict):
                roll = int(starvation.get("roll", 0))
                dc = int(starvation.get("dc", 16))
                if starvation.get("passed"):
                    lines.append(f"**Starvation roll:** {roll} vs DC {dc} • No deaths")
                else:
                    deaths = int(starvation.get("deaths", 0))
                    percent = int(starvation.get("death_percent", 0))
                    lines.append(
                        f"**Starvation roll:** {roll} vs DC {dc} • Failed\n"
                        f"☠️ **{deaths} citizen{'s' if deaths != 1 else ''} died** "
                        f"({percent}% of population)"
                    )
        sections.append("\n".join(lines))

    description = "*No active events.*" if not sections else f"\n\n{SEPARATOR}\n\n".join(sections)
    embed = discord.Embed(title=f"Aethelgard Events • Week {week}", description=description)
    embed.set_footer(text=f"Guild: {guild.name} • This message updates as events change")
    return embed


async def _get_text_channel(
    guild: discord.Guild,
    channel_id: int | None,
) -> discord.TextChannel | None:
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
    channel = await _get_text_channel(guild, state.get("channel_id"))
    message_id = state.get("message_id")
    if channel is None or not message_id:
        return
    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=make_interface_embed(guild, state), view=InterfaceView())
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def refresh_event_message(
    guild: discord.Guild,
    state: dict,
    summary: dict | None = None,
    target_channel: discord.TextChannel | None = None,
) -> None:
    event_meta = event_store.get(guild.id)
    saved_channel = await _get_text_channel(guild, event_meta.get("channel_id"))
    message_id = event_meta.get("message_id")
    embed = make_events_embed(guild, state, summary)

    if (
        saved_channel is not None
        and message_id
        and (target_channel is None or saved_channel.id == target_channel.id)
    ):
        try:
            message = await saved_channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    channel = target_channel or await _get_text_channel(guild, state.get("channel_id"))
    if channel is None:
        return
    try:
        message = await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        return
    event_store.set_message(guild.id, channel.id, message.id)


def vote_counts(vote: dict) -> tuple[int, int, int, float]:
    pro = len(vote.get("pro_votes", []))
    con = len(vote.get("con_votes", []))
    total = pro + con
    return pro, con, total, (pro / total * 100) if total else 0.0


def make_vote_embed(vote: dict) -> discord.Embed:
    pro, con, total, percentage = vote_counts(vote)
    required = int(vote.get("required_percentage", 60))
    status = str(vote.get("status", "open"))
    result = (
        "✅ **PASSED**"
        if status == "passed"
        else "❌ **FAILED**"
        if status == "failed"
        else "🗳️ **Voting Open**"
    )
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
        self.food = discord.ui.TextInput(
            label="Food base / week",
            default=str(weekly.get("food", 0)),
            required=True,
        )
        self.materials = discord.ui.TextInput(
            label="Materials / week",
            default=str(weekly.get("materials", 0)),
            required=True,
        )
        self.cum = discord.ui.TextInput(
            label="Cum / week",
            default=str(weekly.get("cum", 7)),
            required=True,
        )
        for item in (self.food, self.materials, self.cum):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(
                interaction.guild.id,
                food=int(str(self.food)),
                materials=int(str(self.materials)),
                cum=int(str(self.cum)),
            )
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True)
            return
        await interaction.response.send_message("Weekly resources updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class WeeklyPopulationModal(discord.ui.Modal, title="Weekly Population"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.birthrate = discord.ui.TextInput(
            label="Birthrate / week",
            default=str(weekly.get("birthrate", 0)),
            required=True,
        )
        self.growth = discord.ui.TextInput(
            label="Growth / week",
            default=str(weekly.get("growth", 1)),
            required=True,
        )
        self.add_item(self.birthrate)
        self.add_item(self.growth)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(
                interaction.guild.id,
                birthrate=int(str(self.birthrate)),
                growth=int(str(self.growth)),
            )
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True)
            return
        await interaction.response.send_message("Weekly population changes updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class WeeklyStabilityModal(discord.ui.Modal, title="Weekly City Stability"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.nourishment = discord.ui.TextInput(
            label="Nourishment modifier / week",
            default=str(weekly.get("nourishment", 0)),
            required=True,
        )
        self.crime = discord.ui.TextInput(
            label="Crime / week",
            default=str(weekly.get("crime", 0)),
            required=True,
        )
        self.faith = discord.ui.TextInput(
            label="Faith / week",
            default=str(weekly.get("faith", 0)),
            required=True,
        )
        for item in (self.nourishment, self.crime, self.faith):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(
                interaction.guild.id,
                nourishment=int(str(self.nourishment)),
                crime=int(str(self.crime)),
                faith=int(str(self.faith)),
            )
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True)
            return
        await interaction.response.send_message("Weekly stability changes updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class WeeklyVoidModal(discord.ui.Modal, title="Weekly Barrier & Void"):
    def __init__(self, state: dict) -> None:
        super().__init__()
        weekly = state.get("weekly", {})
        self.barrier = discord.ui.TextInput(
            label="Barrier generation / week",
            default=str(weekly.get("barrier", 0)),
            required=True,
        )
        self.void_pressure = discord.ui.TextInput(
            label="Extra Void Pressure / week",
            default=str(weekly.get("void_pressure", 0)),
            required=True,
        )
        self.corruption = discord.ui.TextInput(
            label="Corruption / week",
            default=str(weekly.get("corruption", 0)),
            required=True,
        )
        for item in (self.barrier, self.void_pressure, self.corruption):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = store.set_weekly_group(
                interaction.guild.id,
                barrier=int(str(self.barrier)),
                void_pressure=int(str(self.void_pressure)),
                corruption=int(str(self.corruption)),
            )
        except (ValueError, AttributeError):
            await interaction.response.send_message("All values must be whole numbers.", ephemeral=True)
            return
        await interaction.response.send_message("Weekly Barrier & Void changes updated.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


def workforce_defaults(state: dict) -> tuple[dict[str, int], dict[str, int], list[str]]:
    policy = state.get("workforce_policy", {})
    minimum = policy.get("minimum", {})
    ratio = policy.get("ratio", {})
    priority = policy.get("priority", list(WORKFORCE_ROLES))
    return (
        {role: int(minimum.get(role, 0)) for role in WORKFORCE_ROLES},
        {role: int(ratio.get(role, 25)) for role in WORKFORCE_ROLES},
        list(priority),
    )


class WorkforceMinimumModal(discord.ui.Modal, title="Workforce Minimums"):
    def __init__(self, owner_id: int, state: dict) -> None:
        super().__init__()
        self.owner_id = owner_id
        minimum, ratio, priority = workforce_defaults(state)
        self.ratio_defaults = ratio
        self.priority_defaults = priority

        self.scientists = discord.ui.TextInput(
            label="Scientists minimum",
            default=str(minimum["scientists"]),
            required=True,
        )
        self.priestesses = discord.ui.TextInput(
            label="Priestesses minimum",
            default=str(minimum["priestesses"]),
            required=True,
        )
        self.engineers = discord.ui.TextInput(
            label="Engineers minimum",
            default=str(minimum["engineers"]),
            required=True,
        )
        self.warriors = discord.ui.TextInput(
            label="Warriors minimum",
            default=str(minimum["warriors"]),
            required=True,
        )
        for item in (self.scientists, self.priestesses, self.engineers, self.warriors):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This workforce setup belongs to another user.",
                ephemeral=True,
            )
            return
        try:
            minimum = {
                "scientists": int(str(self.scientists)),
                "priestesses": int(str(self.priestesses)),
                "engineers": int(str(self.engineers)),
                "warriors": int(str(self.warriors)),
            }
        except ValueError:
            await interaction.response.send_message("Minimums must be whole numbers.", ephemeral=True)
            return
        if any(value < 0 for value in minimum.values()):
            await interaction.response.send_message("Minimums cannot be negative.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Minimums captured. Continue to workforce ratios.",
            view=WorkforceRatioContinueView(
                self.owner_id,
                minimum,
                self.ratio_defaults,
                self.priority_defaults,
            ),
            ephemeral=True,
        )


class WorkforceRatioContinueView(discord.ui.View):
    def __init__(
        self,
        owner_id: int,
        minimum: dict[str, int],
        ratio_defaults: dict[str, int],
        priority_defaults: list[str],
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.minimum = minimum
        self.ratio_defaults = ratio_defaults
        self.priority_defaults = priority_defaults

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This workforce setup belongs to another user.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Continue to Ratios", style=discord.ButtonStyle.primary)
    async def continue_to_ratios(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.send_modal(
            WorkforceRatioModal(
                self.owner_id,
                self.minimum,
                self.ratio_defaults,
                self.priority_defaults,
            )
        )


class WorkforceRatioModal(discord.ui.Modal, title="Workforce Ratios"):
    def __init__(
        self,
        owner_id: int,
        minimum: dict[str, int],
        ratio_defaults: dict[str, int],
        priority_defaults: list[str],
    ) -> None:
        super().__init__()
        self.owner_id = owner_id
        self.minimum = minimum
        self.priority_defaults = priority_defaults

        self.scientists = discord.ui.TextInput(
            label="Scientists %",
            default=str(ratio_defaults["scientists"]),
            required=True,
        )
        self.priestesses = discord.ui.TextInput(
            label="Priestesses %",
            default=str(ratio_defaults["priestesses"]),
            required=True,
        )
        self.engineers = discord.ui.TextInput(
            label="Engineers %",
            default=str(ratio_defaults["engineers"]),
            required=True,
        )
        self.warriors = discord.ui.TextInput(
            label="Warriors %",
            default=str(ratio_defaults["warriors"]),
            required=True,
        )
        for item in (self.scientists, self.priestesses, self.engineers, self.warriors):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This workforce setup belongs to another user.",
                ephemeral=True,
            )
            return
        try:
            ratio = {
                "scientists": int(str(self.scientists)),
                "priestesses": int(str(self.priestesses)),
                "engineers": int(str(self.engineers)),
                "warriors": int(str(self.warriors)),
            }
        except ValueError:
            await interaction.response.send_message("Ratios must be whole percentages.", ephemeral=True)
            return
        if any(value < 0 for value in ratio.values()):
            await interaction.response.send_message("Ratios cannot be negative.", ephemeral=True)
            return
        if sum(ratio.values()) != 100:
            await interaction.response.send_message(
                f"Workforce ratios must total **100%**. Current total: **{sum(ratio.values())}%**.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Ratios captured. Continue to priority.",
            view=WorkforcePriorityContinueView(
                self.owner_id,
                self.minimum,
                ratio,
                self.priority_defaults,
            ),
            ephemeral=True,
        )


class WorkforcePriorityContinueView(discord.ui.View):
    def __init__(
        self,
        owner_id: int,
        minimum: dict[str, int],
        ratio: dict[str, int],
        priority_defaults: list[str],
    ) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.minimum = minimum
        self.ratio = ratio
        self.priority_defaults = priority_defaults

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This workforce setup belongs to another user.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Continue to Priority", style=discord.ButtonStyle.primary)
    async def continue_to_priority(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await interaction.response.send_modal(
            WorkforcePriorityModal(
                self.owner_id,
                self.minimum,
                self.ratio,
                self.priority_defaults,
            )
        )


class WorkforcePriorityModal(discord.ui.Modal, title="Workforce Priority"):
    def __init__(
        self,
        owner_id: int,
        minimum: dict[str, int],
        ratio: dict[str, int],
        priority_defaults: list[str],
    ) -> None:
        super().__init__()
        self.owner_id = owner_id
        self.minimum = minimum
        self.ratio = ratio
        ranks = {
            role: index + 1
            for index, role in enumerate(priority_defaults)
            if role in WORKFORCE_ROLES
        }

        self.scientists = discord.ui.TextInput(
            label="Scientists priority (1-4)",
            default=str(ranks.get("scientists", 1)),
            required=True,
        )
        self.priestesses = discord.ui.TextInput(
            label="Priestesses priority (1-4)",
            default=str(ranks.get("priestesses", 2)),
            required=True,
        )
        self.engineers = discord.ui.TextInput(
            label="Engineers priority (1-4)",
            default=str(ranks.get("engineers", 3)),
            required=True,
        )
        self.warriors = discord.ui.TextInput(
            label="Warriors priority (1-4)",
            default=str(ranks.get("warriors", 4)),
            required=True,
        )
        for item in (self.scientists, self.priestesses, self.engineers, self.warriors):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This workforce setup belongs to another user.",
                ephemeral=True,
            )
            return
        try:
            ranks = {
                "scientists": int(str(self.scientists)),
                "priestesses": int(str(self.priestesses)),
                "engineers": int(str(self.engineers)),
                "warriors": int(str(self.warriors)),
            }
        except ValueError:
            await interaction.response.send_message(
                "Priorities must be whole numbers from 1 to 4.",
                ephemeral=True,
            )
            return
        if set(ranks.values()) != {1, 2, 3, 4}:
            await interaction.response.send_message(
                "Use each priority exactly once: **1, 2, 3, 4**.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            return

        priority = [role for role, rank in sorted(ranks.items(), key=lambda item: item[1])]
        try:
            state = store.set_workforce_policy(
                interaction.guild.id,
                minimum=self.minimum,
                ratio=self.ratio,
                priority=priority,
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message("Workforce policy saved.", ephemeral=True)
        await refresh_saved_interface(interaction.guild, state)


class DifficultySelect(discord.ui.Select):
    def __init__(self) -> None:
        difficulties = list_difficulties()
        options = [
            discord.SelectOption(
                label=item["name"],
                value=item["id"],
                description=(item.get("description") or None),
            )
            for item in difficulties
        ]
        if not options:
            options = [discord.SelectOption(label="Normal", value="normal")]
        super().__init__(
            placeholder="Choose difficulty",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, DifficultyResetView):
            return
        if interaction.user.id != view.owner_id:
            await interaction.response.send_message(
                "This reset menu belongs to another user.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            return

        difficulty_id = self.values[0]
        state = store.reset_game(interaction.guild.id, difficulty_id)
        event_store.reset(interaction.guild.id)
        await interaction.response.edit_message(
            content=f"New game started on **{difficulty_id.title()}** difficulty.",
            view=None,
        )
        await refresh_saved_interface(interaction.guild, state)
        await refresh_event_message(interaction.guild, state)


class DifficultyResetView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.add_item(DifficultySelect())


class VoteView(discord.ui.View):
    def __init__(self, status: str = "open") -> None:
        super().__init__(timeout=None)
        if status != "open":
            for child in self.children:
                child.disabled = True

    async def cast(self, interaction: discord.Interaction, choice: str) -> None:
        if interaction.guild is None or interaction.message is None:
            return
        vote = store.cast_vote(
            interaction.guild.id,
            interaction.message.id,
            interaction.user.id,
            choice,
        )
        if vote is None:
            await interaction.response.send_message(
                "Voting on this item is closed.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=make_vote_embed(vote),
            view=VoteView("open"),
        )

    @discord.ui.button(
        label="Pro",
        style=discord.ButtonStyle.success,
        custom_id="aethelgard:vote:pro",
    )
    async def pro(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.cast(interaction, "pro")

    @discord.ui.button(
        label="Con",
        style=discord.ButtonStyle.danger,
        custom_id="aethelgard:vote:con",
    )
    async def con(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        await self.cast(interaction, "con")

    @discord.ui.button(
        label="Conclude Vote",
        style=discord.ButtonStyle.primary,
        custom_id="aethelgard:vote:conclude",
    )
    async def conclude(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if interaction.guild is None or interaction.message is None:
            return
        vote = store.get_vote(interaction.guild.id, interaction.message.id)
        if not vote:
            await interaction.response.send_message(
                "This vote could not be found.",
                ephemeral=True,
            )
            return
        if (
            interaction.user.id != int(vote.get("creator_id", 0))
            and not user_can_manage_guild(interaction)
        ):
            await interaction.response.send_message(
                "Only the vote creator or someone with **Manage Server** can conclude it.",
                ephemeral=True,
            )
            return

        _, _, total, percentage = vote_counts(vote)
        passed = total > 0 and percentage >= int(vote.get("required_percentage", 60))
        concluded = store.conclude_vote(interaction.guild.id, interaction.message.id, passed)
        if concluded is None:
            await interaction.response.send_message(
                "Voting on this item is already closed.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=make_vote_embed(concluded),
            view=VoteView(concluded["status"]),
        )


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
        if not user_can_manage_guild(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to advance the week.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            return

        before_state = store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)
        state, summary = store.advance_week(interaction.guild.id)
        state, nourishment_summary = apply_food_nourishment_week(
            store,
            interaction.guild.id,
            before_state,
            state,
        )
        summary["nourishment"] = nourishment_summary

        deaths = int(nourishment_summary.get("deaths", 0))
        if deaths:
            event_store.add_deaths(interaction.guild.id, deaths)

        await interaction.response.edit_message(
            embed=make_interface_embed(interaction.guild, state),
            view=self,
        )
        target_channel = (
            interaction.channel
            if isinstance(interaction.channel, discord.TextChannel)
            else None
        )
        await refresh_event_message(
            interaction.guild,
            state,
            summary,
            target_channel=target_channel,
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
        if not user_can_manage_guild(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to reset the game.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Choose the difficulty for the new game:",
            view=DifficultyResetView(interaction.user.id),
            ephemeral=True,
        )


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'unknown'})")


@bot.event
async def setup_hook() -> None:
    bot.add_view(InterfaceView())
    bot.add_view(VoteView())
    if GUILD_ID_RAW:
        try:
            guild_id = int(GUILD_ID_RAW)
        except ValueError as exc:
            raise RuntimeError("DISCORD_GUILD_ID must be a numeric Discord server ID.") from exc
        guild = discord.Object(id=guild_id)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
    else:
        synced = await bot.tree.sync()
    print(f"Synced {len(synced)} command(s).")


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
        await interaction.response.send_message("Please choose a text channel.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    existing = store.get(interaction.guild.id)
    state = existing or dict(DEFAULT_GAME_STATE)
    message = None
    view = InterfaceView()

    if existing and existing.get("channel_id") == target_channel.id:
        try:
            message = await target_channel.fetch_message(int(existing["message_id"]))
            await message.edit(
                embed=make_interface_embed(interaction.guild, state),
                view=view,
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
            KeyError,
            ValueError,
        ):
            message = None

    if message is None:
        message = await target_channel.send(
            embed=make_interface_embed(interaction.guild, state),
            view=view,
        )

    state = store.set(interaction.guild.id, target_channel.id, message.id)
    await refresh_event_message(
        interaction.guild,
        state,
        target_channel=target_channel,
    )
    await interaction.followup.send("Interface and event panels ready.", ephemeral=True)


async def open_weekly_modal(
    interaction: discord.Interaction,
    modal_type: type[discord.ui.Modal],
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return
    state = store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)
    await interaction.response.send_modal(modal_type(state))


@bot.tree.command(name="weekly_resources", description="Edit weekly Food, Materials, and Cum.")
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_resources(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyResourcesModal)


@bot.tree.command(name="weekly_population", description="Edit weekly Birthrate and Growth.")
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_population(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyPopulationModal)


@bot.tree.command(
    name="weekly_stability",
    description="Edit Nourishment modifier, Crime, and Faith.",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_stability(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyStabilityModal)


@bot.tree.command(
    name="weekly_void",
    description="Edit Barrier generation, extra Void Pressure, and Corruption.",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def weekly_void(interaction: discord.Interaction) -> None:
    await open_weekly_modal(interaction, WeeklyVoidModal)


@bot.tree.command(
    name="workforce_setup",
    description="Configure workforce minimums, ratios, and priority.",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def workforce_setup(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return
    state = store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)
    await interaction.response.send_modal(
        WorkforceMinimumModal(interaction.user.id, state)
    )


@bot.tree.command(
    name="miracle",
    description="Spend Faith on a manually resolved Miracle.",
)
@app_commands.describe(faithcost="Faith spent on the Miracle")
@app_commands.checks.has_permissions(manage_guild=True)
async def miracle(
    interaction: discord.Interaction,
    faithcost: app_commands.Range[int, 1, 100],
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a Discord server.",
            ephemeral=True,
        )
        return

    state = store.get(interaction.guild.id) or dict(DEFAULT_GAME_STATE)
    faith = int(state.get("faith", 0))
    faith_tier = get_faith_tier(state)

    if not bool(faith_tier.get("miracle_available", False)):
        await interaction.response.send_message(
            f"A Miracle requires **100 Faith**. Current Faith: **{faith}/100**.",
            ephemeral=True,
        )
        return
    if faithcost > faith:
        await interaction.response.send_message(
            f"That Miracle costs **{faithcost} Faith**, but only **{faith}** is available.",
            ephemeral=True,
        )
        return

    state, _ = store.add_resource(interaction.guild.id, "faith", -int(faithcost))
    await refresh_saved_interface(interaction.guild, state)
    await refresh_event_message(interaction.guild, state)
    await interaction.response.send_message(
        f"☀️ Miracle invoked. **{faithcost} Faith** spent. "
        f"Faith: **{faith} → {int(state.get('faith', 0))}**.\n"
        "The Miracle's actual effect is resolved manually.",
        ephemeral=True,
    )


RESOURCE_CHOICES = [
    app_commands.Choice(name="Food", value="food"),
    app_commands.Choice(name="Materials", value="materials"),
    app_commands.Choice(name="Faith", value="faith"),
    app_commands.Choice(name="Corruption", value="corruption"),
    app_commands.Choice(name="Citizens", value="citizens"),
    app_commands.Choice(name="Children", value="children"),
    app_commands.Choice(name="Birthrate", value="birthrate"),
    app_commands.Choice(name="Growth", value="growth"),
    app_commands.Choice(name="Barrier", value="barrier"),
    app_commands.Choice(name="Void Pressure", value="void_pressure"),
    app_commands.Choice(name="Nourishment", value="nourishment"),
    app_commands.Choice(name="Crime", value="crime"),
]


@bot.tree.command(
    name="addresource",
    description="Admin helper to directly add or subtract a game value.",
)
@app_commands.choices(resource_type=RESOURCE_CHOICES)
@app_commands.checks.has_permissions(manage_guild=True)
async def addresource(
    interaction: discord.Interaction,
    resource_type: app_commands.Choice[str],
    value: int,
) -> None:
    if interaction.guild is None:
        return
    state, summary = store.add_resource(
        interaction.guild.id,
        resource_type.value,
        value,
    )
    await refresh_saved_interface(interaction.guild, state)
    await refresh_event_message(interaction.guild, state)

    text = (
        f"**{resource_type.name}** changed by **{format_change(value)}**. "
        f"Current: **{state[resource_type.value]}**."
    )
    if summary["births"]:
        text += f" Created {summary['births']} child(ren)."
    if summary["matured"]:
        text += f" Matured {summary['matured']} child(ren)."
        assigned = summary.get("workforce_added", {})
        parts = [
            f"{ROLE_LABELS[role]} +{assigned.get(role, 0)}"
            for role in WORKFORCE_ROLES
            if assigned.get(role, 0)
        ]
        if parts:
            text += " " + ", ".join(parts) + "."
    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(
    name="vote",
    description="Create a simple Pro/Con vote with a required approval percentage.",
)
async def vote(
    interaction: discord.Interaction,
    topic: str,
    required_percentage: app_commands.Range[int, 1, 100] = 60,
) -> None:
    if interaction.guild is None or not isinstance(
        interaction.channel,
        discord.TextChannel,
    ):
        await interaction.response.send_message(
            "This command can only be used in a server text channel.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    vote_data = {
        "topic": topic,
        "required_percentage": int(required_percentage),
        "creator_id": interaction.user.id,
        "status": "open",
        "pro_votes": [],
        "con_votes": [],
    }
    message = await interaction.channel.send(
        embed=make_vote_embed(vote_data),
        view=VoteView(),
    )
    store.save_vote(interaction.guild.id, message.id, vote_data)
    await interaction.followup.send("Vote created.", ephemeral=True)


async def admin_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the **Manage Server** permission to use this command."
    else:
        print(f"Admin command error: {error!r}")
        message = "The command failed. Check the bot console for details."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


for command in (
    setup_interface,
    weekly_resources,
    weekly_population,
    weekly_stability,
    weekly_void,
    workforce_setup,
    miracle,
    addresource,
):
    command.error(admin_error)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is empty. Open the generated .env file and add your bot token."
        )
    bot.run(TOKEN)
