"""Public construction helpers shared by the standalone bot and integrations."""
from pathlib import Path

from league_bot.config import Settings
from league_bot.daily import DailyList, DailyRunner
from league_bot.library import MacroLibrary
from .daily import HomeDailyRunner as SlayerDailyRunner
from .game import SlayerDailyGame
from .plan import DEFAULT_MACROS
from .selection import open_home_daily
from .status import DailyStatusStore
from .summons import read_summons

BUILTIN_MACROS = Path(__file__).resolve().parent / "macros"


class SlayerLibrary(MacroLibrary):
    """Installed package assets back up the default shared macro directory."""
    def __init__(self, directory):
        super().__init__(directory)
        self._builtin = BUILTIN_MACROS if Path(directory) == Settings().macros_dir else None

    def find(self, name):
        result = super().find(name)
        if result is None and self._builtin:
            path = self._builtin / (name + ".json")
            return path if path.is_file() else None
        return result

    def names(self):
        return sorted(set(super().names()) | (
            {p.stem for p in self._builtin.glob("*.json")} if self._builtin else set()))


def open_library(settings):
    return SlayerLibrary(settings.macros_dir)


def create_status(settings):
    return DailyStatusStore(Path(settings.data_dir) / "daily-status.json")


def open_daily(settings, library, *, path=None):
    """Seed the shipped plan; custom macro directories keep their own selection."""
    if all(library.find(name) is not None for name in DEFAULT_MACROS):
        return open_home_daily(settings, library, path=path)
    return DailyList(Path(path) if path else Path(settings.data_dir) / "daily.json", library)


def create_game(settings, backend, *, status_store=None, **kwargs):
    game = SlayerDailyGame(settings, backend, status_store=(
        status_store if status_store is not None else create_status(settings)), **kwargs)
    game._library = open_library(settings)
    return game


def create_daily(game, settings, *, log=None, **kwargs):
    selection = open_daily(settings, game.library)
    # Generic custom selections retain the original recorder-only runner.
    if not all(game.library.find(name) is not None for name in DEFAULT_MACROS):
        return DailyRunner(game, selection, log=log, **kwargs)
    if game._status_store is None:
        game._status_store = create_status(settings)
    return SlayerDailyRunner(game, selection, log=log,
                             status_store=game._status_store, **kwargs)
