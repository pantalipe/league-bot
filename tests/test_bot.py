import threading
import unittest
from pathlib import Path
from unittest import mock

from league_bot import bot as bot_module
from league_bot.bot import LeagueBot, parse_command
from league_bot.config import Settings
from league_bot.daily import DailyBusy, DailyError, DailyResult
from league_bot.game import GameBusy, GameError, GameStatus, RecordingResult
from league_bot.imaging import solid_frame
from league_bot.macro import MacroError
from league_bot.telegram_api import TelegramError

NOW = 1_800_000_000.0
OWNER = 111
STRANGER = 999


class FakeApi:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.documents = []
        self.batches = []  # scripted get_updates results
        self.sent = threading.Event()

    def get_me(self):
        return {"username": "League_Bot"}

    def set_commands(self, commands):
        self.commands = commands

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))
        self.sent.set()

    def send_photo(self, chat_id, png, caption=""):
        self.photos.append((chat_id, png, caption))

    def send_document(self, chat_id, content, filename, caption=""):
        self.documents.append((chat_id, content, filename))

    def get_updates(self, offset=None, poll_timeout=25):
        item = self.batches.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeGame:
    def __init__(self):
        self.calls = []
        self.error = None
        self.cancel_result = True
        self.stop_result = True
        self.rec_kwargs = {}

    def _do(self, name, result=None):
        self.calls.append(name)
        if self.error:
            raise self.error
        return result

    def start(self):
        return self._do("start", "Slayer Legend iniciado.")

    def stop(self):
        return self._do("stop", "Slayer Legend finalizado.")

    def status(self):
        return self._do("status", GameStatus(running=True, window_found=False, busy=False))

    def screenshot(self):
        return self._do("screenshot", solid_frame(8, 8, (1, 2, 3)))

    def run_macro(self, name):
        return self._do("macro:" + name, f"Macro '{name}' concluida.")

    def list_macros(self):
        return ["start_game", "extra"]

    def start_recording(self, name, **kwargs):
        self.calls.append("rec:" + name)
        if self.error:
            raise self.error
        self.rec_kwargs = kwargs

    def stop_recording(self):
        self.calls.append("recstop")
        return self.stop_result

    def cancel(self):
        self.calls.append("cancel")
        return self.cancel_result


def update(text, user=OWNER, chat=10, date=NOW):
    return {"update_id": 1, "message": {"text": text, "date": date, "chat": {"id": chat}, "from": {"id": user}}}


class BotTestCase(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.game = FakeGame()
        self.settings = Settings(allowed_user_ids=frozenset({OWNER}), max_command_age=300)
        self.bot = LeagueBot(self.settings, self.api, self.game, clock=lambda: NOW + 5)
        self.bot._username = "League_Bot"

    def last_reply(self):
        return self.api.messages[-1][1]


class ParseTests(unittest.TestCase):
    def test_parse_command(self):
        self.assertEqual(parse_command("/macro start_game"), ("macro", ["start_game"]))
        self.assertEqual(parse_command("/StartGame@League_Bot", "league_bot"), ("startgame", []))
        self.assertIsNone(parse_command("/startgame@OtherBot", "league_bot"))
        self.assertIsNone(parse_command("just chatting"))
        self.assertIsNone(parse_command(""))


class AuthorizationTests(BotTestCase):
    def test_strangers_cannot_touch_the_game(self):
        for command in ["/startgame", "/stopgame", "/shot", "/status", "/macro start_game", "/cancel", "/help", "/rec quest", "/recstop"]:
            self.bot.handle_update(update(command, user=STRANGER))
        self.assertEqual(self.game.calls, [])
        self.assertTrue(all("Nao autorizado" in text for _, text in self.api.messages))
        self.assertEqual(self.api.photos, [])

    def test_empty_allowlist_refuses_everyone(self):
        bot = LeagueBot(Settings(), self.api, self.game, clock=lambda: NOW)
        bot.handle_update(update("/startgame"))
        self.assertEqual(self.game.calls, [])

    def test_id_works_for_anyone(self):
        self.bot.handle_update(update("/id", user=STRANGER))
        self.assertIn(str(STRANGER), self.last_reply())
        self.assertEqual(self.game.calls, [])

    def test_ignores_non_commands_and_other_bots(self):
        self.bot.handle_update(update("hello there"))
        self.bot.handle_update(update("/startgame@SomeoneElseBot"))
        self.bot.handle_update({"update_id": 2, "edited_message": {}})
        self.assertEqual((self.api.messages, self.game.calls), ([], []))

    def test_addressed_command_is_accepted(self):
        self.bot.handle_update(update("/startgame@league_bot"))
        self.assertEqual(self.game.calls, ["start"])

    def test_stale_commands_are_dropped(self):
        self.bot.handle_update(update("/startgame", date=NOW - 3600))
        self.assertEqual(self.game.calls, [])
        self.assertIn("antiga", self.last_reply())

    def test_stale_check_can_be_disabled(self):
        bot = LeagueBot(Settings(allowed_user_ids=frozenset({OWNER}), max_command_age=0), self.api, self.game, clock=lambda: NOW)
        bot.handle_update(update("/startgame", date=NOW - 3600))
        self.assertEqual(self.game.calls, ["start"])


class CommandTests(BotTestCase):
    def test_startgame_announces_then_reports(self):
        self.bot.handle_update(update("/startgame"))
        texts = [t for _, t in self.api.messages]
        self.assertIn("Iniciando", texts[0])
        self.assertIn("iniciado", texts[1])

    def test_stopgame_and_status(self):
        self.bot.handle_update(update("/stopgame"))
        self.assertIn("finalizado", self.last_reply())
        self.bot.handle_update(update("/status"))
        self.assertIn("Jogo: rodando", self.last_reply())
        self.assertIn("nao encontrada", self.last_reply())

    def test_shot_sends_a_png_photo(self):
        self.bot.handle_update(update("/shot"))
        chat, png, caption = self.api.photos[0]
        self.assertEqual((chat, png[:8]), (10, b"\x89PNG\r\n\x1a\n"))
        self.assertIn("Slayer Legend", caption)

    def test_huge_screenshots_fall_back_to_a_document(self):
        with mock.patch.object(bot_module, "MAX_PHOTO_BYTES", 10):
            self.bot.handle_update(update("/shot"))
        self.assertEqual((self.api.photos, len(self.api.documents)), ([], 1))

    def test_macro_lists_or_runs(self):
        self.bot.handle_update(update("/macro"))
        self.assertIn("extra", self.last_reply())
        self.bot.handle_update(update("/macro extra"))
        self.assertIn("macro:extra", self.game.calls)
        self.assertIn("concluida", self.last_reply())

    def test_cancel(self):
        self.bot.handle_update(update("/cancel"))
        self.assertIn("Cancelando", self.last_reply())
        self.game.cancel_result = False
        self.bot.handle_update(update("/cancel"))
        self.assertIn("Nada em andamento", self.last_reply())

    def test_unknown_command(self):
        self.bot.handle_update(update("/dance"))
        self.assertIn("desconhecido", self.last_reply())


class RecordingCommandTests(BotTestCase):
    def test_rec_without_a_name_explains_usage(self):
        self.bot.handle_update(update("/rec"))
        self.assertIn("Uso: /rec", self.last_reply())
        self.assertEqual(self.game.calls, [])

    def test_rec_starts_in_the_background_and_reports_when_done(self):
        self.bot.handle_update(update("/rec quest_1"))
        self.assertEqual(self.game.calls, ["rec:quest_1"])
        self.assertEqual((self.game.rec_kwargs["anchors"], self.game.rec_kwargs["overwrite"]), (False, False))
        self.assertIn("Gravando 'quest_1'", self.last_reply())
        self.game.rec_kwargs["on_done"](RecordingResult("quest_1", Path("x.json"), 3, 1, 12.0))
        reply = self.last_reply()
        self.assertIn("salva: 3 clique(s)", reply)
        self.assertIn("1 gesto(s)", reply)
        self.assertIn("/macro quest_1", reply)

    def test_rec_failure_is_shown_when_done(self):
        self.bot.handle_update(update("/rec quest_1"))
        self.game.rec_kwargs["on_done"](RecordingResult("quest_1", None, 0, 0, 3.0, (), "Nenhum clique gravado; nada foi salvo."))
        self.assertIn("Nenhum clique", self.last_reply())

    def test_rec_flags(self):
        self.bot.handle_update(update("/rec quest_1 ANCHOR force"))
        self.assertEqual((self.game.rec_kwargs["anchors"], self.game.rec_kwargs["overwrite"]), (True, True))
        self.assertIn("cor de cada clique", self.last_reply())

    def test_recstop(self):
        self.bot.handle_update(update("/recstop"))
        self.assertIn("Terminando", self.last_reply())
        self.game.stop_result = False
        self.bot.handle_update(update("/recstop"))
        self.assertIn("Nenhuma gravacao", self.last_reply())

    def test_rec_errors_are_reported(self):
        for error, marker in [(GameBusy("ocupado"), "⏳"), (GameError("sem janela"), "❌")]:
            self.game.error = error
            self.bot.handle_update(update("/rec quest_1"))
            self.assertIn(marker, self.last_reply())

    def test_status_shows_an_ongoing_recording(self):
        self.game.status = lambda: GameStatus(True, True, True, recording=True)
        self.bot.handle_update(update("/status"))
        self.assertIn("Gravando macro: sim", self.last_reply())


class FakeDaily:
    def __init__(self):
        self.entries = ["a", "b"]
        self.calls = []
        self.error = None
        self.cancel_result = False
        self.result = DailyResult(("b", "a"), ("b", "a"), "ok", "", solid_frame(2, 2, (1, 2, 3)))

    def _check(self):
        if self.error:
            raise self.error

    def macros(self):
        return list(self.entries)

    def missing(self):
        return []

    def add(self, name):
        self.calls.append("add:" + name)
        self._check()
        self.entries.append(name)

    def remove(self, name):
        self.calls.append("remove:" + name)
        self._check()
        self.entries.remove(name)

    def run(self, on_start=None):
        self.calls.append("run")
        self._check()
        if on_start:
            on_start(self.result.order)
        return self.result

    def cancel(self):
        self.calls.append("cancel")
        return self.cancel_result


class DailyCommandTests(BotTestCase):
    def setUp(self):
        super().setUp()
        self.daily = FakeDaily()
        self.bot = LeagueBot(self.settings, self.api, self.game, clock=lambda: NOW + 5, daily=self.daily)
        self.bot._username = "League_Bot"

    def test_strangers_cannot_touch_the_daily(self):
        for command in ["/daily", "/dailylist", "/dailyadd x", "/dailyremove a"]:
            self.bot.handle_update(update(command, user=STRANGER))
        self.assertEqual(self.daily.calls, [])

    def test_daily_announces_the_order_runs_and_sends_the_final_screen(self):
        self.bot.handle_update(update("/daily"))
        texts_sent = [t for _, t in self.api.messages]
        self.assertIn("b -> a", texts_sent[0])
        self.assertIn("Daily concluida (2 macro(s))", texts_sent[1])
        self.assertEqual(self.daily.calls, ["run"])
        chat, png, caption = self.api.photos[0]
        self.assertEqual((chat, png[:8]), (10, b"\x89PNG\r\n\x1a\n"))

    def test_a_failed_daily_is_reported_and_still_sends_the_screen(self):
        self.daily.result = DailyResult(("b", "a"), ("b",), "failed", "passo 3 falhou", solid_frame(2, 2, (1, 2, 3)))
        self.bot.handle_update(update("/daily"))
        self.assertIn("Daily falhou: passo 3 falhou", self.api.messages[-1][1])
        self.assertEqual(len(self.api.photos), 1)

    def test_no_screen_means_no_photo(self):
        self.daily.result = DailyResult(("b", "a"), ("b", "a"), "ok")
        self.bot.handle_update(update("/daily"))
        self.assertEqual(self.api.photos, [])

    def test_list_add_and_remove(self):
        self.bot.handle_update(update("/dailylist"))
        self.assertIn("• a", self.last_reply())
        self.bot.handle_update(update("/dailyadd c"))
        self.assertEqual(self.daily.calls, ["add:c"])
        self.assertIn("'c' entrou na daily", self.last_reply())
        self.assertIn("• c", self.last_reply())
        self.bot.handle_update(update("/dailyremove a"))
        self.assertIn("'a' saiu da daily", self.last_reply())
        self.assertNotIn("• a", self.last_reply())

    def test_add_and_remove_need_a_name(self):
        self.bot.handle_update(update("/dailyadd"))
        self.assertIn("Uso: /dailyadd", self.last_reply())
        self.bot.handle_update(update("/dailyremove"))
        self.assertIn("Uso: /dailyremove", self.last_reply())
        self.assertEqual(self.daily.calls, [])

    def test_errors_are_reported(self):
        for error, marker in [(DailyBusy("ja esta rodando"), "⏳"), (DailyError("vazia"), "❌")]:
            self.daily.error = error
            self.bot.handle_update(update("/daily"))
            self.assertIn(marker, self.last_reply())

    def test_cancel_prefers_the_running_daily(self):
        self.daily.cancel_result = True
        self.bot.handle_update(update("/cancel"))
        self.assertIn("Cancelando", self.last_reply())
        self.assertNotIn("cancel", self.game.calls)  # the daily already aborted the macro in progress

    def test_cancel_falls_back_to_the_game_when_no_daily_runs(self):
        self.bot.handle_update(update("/cancel"))
        self.assertEqual(self.game.calls, ["cancel"])

    def test_without_a_daily_the_commands_explain_it(self):
        bot = LeagueBot(self.settings, self.api, self.game, clock=lambda: NOW + 5)
        bot.handle_update(update("/daily"))
        self.assertIn("nao esta configurada", self.last_reply())


class ErrorHandlingTests(BotTestCase):
    def test_busy_game_error_and_macro_error_are_shown(self):
        for error, marker in [(GameBusy("ocupado"), "⏳"), (GameError("sem janela"), "❌"), (MacroError("passo 3"), "❌")]:
            self.game.error = error
            self.bot.handle_update(update("/stopgame"))
            self.assertIn(marker, self.last_reply())
            self.assertIn(str(error), self.last_reply())

    def test_unexpected_errors_do_not_leak_details(self):
        self.game.error = RuntimeError("secret internal path C:\\Users\\x")
        with self.assertLogs("league_bot", level="ERROR"):
            self.bot.handle_update(update("/stopgame"))
        self.assertNotIn("secret", self.last_reply())
        self.assertIn("Erro inesperado", self.last_reply())

    def test_failing_to_reply_does_not_crash_the_handler(self):
        self.api.send_message = mock.Mock(side_effect=TelegramError("offline"))
        with self.assertLogs("league_bot", level="WARNING"):
            self.bot.handle_update(update("/status"))


class ServeLoopTests(BotTestCase):
    def test_dispatches_updates_and_stops(self):
        stop = threading.Event()

        def second_poll():
            stop.set()
            return []

        class Script(list):
            def pop(self, index=0):
                item = super().pop(index)
                return item() if callable(item) else item

        self.api.batches = Script([[update("/status")], second_poll])
        self.bot.serve_forever(stop)
        self.assertTrue(self.api.sent.wait(2))
        self.assertEqual(self.game.calls, ["status"])
        self.assertEqual(self.bot._username, "League_Bot")

    def test_transient_errors_are_retried(self):
        stop = threading.Event()
        calls = []

        def poll(offset=None, poll_timeout=25):
            calls.append(offset)
            if len(calls) == 1:
                raise TelegramError("network down", retry_after=0)
            stop.set()
            return []

        self.api.get_updates = poll
        with self.assertLogs("league_bot", level="WARNING"):
            self.bot.serve_forever(stop)
        self.assertEqual(len(calls), 2)

    def test_invalid_token_is_fatal(self):
        self.api.batches = [TelegramError("Unauthorized", code=401)]
        with self.assertRaises(TelegramError):
            self.bot.serve_forever(threading.Event())


if __name__ == "__main__":
    unittest.main()
