"""Command line entry point: ``python -m league_bot <command>`` (see ``--help``)."""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import List, Optional

from .config import DEFAULT_ENV_FILE, ConfigError, Settings, load_settings
from .game import GameError, SlayerGame
from .library import LibraryError, MacroLibrary
from .macro import MacroError, resolve_coord
from .recorder import Recorder, RecorderError, vk_from_name
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

    record = sub.add_parser("record", help="grava seus cliques na janela do jogo como uma nova macro")
    record.add_argument("name", help="nome da macro (letras, numeros, '_' e '-')")
    record.add_argument("-d", "--description", default="", help="descricao curta")
    record.add_argument("-t", "--tag", action="append", default=[], help="tag (pode repetir)")
    record.add_argument("--no-anchor", action="store_true", help="nao grava a cor de cada clique (cliques 'cegos')")
    record.add_argument("--force", action="store_true", help="sobrescreve uma macro com o mesmo nome")
    record.add_argument("--stop-key", default="F10", help="tecla que termina a gravacao, F1 a F12 (padrao F10)")
    record.add_argument("--delay", type=float, default=3.0, help="segundos de contagem antes de comecar (padrao 3)")
    record.add_argument("--max-seconds", type=float, default=900.0, help="duracao maxima da gravacao (padrao 900)")

    sub.add_parser("macros", help="lista as macros (compartilhadas e locais)")
    show = sub.add_parser("show", help="mostra os passos de uma macro")
    show.add_argument("name")
    rename = sub.add_parser("rename", help="renomeia uma macro local")
    rename.add_argument("old")
    rename.add_argument("new")
    delete = sub.add_parser("delete", help="apaga uma macro local")
    delete.add_argument("name")
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


def cmd_record(settings: Settings, args: argparse.Namespace) -> int:
    library = MacroLibrary(settings.macros_dir)
    library.check_name(args.name)
    if library.find(args.name) is not None and not args.force:
        raise LibraryError(f"Ja existe uma macro chamada '{args.name}'. Escolha outro nome ou use --force.")
    if not settings.window_title:
        raise GameError("SLAYER_WINDOW_TITLE nao esta configurado. Rode `python -m league_bot windows` para ver os titulos.")
    stop_vk = vk_from_name(args.stop_key)
    backend = _backend()
    if backend.find_window(settings.window_title) is None:
        raise GameError(f"Janela '{settings.window_title}' nao encontrada: abra o jogo antes de gravar.")

    recorder = Recorder(
        backend, settings.window_title, anchors=not args.no_anchor, stop_vk=stop_vk,
        max_seconds=args.max_seconds, log=print,
    )
    stop_key = args.stop_key.upper()
    print(f"Vou gravar os cliques que voce der na janela do jogo. Para terminar: {stop_key} (ou Ctrl+C aqui).")
    seconds = int(args.delay)
    while seconds > 0:
        print(f"Comecando em {seconds}... (va para a janela do jogo)")
        time.sleep(1)
        seconds -= 1
    print("GRAVANDO. Jogue normalmente.")
    recording = recorder.record()
    print("Gravacao encerrada.")

    for warning in recording.warnings:
        print(f"aviso: {warning}")
    if recording.skipped_gestures:
        print(f"aviso: {recording.skipped_gestures} gesto(s) de arrastar/segurar foram ignorados (ainda nao suportados).")
    if recording.clicks == 0:
        print("Nenhum clique gravado; nada foi salvo.")
        return 1
    path = library.save(
        args.name, recording.steps, description=args.description, tags=args.tag,
        window=recording.window_size, overwrite=args.force,
    )
    print(f"Macro '{args.name}' salva: {recording.clicks} clique(s) em {recording.duration:.0f}s -> {path}")
    print(f"Para rodar: python -m league_bot macro {args.name}")
    return 0


def cmd_macros(settings: Settings) -> int:
    infos = MacroLibrary(settings.macros_dir).list()
    if not infos:
        print("Nenhuma macro.")
        return 0
    width = max(len(info.name) for info in infos)
    print(f"{'NOME':<{width}}  {'ORIGEM':<8} {'PASSOS':>6}  DESCRICAO")
    for info in infos:
        text = f"[ERRO] {info.error}" if info.error else info.description
        if info.tags:
            text = f"{text} [{', '.join(info.tags)}]".strip()
        print(f"{info.name:<{width}}  {info.source:<8} {info.steps:>6}  {text}".rstrip())
    return 0


def cmd_show(settings: Settings, name: str) -> int:
    library = MacroLibrary(settings.macros_dir)
    steps = library.load_steps(name)
    info = next(i for i in library.list() if i.name == name)
    print(f"{name} ({info.source}) - {info.path}")
    if info.description:
        print(info.description)
    for number, step in enumerate(steps, 1):
        params = " ".join(f"{key}={value}" for key, value in step.items() if key not in ("action", "_comment"))
        print(f"{number:>3}. {step['action']} {params}".rstrip())
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
        if command == "record":
            return cmd_record(settings, args)
        if command == "macros":
            return cmd_macros(settings)
        if command == "show":
            return cmd_show(settings, args.name)
        if command == "rename":
            path = MacroLibrary(settings.macros_dir).rename(args.old, args.new)
            print(f"'{args.old}' renomeada para '{args.new}' ({path})")
            return 0
        if command == "delete":
            MacroLibrary(settings.macros_dir).delete(args.name)
            print(f"Macro '{args.name}' apagada.")
            return 0
    except KeyboardInterrupt:
        print("\nEncerrado.")
        return 0
    except (ConfigError, GameError, MacroError, LibraryError, RecorderError, TelegramError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
