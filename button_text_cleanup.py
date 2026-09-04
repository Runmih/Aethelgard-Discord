from __future__ import annotations

from typing import Any

import discord


_INSTALLED = False


def install(main: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    previous_make_events = main.make_events_embed

    def make_events_embed(
        guild: discord.Guild,
        state: dict,
        summary: dict | None = None,
    ) -> discord.Embed:
        embed = previous_make_events(guild, state, summary)
        description = embed.description or ""
        description = description.replace(
            "Resolve with `/crime_resolve`.",
            "Use the **Resolve Event** button below.",
        )
        description = description.replace(
            "Resolve with `/kidnapping_resolve`.",
            "Use the **Resolve Event** button below.",
        )
        embed.description = description
        return embed

    main.make_events_embed = make_events_embed
