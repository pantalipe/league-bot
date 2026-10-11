"""Home-bot daily runner with attendance and a tracked Slayer macro plan."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

from league_bot.daily import DailyBusy, DailyError, DailyList, DailyResult, DailyRunner
from league_bot.game import GameError
from league_bot.library import LibraryError
from league_bot.macro import MacroCancelled, MacroError
from .status import BR_TZ, DailyStatusError
from .plan import (
    ACTIVATIONS, BLOCKED_MACROS, DEFAULT_MACROS, FINISHED_DAILIES,
    MACRO_CATALOG, REPEATED_MACROS, missing_daily_dependencies, ordered_macros,
)

ATTENDANCE_MACRO = "attendance_check"


@dataclass(frozen=True)
class HomeDailyResult(DailyResult):
    """Daily result with the attendance outcome, when verification completed."""

    attendance: Optional[str] = None


class _CycleChanged(Exception):
    pass


class HomeDailyRunner(DailyRunner):
    """Run attendance first and then the selected macros in dependency order."""

    def __init__(self, game, entries: DailyList, *, status_store=None, **kwargs) -> None:
        super().__init__(game, entries, **kwargs)
        self._status_store = status_store

    def macros(self) -> List[str]:
        return [ATTENDANCE_MACRO, *self._entries.macros()]

    def missing(self) -> List[str]:
        return self._entries.missing()

    def add(self, name: str) -> None:
        if name == ATTENDANCE_MACRO:
            raise DailyError("A verificacao de presenca e obrigatoria e nao pode ser adicionada manualmente.")
        self._entries.add(name)

    def remove(self, name: str) -> None:
        if name == ATTENDANCE_MACRO:
            raise DailyError("A verificacao de presenca e obrigatoria e nao pode ser removida.")
        self._entries.remove(name)

    def run(self, on_start: Optional[Callable[[Tuple[str, ...]], None]] = None,
            on_event: Optional[Callable[[str], None]] = None) -> HomeDailyResult:
        macros = self._entries.macros()
        missing = self._entries.missing()
        if missing:
            raise DailyError("A daily tem macros que nao existem mais: " + ", ".join(missing))
        blocked = sorted(set(macros) & BLOCKED_MACROS)
        if blocked:
            raise DailyError("Macro bloqueada até confirmar o custo em diamantes: " + ", ".join(blocked))
        repeated_without_store = sorted(set(macros) & set(REPEATED_MACROS)) if self._status_store is None else []
        if repeated_without_store:
            raise DailyError("O acompanhamento diário é necessário para as coletas repetidas: " +
                             ", ".join(repeated_without_store))
        dependencies = missing_daily_dependencies(macros)
        if dependencies:
            details = "; ".join(
                f"{name} precisa de {', '.join(required)}"
                for name, required in dependencies.items()
            )
            raise DailyError("A daily selecionada está incompleta: " + details)
        if not self._lock.acquire(blocking=False):
            raise DailyBusy("A daily ja esta rodando (use /runcancel para abortar).")
        self._cancelled.clear()
        try:
            return self._execute_home(macros, on_start, on_event)
        finally:
            self._lock.release()

    def _execute_home(self, macros: List[str], on_start, on_event) -> HomeDailyResult:
        plan = ordered_macros(macros, self._rng)
        try:
            cycle = self._status_store.cycle_id() if self._status_store else None
            snapshot = self._status_store.snapshot() if self._status_store else None
        except DailyStatusError as exc:
            return HomeDailyResult((ATTENDANCE_MACRO,), (), "failed", str(exc), None, None)
        order = (ATTENDANCE_MACRO, *plan)
        self._entries.record_run(order, self._now())
        self._log("daily order: " + " -> ".join(order))
        if on_start is not None:
            on_start(order)

        done: List[str] = []
        status, error = "ok", ""
        attendance = None
        current_task = "attendance"
        try:
            if self._ensure_running:
                self._game.start()
            self._check_cancelled(cycle)
            attendance = self._game.check_attendance()
            if self._status_store:
                self._status_store.mark_progress("attendance", 1, source="visual", expected_cycle=cycle)
            done.append(ATTENDANCE_MACRO)

            # Run one eligible pickup early, then let other work occupy its cooldown.
            remaining = {}
            for name, (target, _interval) in REPEATED_MACROS.items():
                if name not in plan:
                    continue
                task = (snapshot or {}).get("tasks", {}).get("macro:" + name, {})
                remaining[name] = max(0, target - task.get("progress", 0))

            deferred = [name for name in plan if name == FINISHED_DAILIES]
            for name in (name for name in plan if name != FINISHED_DAILIES):
                if self._cancelled.is_set():
                    raise MacroCancelled("daily cancelled")
                if name in REPEATED_MACROS:
                    if remaining[name]:
                        if self._eligible(name, snapshot, cycle):
                            current_task = "macro:" + name
                            self._run_tracked(name, cycle, done, on_event)
                            remaining[name] -= 1
                            snapshot = self._refresh_snapshot(cycle)
                    continue
                current_task = "macro:" + name
                if self._is_complete(name, snapshot):
                    continue
                self._check_cancelled(cycle)
                self._run_tracked(name, cycle, done, on_event)
                snapshot = self._refresh_snapshot(cycle)

            while any(remaining.values()):
                self._check_cancelled(cycle)
                due = [self._eligible_at(name, snapshot) for name, count in remaining.items() if count]
                next_at = min(due)
                now = self._clock_now()
                seconds = max(0.0, (next_at - now).total_seconds())
                if seconds:
                    self._notify(on_event, f"Aguardando o intervalo das coletas (até {int(seconds)} s).")
                    if self._cancelled.wait(seconds):
                        raise MacroCancelled("daily cancelled")
                self._check_cancelled(cycle)
                due_names = [name for name, count in remaining.items()
                             if count and self._eligible_at(name, snapshot) <= self._clock_now()]
                for name in due_names:
                    current_task = "macro:" + name
                    self._run_tracked(name, cycle, done, on_event)
                    remaining[name] -= 1
                    snapshot = self._refresh_snapshot(cycle)
            for name in deferred:
                current_task = "macro:" + name
                if self._is_complete(name, snapshot):
                    continue
                self._check_cancelled(cycle)
                self._run_tracked(name, cycle, done, on_event)
                snapshot = self._refresh_snapshot(cycle)
        except MacroCancelled:
            status, error = "cancelled", "Daily cancelada."
        except _CycleChanged:
            status, error = "cancelled", "O ciclo diário mudou durante a execução; a daily foi interrompida."
        except (GameError, MacroError, LibraryError, DailyStatusError) as exc:
            status, error = "failed", str(exc)
            if self._status_store:
                try:
                    self._status_store.mark_error(current_task, error, expected_cycle=cycle)
                except DailyStatusError:
                    error = "Nao foi possivel salvar o acompanhamento diario."

        frame = None
        try:
            frame = self._game.screenshot()
        except (GameError, OSError):
            frame = None
        return HomeDailyResult(order, tuple(done), status, error, frame, attendance)

    def _run_tracked(self, name, cycle, done, on_event):
        self._check_cancelled(cycle)
        if name in ACTIVATIONS:
            message = "Ativando os bônus diários: " + ("scrolls" if name == "ativar_scrolls" else "montaria") + "."
            self._notify(on_event, message)
        result = self._game.run_macro(name)
        self._check_cancelled(cycle)
        if getattr(result, "skipped", False):
            self._notify(on_event, str(result))
            if self._status_store:
                self._status_store.mark_error("macro:" + name, str(result), expected_cycle=cycle)
            return
        if self._status_store:
            task_id = "macro:" + name
            task = self._status_store.snapshot().get("tasks", {}).get(task_id, {})
            progress = task.get("progress", 0)
            target = REPEATED_MACROS.get(name, (1, 0))[0]
            self._status_store.mark_progress(
                task_id, min(target, progress + 1), target=target, label=name,
                source="macro", expected_cycle=cycle,
            )
        done.append(name)

    def _refresh_snapshot(self, cycle):
        if not self._status_store:
            return None
        self._check_cancelled(cycle)
        return self._status_store.snapshot()

    def _check_cancelled(self, cycle):
        if self._cancelled.is_set():
            raise MacroCancelled("daily cancelled")
        if self._status_store and self._status_store.cycle_id() != cycle:
            raise _CycleChanged()

    @staticmethod
    def _is_complete(name, snapshot):
        if snapshot is None:
            return False
        task = snapshot.get("tasks", {}).get("macro:" + name, {})
        return task.get("status") == "completed"

    def _eligible(self, name, snapshot, cycle):
        return self._eligible_at(name, snapshot) <= self._clock_now()

    @staticmethod
    def _eligible_at(name, snapshot):
        task = (snapshot or {}).get("tasks", {}).get("macro:" + name, {})
        timestamp = task.get("last_completed_at") or task.get("updated_at")
        if not timestamp:
            return datetime.min.replace(tzinfo=BR_TZ)
        try:
            return datetime.fromisoformat(timestamp).astimezone(BR_TZ) + timedelta(seconds=REPEATED_MACROS[name][1])
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=BR_TZ)

    def _clock_now(self):
        value = self._now()
        if value.tzinfo is None:
            return value.replace(tzinfo=BR_TZ)
        return value.astimezone(BR_TZ)

    def _notify(self, callback, message):
        if callback is None:
            return
        try:
            callback(message)
        except Exception as exc:  # Telegram notification failure must not stop game actions.
            self._log("daily notification failed: " + str(exc))
