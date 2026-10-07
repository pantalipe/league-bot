import tempfile
import unittest
from pathlib import Path

from league_bot.config import ConfigError, Settings, load_settings, parse_env_file


class EnvFileTests(unittest.TestCase):
    def test_parses_comments_quotes_export_and_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "\ufeff# comment\n\nA=1\nexport B = two words \nC=\"quoted\"\nD='single'\nE=a=b\nnonsense\n",
                encoding="utf-8",
            )
            self.assertEqual(parse_env_file(path), {"A": "1", "B": "two words", "C": "quoted", "D": "single", "E": "a=b"})

    def test_missing_file_is_empty(self):
        self.assertEqual(parse_env_file(Path("definitely/not/here.env")), {})


class LoadSettingsTests(unittest.TestCase):
    def test_defaults(self):
        s = load_settings(environ={}, env_file=None)
        self.assertEqual(s.allowed_user_ids, frozenset())
        self.assertEqual(s.start_macro, "start_game")
        self.assertEqual(s.process_names, ("client.exe", "crosvm.exe"))
        self.assertTrue(s.foreground_input)
        self.assertEqual(s.max_command_age, 300)

    def test_real_environment_overrides_the_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("TELEGRAM_TOKEN=1:fromfile\nSLAYER_WINDOW_TITLE=File Title\n", encoding="utf-8")
            s = load_settings(environ={"TELEGRAM_TOKEN": "2:fromenv"}, env_file=path)
        self.assertEqual(s.telegram_token, "2:fromenv")
        self.assertEqual(s.window_title, "File Title")

    def test_user_ids_accept_commas_semicolons_and_spaces(self):
        s = load_settings(environ={"ALLOWED_USER_IDS": "1, 2;3,"}, env_file=None)
        self.assertEqual(s.allowed_user_ids, frozenset({1, 2, 3}))

    def test_invalid_values_raise_config_error(self):
        bad_envs = [
            {"ALLOWED_USER_IDS": "abc"},
            {"TELEGRAM_TOKEN": "no-colon"},
            {"SLAYER_FOREGROUND_INPUT": "maybe"},
            {"SLAYER_MAX_COMMAND_AGE": "-5"},
            {"SLAYER_MAX_COMMAND_AGE": "soon"},
            {"SLAYER_START_MACRO": "../evil"},
        ]
        for env in bad_envs:
            with self.subTest(env=env), self.assertRaises(ConfigError):
                load_settings(environ=env, env_file=None)

    def test_macros_dir_can_be_overridden(self):
        s = load_settings(environ={"SLAYER_MACROS_DIR": "some/where"}, env_file=None)
        self.assertEqual(s.macros_dir, Path("some/where"))
        self.assertEqual(load_settings(environ={}, env_file=None).macros_dir.name, "macros")

    def test_data_dir_can_be_overridden(self):
        s = load_settings(environ={"SLAYER_DATA_DIR": "some/state"}, env_file=None)
        self.assertEqual(s.data_dir, Path("some/state"))
        self.assertEqual(load_settings(environ={}, env_file=None).data_dir.name, "state")

    def test_bool_parsing(self):
        self.assertFalse(load_settings(environ={"SLAYER_FOREGROUND_INPUT": "off"}, env_file=None).foreground_input)
        self.assertTrue(load_settings(environ={"SLAYER_FOREGROUND_INPUT": "YES"}, env_file=None).foreground_input)

    def test_summary_never_contains_the_token(self):
        s = load_settings(environ={"TELEGRAM_TOKEN": "123456:SECRET-VALUE"}, env_file=None)
        self.assertNotIn("SECRET-VALUE", " ".join(s.summary().values()))
        self.assertEqual(s.summary()["TELEGRAM_TOKEN"], "set")

    def test_require_token(self):
        with self.assertRaises(ConfigError):
            Settings().require_token()
        self.assertEqual(Settings(telegram_token="1:a").require_token(), "1:a")


if __name__ == "__main__":
    unittest.main()
