"""User-facing messages (pt-BR) shared by every chat front end built on league_bot."""
from __future__ import annotations

from typing import Sequence

from .game import RecordingResult
from .library import MacroInfo


def recording_started(name: str, anchors: bool = False) -> str:
    text = (
        f"🔴 Gravando '{name}'. Va para o jogo e clique normalmente. "
        "Para terminar: F10 ou /recstop (limite de 15 min)."
    )
    if anchors:
        text += "\nGravando tambem a cor de cada clique."
    return text


def recording_result(result: RecordingResult, run_command: str = "/macro") -> str:
    if result.error:
        return f"❌ {result.error}"
    lines = [f"✅ Macro '{result.name}' salva: {result.clicks} clique(s) em {result.duration:.0f}s."]
    if result.skipped_gestures:
        lines.append(f"⚠️ {result.skipped_gestures} gesto(s) de arrastar/segurar foram ignorados (ainda nao suportados).")
    lines.extend(f"⚠️ {warning}" for warning in result.warnings)
    lines.append(f"Para rodar: {run_command} {result.name}")
    return "\n".join(lines)


def macro_list(infos: Sequence[MacroInfo]) -> str:
    if not infos:
        return "Nenhuma macro."
    lines = ["Macros:"]
    for info in infos:
        text = f"• {info.name} ({info.source}, {info.steps} passo(s))"
        if info.error:
            text += f" - ERRO: {info.error}"
        elif info.description:
            text += f" - {info.description}"
        if info.tags:
            text += f" [{', '.join(info.tags)}]"
        lines.append(text)
    return "\n".join(lines)
