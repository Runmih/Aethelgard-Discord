from __future__ import annotations

from typing import Any

import discord

import extended_systems


_INSTALLED = False


def _clean_interface_embed(embed: discord.Embed) -> discord.Embed:
    """Apply display-only cleanup to the main interface embed."""
    description = embed.description or ""
    kept: list[str] = []

    for line in description.splitlines():
        stripped = line.strip()

        # Remove detail/breakdown lines requested from the lean interface.
        if stripped.startswith("↳"):
            continue
        if stripped.startswith("**Total Workforce Multiplier:**"):
            continue
        if stripped.startswith("**Healthcare:**"):
            continue

        kept.append(line)

    # Collapse accidental runs of blank lines created by removed detail rows.
    cleaned: list[str] = []
    previous_blank = False
    for line in kept:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        cleaned.append(line)
        previous_blank = blank

    embed.description = "\n".join(cleaned).strip()
    embed.set_footer(text=None)
    return embed


async def _refresh_event_panel(
    main: Any,
    guild: discord.Guild,
    state: dict,
    summary: dict | None = None,
) -> None:
    """Edit the one saved event panel instead of following interaction channels."""
    event_meta = main.event_store.get(guild.id)
    saved_channel = await main._get_text_channel(guild, event_meta.get("channel_id"))
    message_id = event_meta.get("message_id")
    desired_channel = await main._get_text_channel(guild, state.get("channel_id"))
    embed = main.make_events_embed(guild, state, summary)

    # If the saved panel is already in the configured interface channel, edit it.
    if (
        saved_channel is not None
        and desired_channel is not None
        and saved_channel.id == desired_channel.id
        and message_id
    ):
        try:
            message = await saved_channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # If the interface was deliberately moved, remove the old panel when possible.
    if (
        saved_channel is not None
        and desired_channel is not None
        and saved_channel.id != desired_channel.id
        and message_id
    ):
        try:
            old_message = await saved_channel.fetch_message(int(message_id))
            await old_message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    channel = desired_channel or saved_channel
    if channel is None:
        return

    try:
        message = await channel.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        return

    main.event_store.set_message(guild.id, channel.id, message.id)


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    previous_make_interface = main.make_interface_embed

    def make_interface_embed(guild: discord.Guild, state: dict) -> discord.Embed:
        return _clean_interface_embed(previous_make_interface(guild, state))

    async def refresh_event_message(
        guild: discord.Guild,
        state: dict,
        summary: dict | None = None,
        target_channel: discord.TextChannel | None = None,
    ) -> None:
        # target_channel is intentionally ignored here. state['channel_id'] is the
        # configured home of the persistent panels and prevents message spam when
        # commands are invoked from other channels.
        del target_channel
        await _refresh_event_panel(main, guild, state, summary)

        # Keep the existing expedition/outpost panel refresh behavior.
        desired_channel = await main._get_text_channel(guild, state.get("channel_id"))
        await extended_systems.refresh_expedition_message(
            main,
            guild,
            state,
            target_channel=desired_channel,
        )

    main.make_interface_embed = make_interface_embed
    main.refresh_event_message = refresh_event_message
