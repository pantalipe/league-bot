"""Command helpers for guided screenshot-based screen calibration."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

from .config import Settings


def _engine():
    # Keep Pillow and calibration implementation imports out of normal CLI startup.
    from .slayer import calibration

    return calibration


def _session(args, settings: Settings) -> Path:
    return args.session if args.session is not None else settings.data_dir / "calibration" / "session"


def _check_capture_options(count: int, interval: float) -> None:
    if not 2 <= count <= 60:
        raise ValueError("--count deve estar entre 2 e 60")
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("--interval deve ser um numero finito >= 0")


def _capture(game, state: str, session: Path, count: int, interval: float) -> list[Path]:
    _check_capture_options(count, interval)
    frames = []
    for index in range(count):
        if index:
            time.sleep(interval)
        frames.append(game.screenshot())
    paths = _engine().capture_sample(session, state, frames)
    for path in paths:
        print(path)
    return paths


def _diagnose(args) -> int:
    calibration = _engine()
    frame = calibration.load_image(args.image)
    screen = calibration.catalog()[args.state]
    report = calibration.diagnose(frame, screen)
    size = "x".join(str(value) for value in report["size"])
    expected_size = "x".join(str(value) for value in report["expected_size"])
    print(f"{args.state}: {'MATCH' if report['matched'] else 'SEM MATCH'} ({size}; esperado {expected_size})")
    size_matches = report["size"] == report["expected_size"]
    if not size_matches:
        print(f"ERRO: tamanho {size} nao suportado; a calibracao exige {expected_size}.", file=sys.stderr)
    for item in report["anchors"]:
        xy = f"({item['x']}, {item['y']})"
        expected = _rgb(item.get("expected"))
        actual = _rgb(item.get("actual"))
        delta = _rgb(item.get("delta"))
        status = "OK" if item.get("matched") else "FALHA"
        print(f"  anchor {item['index']}: {status} pos={xy} esperado={expected} atual={actual} delta={delta}")
    return 0 if report["matched"] and size_matches else 1


def _rgb(value) -> str:
    return "indisponivel" if value is None else "[" + ", ".join(str(channel) for channel in value) + "]"


def _validate(session: Path) -> dict:
    result = _engine().validate_candidate(session)
    print(f"Amostras: {result['samples']}")
    if result["ok"]:
        print("Validacao aprovada.")
    else:
        print("Validacao reprovada:", file=sys.stderr)
        for error in result["errors"]:
            print(f"  - {error}", file=sys.stderr)
    return result


def run_calibration(args, settings: Settings, game_factory=None) -> int:
    """Run one calibration command; offline operations never construct a game/backend."""
    session = _session(args, settings) if hasattr(args, "session") else None
    command = args.calibration_command
    if command == "diagnose":
        return _diagnose(args)
    if command == "capture":
        _check_capture_options(args.count, args.interval)
        if game_factory is None:
            raise RuntimeError("captura requer um provedor de jogo")
        _capture(game_factory(settings), args.state, session, args.count, args.interval)
        return 0
    if command == "add":
        paths = _engine().add_sample(session, args.state, args.images)
        for path in paths:
            print(path)
        return 0
    if command == "propose":
        if not 0 <= args.search_radius <= 30:
            raise ValueError("--search-radius deve estar entre 0 e 30")
        report_path = session / "report.html"
        try:
            path = _engine().build_candidate(session, search_radius=args.search_radius)
        except ValueError:
            if report_path.exists():
                print(f"Relatorio para revisao: {report_path}")
            raise
        print(f"Candidato salvo em {path}; nenhum perfil ativo foi alterado.")
        if report_path.exists():
            print(f"Relatorio anotado para revisao: {report_path}")
        return 0
    if command == "validate":
        return 0 if _validate(session)["ok"] else 1
    if command == "apply":
        if not _validate(session)["ok"]:
            return 1
        path = _engine().apply_candidate(session, settings.data_dir)
        print(f"Perfil local ativado em {path}.")
        return 0
    if command == "rollback":
        path = _engine().rollback(args.data_dir or settings.data_dir)
        print(f"Perfil local restaurado: {path}")
        return 0
    if command == "guide":
        _check_capture_options(args.count, args.interval)
        if game_factory is None:
            raise RuntimeError("guia requer um provedor de jogo")
        game = game_factory(settings)
        print("Mude a tela do jogo manualmente. Este guia somente captura; nao navega nem clica.")
        for state, description in CALIBRATION_GUIDE_STATES:
            answer = input(f"Mostre {description} Enter captura, s pula, q encerra: ").strip().lower()
            if answer == "q":
                print("Guia encerrado.")
                break
            if answer == "s":
                continue
            frames = []
            for index in range(args.count):
                if index:
                    time.sleep(args.interval)
                frames.append(game.screenshot())
            for path in _engine().capture_sample(session, state, frames):
                print(path)
        return 0
    raise ValueError(f"Comando de calibracao desconhecido: {command}")


# CLI help uses this stable set; derived labels such as ``main_entry`` are matcher
# outputs and are not separately captured as training states.
CALIBRATION_STATES = (
    "main", "menu_open", "settings_open", "attendance_claim_ready",
    "attendance_claimed", "attendance_claimed_settings", "unknown",
)
CALIBRATION_GUIDE_STATES = (
    ("main", "o menu principal fechado."),
    ("menu_open", "o menu aberto, com a engrenagem visivel."),
    ("settings_open", "Settings aberto na aba Attendance Reward."),
    ("attendance_claim_ready", "a presenca aberta, com Claim disponivel."),
    ("attendance_claimed", "a presenca depois da coleta, com Claim desabilitado."),
    ("attendance_claimed_settings", "a presenca aberta por Settings depois de ja coletada."),
    ("unknown", "opcionalmente, uma tela que nao corresponda a nenhuma classe acima, como evidencia negativa."),
)
