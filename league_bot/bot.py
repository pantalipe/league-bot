"""Telegram command handling for league-bot.

Security model: every command except /id requires the sender's Telegram user id
to be in ALLOWED_USER_IDS. With an empty list nobody is authorized (fail closed).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from . import texts
from .config import Settings
from .game import GameBusy, GameError, SlayerGame
from .macro import MacroError
from .telegram_api import TelegramAPI, TelegramError

log = logging.getLogger("league_bot")

COMMANDS: List[Tuple[str, str]] = [
    ("startgame", "Inicia o Slayer Legend e roda a macro de inicio"),
    ("stopgame", "Fecha o jogo"),
    ("status", "Mostra se o jogo esta rodando"),
    ("shot", "Screenshot da janela do jogo"),
    ("macro", "Roda uma macro: /macro <nome>"),
    ("cancel", "Cancela a macro em andamento"),
    ("rec", "Grava seus cliques como macro: /rec <nome>"),
    ("recstop", "Termina a gravacao"),
    ("id", "Mostra o seu ID do Telegram"),
    ("help", "Lista os comandos"),
]

HELP_TEXT = (
    "Comandos:\n"
    "/startgame - inicia o jogo e roda a macro de inicio\n"
    "/stopgame - fecha o jogo\n"
    "/status - estado do jogo\n"
    "/shot - screenshot da janela do jogo\n"
    "/macro <nome> - roda uma macro (sem nome: lista as disponiveis)\n"
    "/cancel - cancela a macro em andamento\n"
    "/rec <nome> - grava seus cliques como uma macro (termina com F10 ou /recstop)\n"
    "/recstop - termina a gravacao\n"
    "/id - mostra o seu ID do Telegram"
)

# Telegram rejects photos above 10 MB; leave some headroom.
MAX_PHOTO_BYTES = 9_000_000


def parse_command(text: str, bot_username: str = "") -> Optional[Tuple[str, List[str]]]:
    """Split "/cmd@bot arg1 arg2" into ("cmd", ["arg1", "arg2"]); None if not for this bot."""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return None
    name, _, target = parts[0][1:].partition("@")
    if target and bot_username and target.lower() != bot_username.lower():
        return None
    return name.lower(), parts[1:]


class LeagueBot:
    def __init__(self, settings: Settings, api: TelegramAPI, game: SlayerGame,
                 clock: Callable[[], float] = time.time) -> None:
        self._settings = settings
        self._api = api
        self._game = game
        self._clock = clock
        self._username = ""
        self._handlers: Dict[str, Callable[[int, List[str]], None]] = {
            "start": self._cmd_help,
            "help": self._cmd_help,
            "status": self._cmd_status,
            "startgame": self._cmd_startgame,
            "stopgame": self._cmd_stopgame,
            "shot": self._cmd_shot,
            "macro": self._cmd_macro,
            "cancel": self._cmd_cancel,
            "rec": self._cmd_rec,
            "recstop": self._cmd_recstop,
        }

    # -- plumbing --------------------------------------------------------------

    def _reply(self, chat_id: int, text: str) -> None:
        try:
            self._api.send_message(chat_id, text)
        except TelegramError as exc:
            log.warning("could not send reply: %s", exc)

    def _is_stale(self, message: dict) -> bool:
        max_age = self._settings.max_command_age
        sent = message.get("date")
        return bool(max_age) and isinstance(sent, (int, float)) and self._clock() - sent > max_age

    def handle_update(self, update: dict) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        parsed = parse_command(message.get("text") or "", self._username)
        if parsed is None:
            return
        command, args = parsed
        chat_id = message["chat"]["id"]
        user_id = (message.get("from") or {}).get("id")

        if command == "id":  # needed to bootstrap ALLOWED_USER_IDS, reveals nothing else
            self._reply(chat_id, f"Seu user id: {user_id}")
            return
        if user_id not in self._settings.allowed_user_ids:
            log.warning("rejected /%s from unauthorized user id=%s", command, user_id)
            self._reply(chat_id, "Nao autorizado. Peca ao dono do bot para adicionar o seu ID (mande /id).")
            return
        if self._is_stale(message):
            self._reply(chat_id, f"Comando /{command} ignorado: mensagem antiga demais.")
            return
        handler = self._handlers.get(command)
        if handler is None:
            self._reply(chat_id, "Comando desconhecido. Use /help.")
            return
        try:
            handler(chat_id, args)
        except GameBusy as exc:
            self._reply(chat_id, f"⏳ {exc}")
        except (GameError, MacroError) as exc:
            self._reply(chat_id, f"❌ {exc}")
        except Exception:
            log.exception("unexpected error handling /%s", command)
            self._reply(chat_id, "❌ Erro inesperado (veja o log do bot).")

    # -- commands --------------------------------------------------------------

    def _cmd_help(self, chat_id: int, args: List[str]) -> None:
        self._reply(chat_id, HELP_TEXT)

    def _cmd_status(self, chat_id: int, args: List[str]) -> None:
        st = self._game.status()
        lines = [
            f"Jogo: {'rodando' if st.running else 'parado'}",
            f"Janela: {'encontrada' if st.window_found else 'nao encontrada'}",
            f"Operacao em andamento: {'sim' if st.busy else 'nao'}",
        ]
        if st.recording:
            lines.append("Gravando macro: sim")
        self._reply(chat_id, "\n".join(lines))

    def _cmd_startgame(self, chat_id: int, args: List[str]) -> None:
        self._reply(chat_id, "▶️ Iniciando o Slayer Legend... pode levar alguns minutos.")
        self._reply(chat_id, "✅ " + self._game.start())

    def _cmd_stopgame(self, chat_id: int, args: List[str]) -> None:
        self._reply(chat_id, "⏹️ " + self._game.stop())

    def _cmd_shot(self, chat_id: int, args: List[str]) -> None:
        png = self._game.screenshot().to_png()
        caption = f"🖼️ Slayer Legend — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        if len(png) <= MAX_PHOTO_BYTES:
            self._api.send_photo(chat_id, png, caption)
        else:
            self._api.send_document(chat_id, png, "shot.png", caption)

    def _cmd_macro(self, chat_id: int, args: List[str]) -> None:
        if not args:
            names = ", ".join(self._game.list_macros()) or "(nenhuma)"
            self._reply(chat_id, f"Uso: /macro <nome>\nDisponiveis: {names}")
            return
        self._reply(chat_id, f"▶️ Rodando macro '{args[0]}'...")
        self._reply(chat_id, "✅ " + self._game.run_macro(args[0]))

    def _cmd_rec(self, chat_id: int, args: List[str]) -> None:
        if not args:
            self._reply(chat_id, "Uso: /rec <nome> [anchor] [force]\nGrava seus cliques na janela do jogo. Termine com F10 ou /recstop.")
            return
        name, flags = args[0], {arg.lower() for arg in args[1:]}
        anchors = "anchor" in flags
        self._game.start_recording(
            name, anchors=anchors, overwrite="force" in flags,
            on_done=lambda result: self._reply(chat_id, texts.recording_result(result)),
        )
        self._reply(chat_id, texts.recording_started(name, anchors))

    def _cmd_recstop(self, chat_id: int, args: List[str]) -> None:
        if self._game.stop_recording():
            self._reply(chat_id, "⏹️ Terminando a gravacao...")
        else:
            self._reply(chat_id, "Nenhuma gravacao em andamento.")

    def _cmd_cancel(self, chat_id: int, args: List[str]) -> None:
        if self._game.cancel():
            self._reply(chat_id, "🛑 Cancelando a macro em andamento...")
        else:
            self._reply(chat_id, "Nada em andamento para cancelar.")

    # -- main loop -------------------------------------------------------------

    def serve_forever(self, stop: Optional[threading.Event] = None) -> None:
        stop = stop or threading.Event()
        self._username = self._api.get_me().get("username", "")  # a bad token fails right here
        if not self._settings.allowed_user_ids:
            log.warning("ALLOWED_USER_IDS is empty: every command except /id will be refused")
        try:
            self._api.set_commands(COMMANDS)
        except TelegramError as exc:
            log.warning("could not register the command menu: %s", exc)
        log.info("bot @%s is up (%d authorized user(s))", self._username, len(self._settings.allowed_user_ids))

        offset: Optional[int] = None
        delay = 1.0
        while not stop.is_set():
            try:
                updates = self._api.get_updates(offset)
                delay = 1.0
            except TelegramError as exc:
                if exc.code == 401:
                    raise  # invalid token: retrying cannot help
                log.warning("polling failed: %s (retrying in %.0fs)", exc, delay)
                stop.wait(exc.retry_after if exc.retry_after is not None else delay)
                delay = min(delay * 2, 30.0)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                # One thread per update so /status and /cancel work while a macro is running.
                threading.Thread(target=self.handle_update, args=(update,), daemon=True).start()
