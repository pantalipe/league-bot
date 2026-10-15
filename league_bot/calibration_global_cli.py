"""Global calibration commands; offline commands never construct a game."""
from __future__ import annotations

import json
import time
from pathlib import Path


def add_parser(sub):
    parser = sub.add_parser("all", help="catalogo e calibracao de todas as telas e macros")
    parser.add_argument("operation", choices=("catalog", "status", "add", "capture", "guide",
                                              "propose", "validate", "apply", "rollback", "geometry", "tour"))
    parser.add_argument("--session", type=Path)
    parser.add_argument("--entry", help="ID do catalogo, mostrado por catalog")
    parser.add_argument("--label", choices=("positive", "negative"), default="positive")
    parser.add_argument("--images", type=Path, nargs="+")
    parser.add_argument("--macro", help="filtra uma macro no catalogo/guia")
    parser.add_argument("--resume", action="store_true", help="tour: retoma os destinos pendentes da sessao")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--interval", type=float, default=.3)
    parser.add_argument("--output", type=Path, help="salva catalogo/cobertura em JSON")


def run(args, settings, game_factory=None):
    from .slayer import calibration_global as engine
    from .slayer.calibration_inventory import inventory
    from .calibration_cli import _check_capture_options
    from .config import Settings

    session = args.session or settings.data_dir / "calibration" / "global-session"
    inv = inventory(None if settings.macros_dir == Settings().macros_dir else settings.macros_dir)
    op = args.operation
    if op == "catalog":
        selected = inv["entries"]
        if args.macro:
            ids = set(inv["macros"][args.macro]["entries"])
            selected = {k: v for k, v in selected.items() if k in ids}
        for ident, item in selected.items():
            print(f"{ident}  {item['kind']}  {item['name']}  {item['source']}{item['pointer']}")
        for error in inv["errors"]:
            print(f"ERRO: {error}")
        if args.output:
            _save(args.output, inv)
        print(f"{len(selected)} pontos catalogados; isso nao significa que estao calibrados.")
        return 1 if inv["errors"] else 0
    if op == "status":
        report = engine.coverage(session, inv=inv)
        if args.output:
            _save(args.output, report)
        print(f"Evidencias suficientes: {report['ready']}/{report['total']} reconhecedores; validacao separada em validate.")
        for name, macro in report["macros"].items():
            if not args.macro or args.macro == name:
                print(f"{name}: {macro['ready']}/{macro['total']} pontos de reconhecimento com evidencias; "
                      f"{macro.get('click_actions', 0)} cliques catalogados")
        return 0
    if op in ("capture", "guide", "geometry", "tour"):
        if game_factory is None:
            raise ValueError("captura requer um provedor de jogo")
        _check_capture_options(args.count, args.interval)
        if op == "geometry":
            from .winapi import Win32Backend
            backend = Win32Backend()
            if not settings.window_title.strip():
                raise ValueError("Configure SLAYER_WINDOW_TITLE para medir a janela.")
            hwnd = backend.find_window(settings.window_title)
            if hwnd is None:
                raise ValueError("Abra a janela do jogo para medir a area de referencia.")
            size = backend.client_size(hwnd)
            if tuple(size) != (434, 810):
                raise ValueError("A primeira referencia deve ser medida em 434x810; nenhuma janela foi redimensionada.")
            viewport = backend.viewport(hwnd)
            path = settings.data_dir / "calibration" / "geometry.json"
            _save(path, {"version": 1, "reference_size": list(size), "reference_viewport": list(viewport)})
            print(f"Geometria relativa salva: {path}; area do jogo {viewport}. Reinicie o bot para carregar.")
            return 0
        game = game_factory(settings)
        if op == "tour":
            from .slayer.calibration_tour import run_tour
            report = run_tour(game, session, inv, count=args.count, interval=args.interval,resume=args.resume)
            print(json.dumps(report,ensure_ascii=False,indent=2))
            return 1 if any(item["status"] != "captured" or item.get("recovery_error") for item in report) else 0
        entries = [args.entry] if op == "capture" else [
            ident for ident, entry in inv["entries"].items()
            if entry["kind"] != "click" and (not args.macro or ident in inv["macros"][args.macro]["entries"])]
        if op == "guide":
            print("Mostre cada tela manualmente. Enter captura, s pula, q encerra; o guia nao clica.")
        for ident in entries:
            if ident not in inv["entries"]:
                raise ValueError("Informe --entry com um ID valido de calibrate all catalog")
            if op == "guide":
                entry = inv["entries"][ident]
                answer = input(f"{entry['name']} ({entry['source']}{entry['pointer']}): ").strip().lower()
                if answer == "q":
                    break
                if answer == "s":
                    continue
            paths = []
            folder = session / "captures"
            folder.mkdir(parents=True, exist_ok=True)
            for i in range(args.count):
                if i:
                    time.sleep(args.interval)
                frame = game.screenshot()
                path = folder / f"{time.time_ns()}-{i}.png"
                path.write_bytes(frame.to_png())
                paths.append(path)
            engine.add(session, ident, args.label, paths, inv=inv)
        return 0
    if op == "add":
        if not args.entry or not args.images:
            raise ValueError("add requer --entry e --images")
        engine.add(session, args.entry, args.label, args.images, inv=inv)
        return 0
    if op == "propose":
        print(engine.propose(session, inv=inv))
        return 0
    if op == "validate":
        report = engine.validate(session, inv=inv)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if op == "apply":
        print(engine.apply(session, settings.data_dir, inv=inv))
        return 0
    if op == "rollback":
        print(engine.rollback(settings.data_dir))
        return 0
    raise ValueError(f"Operacao desconhecida: {op}")


def _save(path, value):
    from .slayer.calibration import _write
    _write(Path(path), value)
