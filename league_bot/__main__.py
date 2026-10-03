"""Command line entry point: ``python -m league_bot [run|check|windows|status|start|stop|shot|macro|pixel]``."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import List, Optional

from .config import DEFAULT_ENV_FILE, ConfigError, Settings, load_settings
from .game import GameError, SlayerGame
from .macro import MacroError, resolve_coord
from .telegram_api import TelegramAPI, TelegramError

log = logging.getLogger("league_bot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="league-bot", description="Controla o Slayer Legend (Google Play Games) pelo Telegram.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="caminho do .env (padrao: .env na raiz do repo)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="inicia o bot do Telegram (padrao)")
    sub.add_parser("check", help="valida a configuracao e as macros sem tocar no jogo")
    sub.add_parser("windows", help="lista os titulos das janelas abertas (para achar SLAYER_WINDOW_TITLE)")
    sub.add_parser("status", help="mostra se o jogo esta rodando")
    sub.add_parser("start", help="inicia o jogo e roda a macro de inicio")
    sub.add_parser("stop", help="fecha o jogo")
    shot = sub.add_parser("shot", help="salva um screenshot da janela do jogo")
    shot.add_argument("path", nargs="?", default="shot.png", help="arquivo de saida (.png ou .bmp)")
    macro = sub.add_parser("macro", help="roda uma macro pelo nome")
    macro.add_argument("name")
    pixel = sub.add_parser("pixel", help="mostra a cor de um ponto da janela (para calibrar macros)")
    pixel.add_argument("x", help="coordenada x: 'center', 'NN%%' ou pixels")
    pixel.add_argument("y", help="coordenada y: 'center', 'NN%%' ou pixels")
    return parser


def setup_logging(log_file: str) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def _backend():
    from .winapi import Win32Backend
    return Win32Backend()


def _game(settings: Settings) -> SlayerGame:
    return SlayerGame(settings, _backend(), log=log.info)


def cmd_check(settings: Settings) -> int:
    problems = 0
    print("Configuracao:")
    for key, value in settings.summary().items():
        print(f"  {key} = {value}")
    if not settings.window_title:
        problems += 1
    print("Macros:")
    try:
        game = _game(settings)
    except OSError as exc:
        print(f"  (nao foi possivel validar neste sistema: {exc})")
        return 1 if problems else 0
    for name in game.list_macros():
        try:
            game.load_macro_steps(name)
            print(f"  OK    {name}")
        except (GameError, MacroError) as exc:
            problems += 1
            print(f"  ERRO  {name}: {exc}")
    if settings.window_title:
        found = game.status().window_found
        print(f"Janela '{settings.window_title}': {'encontrada' if found else 'nao encontrada (normal se o jogo esta fechado)'}")
    print("Tudo certo." if not problems else f"{problems} problema(s) encontrado(s).")
    return 1 if problems else 0


def cmd_pixel(settings: Settings, x_spec: str, y_spec: str) -> int:
    game = _game(settings)
    frame = game.screenshot()
    spec_x = x_spec if x_spec.endswith("%") or x_spec == "center" else int(x_spec)
    spec_y = y_spec if y_spec.endswith("%") or y_spec == "center" else int(y_spec)
    x, y = resolve_coord(spec_x, frame.width), resolve_coord(spec_y, frame.height)
    rgb = frame.pixel(x, y)
    if rgb is None:
        print(f"({x}, {y}) esta fora da janela ({frame.width}x{frame.height})")
        return 1
    print(f"janela {frame.width}x{frame.height}, ponto ({x}, {y}): cor [{rgb[0]}, {rgb[1]}, {rgb[2]}]")
    return 0


def run(args: argparse.Namespace) -> int:
    command = args.command or "run"
    try:
        settings = load_settings(env_file=args.env_file)
    except ConfigError as exc:
        print(f"Erro de configuracao: {exc}", file=sys.stderr)
        return 2
    setup_logging(settings.log_file)

    try:
        if command == "check":
            return cmd_check(settings)
        if command == "windows":
            for title in sorted(set(_backend().list_windows()), key=str.lower):
                print(title)
            return 0
        if command == "run":
            from .bot import LeagueBot
            api = TelegramAPI(settings.require_token())
            LeagueBot(settings, api, _game(settings)).serve_forever()
            return 0
        if command == "status":
            st = _game(settings).status()
            print(f"jogo: {'rodando' if st.running else 'parado'} | janela: {'encontrada' if st.window_found else 'nao encontrada'}")
            return 0
        if command == "start":
            print(_game(settings).start())
            return 0
        if command == "stop":
            print(_game(settings).stop())
            return 0
        if command == "shot":
            frame = _game(settings).screenshot()
            path = Path(args.path)
            path.write_bytes(frame.to_bmp() if path.suffix.lower() == ".bmp" else frame.to_png())
            print(f"salvo em {path.resolve()}")
            return 0
        if command == "macro":
            print(_game(settings).run_macro(args.name))
            return 0
        if command == "pixel":
            return cmd_pixel(settings, args.x, args.y)
    except KeyboardInterrupt:
        print("\nEncerrado.")
        return 0
    except (ConfigError, GameError, MacroError, TelegramError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
