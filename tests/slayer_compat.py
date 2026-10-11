"""Test-only compatibility facade for the former home-bot adapter API."""

import league_bot
from league_bot.config import load_settings
from league_bot.game import SlayerGame
from league_bot.slayer.game import SlayerDailyGame
from league_bot.slayer.navigation import load_attendance_screens, load_daily_navigation


class HomeSlayerGame(SlayerDailyGame):
    """Retain the legacy host placement expected by imported home feature tests."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("final_position", (1460, 202))
        super().__init__(*args, **kwargs)


def available():
    return True
