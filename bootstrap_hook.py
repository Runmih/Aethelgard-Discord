from __future__ import annotations

import sys
from typing import Any

from discord.ext import commands


_INSTALLED = False
_ORIGINAL_RUN: Any = None


def install_bootstrap() -> None:
    """Install the extended Aethelgard systems after bot.py has finished loading.

    productivity_system is imported by bot.py before the Bot instance is run.
    Delaying installation until Bot.run keeps the extension modular and avoids
    circular imports while leaving the existing bot core untouched.
    """
    global _INSTALLED, _ORIGINAL_RUN
    if _INSTALLED:
        return
    _INSTALLED = True
    _ORIGINAL_RUN = commands.Bot.run

    def run_with_aethelgard_systems(self: commands.Bot, *args: Any, **kwargs: Any) -> Any:
        main = sys.modules.get("__main__")
        if main is not None and getattr(main, "bot", None) is self:
            from extended_systems import install
            from expedition_system import install as install_expedition_system
            from crime_system import install as install_crime_system
            from interface_cleanup import install as install_interface_cleanup
            from command_consolidation import install as install_command_consolidation
            from button_text_cleanup import install as install_button_text_cleanup

            install(main)
            install_expedition_system(main)
            install_crime_system(main)
            install_interface_cleanup(main)
            install_command_consolidation(main)
            install_button_text_cleanup(main)
        return _ORIGINAL_RUN(self, *args, **kwargs)

    commands.Bot.run = run_with_aethelgard_systems
