"""Standalone commands, installed resources and no home-bot/runtime dependencies."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from league_bot.bot import LeagueBot
from league_bot.config import Settings
from league_bot.macro import validate_steps
from league_bot.game import SlayerGame, GameError
from league_bot.slayer import create_game, create_daily
from league_bot.slayer.api import BUILTIN_MACROS, create_status
from league_bot.slayer.commands import set_progress
from league_bot.slayer.plan import DEFAULT_MACROS


class SharedDailyPortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = replace(Settings(), window_title="Slayer Legend", data_dir=self.root / "state")

    def test_shipped_selection_and_all_steps_validate(self):
        game = create_game(self.settings, object())
        runner = create_daily(game, self.settings)
        self.assertEqual(set(runner.macros()[1:]), set(DEFAULT_MACROS))
        self.assertFalse(runner.missing())
        for name in (*DEFAULT_MACROS, "start_game_recognized"):
            validate_steps(game.load_macro_steps(name))

    def test_default_placement_has_no_host_coordinates(self):
        game = create_game(self.settings, object())
        self.assertEqual(game.final_steps(), [
            dict(action="move_resize", width=438, height=814), dict(action="minimize")])
        for name in (*DEFAULT_MACROS, "start_game_recognized"):
            steps = game.load_macro_steps(name)
            self.assertFalse(any(step.get("x") == 1460 for step in steps))

    def test_named_mission_and_alias_updates(self):
        store = create_status(self.settings)
        set_progress(store, ["Caverna de XP", "1", "3"])
        set_progress(store, ["espadas", "2"])
        snapshot = store.snapshot()
        self.assertEqual(snapshot["tasks"]["mission:caverna-de-xp"]["progress"], 1)
        self.assertEqual(snapshot["tasks"]["summon_sword"]["progress"], 2)
        set_progress(store, ["Caverna de XP", "2"])
        self.assertEqual(store.snapshot()["tasks"]["mission:caverna-de-xp"]["target"], 3)

    def test_telegram_status_updates_are_authorized_and_handle_quoted_names(self):
        messages = []
        api = SimpleNamespace(send_message=lambda chat, text: messages.append(text))
        bot = LeagueBot(replace(self.settings, allowed_user_ids=frozenset({1})), api,
                        SimpleNamespace(_status_store=create_status(self.settings)))
        def send(user, command):
            bot.handle_update(dict(message=dict(chat=dict(id=10), **{
                "from": dict(id=user), "text": command})))
        send(2, '/dailyset "Caverna XP" 2 3')
        self.assertFalse((self.settings.data_dir / "daily-status.json").exists())
        send(1, '/dailyset "Caverna XP" 2 3')
        send(1, '/dailystatus')
        self.assertIn("Caverna XP: 2/3", messages[-1])
        self.assertNotIn('"Caverna', messages[-1])

    def test_isolated_installed_layout_works_without_site_packages_or_homebot(self):
        source = Path(__file__).resolve().parents[1] / "league_bot"
        shutil.copytree(source, self.root / "league_bot", ignore=shutil.ignore_patterns('__pycache__'))
        script = '''
import sys
from dataclasses import replace
from pathlib import Path
from league_bot.config import Settings
from league_bot.slayer import create_game, create_daily
from league_bot.macro import validate_steps
from league_bot.slayer.plan import DEFAULT_MACROS
settings = replace(Settings(), data_dir=Path.cwd()/"local-state", window_title="Slayer Legend")
game = create_game(settings, object())
daily = create_daily(game, settings)
assert daily.macros()[0] == "attendance_check" and len(daily.macros()) == 21 and not daily.missing()
for name in (*DEFAULT_MACROS, "start_game_recognized"):
    validate_steps(game.load_macro_steps(name))
assert "PIL" not in sys.modules and "league_adapter" not in sys.modules
assert not any("panda-home-bot" in str(m.__file__) for m in list(sys.modules.values())
               if getattr(m, "__file__", None))
print("standalone stdlib: 20 macros validated")
'''
        result = subprocess.run([sys.executable, "-S", "-c", script], cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_macro_documents_exclude_local_recording_metadata(self):
        for name in DEFAULT_MACROS:
            document = json.loads((BUILTIN_MACROS / (name + '.json')).read_text(encoding='utf-8'))
            self.assertEqual(set(document), {'description', 'window', 'steps', 'tags'})
            self.assertNotIn('recordings', json.dumps(document).lower())

    def test_generic_game_cannot_replay_spending_sensitive_recordings(self):
        game = SlayerGame(self.settings, object())
        for name in ('pet_guild', 'cubo_de_melhora'):
            with self.subTest(name=name), self.assertRaisesRegex(GameError, 'fluxo visual'):
                game.run_macro(name)


if __name__ == '__main__':
    unittest.main()
