import unittest
from pathlib import Path

from league_bot import texts
from league_bot.game import RecordingResult
from league_bot.library import MacroInfo


class RecordingTextTests(unittest.TestCase):
    def test_started_message_mentions_how_to_stop(self):
        text = texts.recording_started("quest_1")
        self.assertIn("quest_1", text)
        self.assertIn("F10", text)
        self.assertIn("/recstop", text)
        self.assertNotIn("cor de cada clique", text)
        self.assertIn("cor de cada clique", texts.recording_started("quest_1", anchors=True))

    def test_saved_result(self):
        result = RecordingResult("quest_1", Path("x.json"), 5, 2, 31.6, ("hit the time limit",))
        text = texts.recording_result(result)
        self.assertIn("salva: 5 clique(s) em 32s", text)
        self.assertIn("2 gesto(s)", text)
        self.assertIn("hit the time limit", text)
        self.assertTrue(text.endswith("Para rodar: /macro quest_1"))

    def test_run_command_is_configurable_for_other_front_ends(self):
        result = RecordingResult("q", Path("x.json"), 1, 0, 1.0)
        self.assertTrue(texts.recording_result(result, run_command="/runmacro").endswith("/runmacro q"))
        self.assertNotIn("gesto", texts.recording_result(result))

    def test_failed_result_shows_only_the_error(self):
        result = RecordingResult("q", None, 0, 0, 2.0, (), "Nenhum clique gravado; nada foi salvo.")
        self.assertEqual(texts.recording_result(result), "❌ Nenhum clique gravado; nada foi salvo.")


class MacroListTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(texts.macro_list([]), "Nenhuma macro.")

    def test_lists_source_steps_description_tags_and_errors(self):
        infos = [
            MacroInfo("quest_1", "local", Path("a"), 24, "Daily 1", ("daily",)),
            MacroInfo("start_game", "shared", Path("b"), 14),
            MacroInfo("broken", "local", Path("c"), 0, error="JSON invalido"),
        ]
        lines = texts.macro_list(infos).split("\n")
        self.assertEqual(lines[0], "Macros:")
        self.assertEqual(lines[1], "• quest_1 (local, 24 passo(s)) - Daily 1 [daily]")
        self.assertEqual(lines[2], "• start_game (shared, 14 passo(s))")
        self.assertEqual(lines[3], "• broken (local, 0 passo(s)) - ERRO: JSON invalido")


if __name__ == "__main__":
    unittest.main()
