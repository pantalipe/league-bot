"""The daily: a list of macros that all run every time, each time in a fresh random order.

Running everything in the same fixed order every day would look mechanical, so the
order is shuffled on every run (and is never the same as the previous run's, whenever
another order exists). The daily is started on demand; nothing here schedules it.
"""
from __future__ import annotations

import json
import os
import random
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .game import GameError, SlayerGame
from .imaging import Frame
from .library import LibraryError, MacroLibrary
from .macro import MacroCancelled, MacroError


class DailyError(RuntimeError):
    """The daily is empty, refers to a missing macro, or its file is unusable."""


class DailyBusy(DailyError):
    """A daily is already running."""


def shuffled_order(macros: Sequence[str], last: Sequence[str], rng: random.Random) -> List[str]:
    """A random permutation of ``macros`` that differs from ``last`` whenever another order exists."""
    order = list(macros)
    if len(order) < 2:
        return order
    for _ in range(20):
        rng.shuffle(order)
        if order != list(last):
            return order
    return order[1:] + order[:1]  # a rotation of distinct items always differs from the original


class DailyList:
    """The macros that make up the daily, plus the order used last time (one JSON file)."""

    def __init__(self, path: Path, library: MacroLibrary) -> None:
        self._path = Path(path)
        self._library = library
        self._lock = threading.Lock()

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise DailyError(f"{self._path.name}: arquivo invalido ({exc})") from None
        if not isinstance(data, dict):
            raise DailyError(f"{self._path.name}: arquivo invalido")
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, self._path)  # atomic: a crash never leaves a half-written file

    @staticmethod
    def _names(data: Dict[str, Any], key: str) -> List[str]:
        raw = data.get(key, [])
        return [str(item) for item in raw] if isinstance(raw, list) else []

    def macros(self) -> List[str]:
        return self._names(self._read(), "macros")

    def last_order(self) -> List[str]:
        return self._names(self._read(), "last_order")

    def last_run(self) -> str:
        return str(self._read().get("last_run", ""))

    def missing(self) -> List[str]:
        """Macros in the list that no longer exist (deleted or renamed since they were added)."""
        gone = []
        for name in self.macros():
            try:
                exists = self._library.find(name) is not None
            except LibraryError:
                exists = False
            if not exists:
                gone.append(name)
        return gone

    def add(self, name: str) -> None:
        try:
            exists = self._library.find(name) is not None
        except LibraryError as exc:
            raise DailyError(str(exc)) from None
        if not exists:
            available = ", ".join(self._library.names()) or "(nenhuma)"
            raise DailyError(f"Macro '{name}' nao existe. Disponiveis: {available}")
        with self._lock:
            data = self._read()
            macros = self._names(data, "macros")
            if name in macros:
                raise DailyError(f"'{name}' ja esta na daily.")
            data["macros"] = macros + [name]
            self._write(data)

    def remove(self, name: str) -> None:
        with self._lock:
            data = self._read()
            macros = self._names(data, "macros")
            if name not in macros:
                raise DailyError(f"'{name}' nao esta na daily.")
            data["macros"] = [m for m in macros if m != name]
            self._write(data)

    def record_run(self, order: Sequence[str], when: datetime) -> None:
        with self._lock:
            data = self._read()
            data["last_order"] = list(order)
            data["last_run"] = when.isoformat(timespec="seconds")
            self._write(data)


@dataclass(frozen=True)
class DailyResult:
    order: Tuple[str, ...]
    done: Tuple[str, ...]
    status: str  # "ok", "failed" or "cancelled"
    error: str = ""
    frame: Optional[Frame] = None


class DailyRunner:
    """Runs every macro of the daily, one after another, in a random order."""

    def __init__(
        self,
        game: SlayerGame,
        entries: DailyList,
        *,
        rng: Optional[random.Random] = None,
        now: Callable[[], datetime] = datetime.now,
        ensure_running: bool = True,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._game = game
        self._entries = entries
        self._rng = rng or random.Random()
        self._now = now
        self._ensure_running = ensure_running
        self._log = log or (lambda message: None)
        self._lock = threading.Lock()
        self._cancelled = threading.Event()

    # -- list management (thin delegates, so front ends need only the runner) --

    def macros(self) -> List[str]:
        return self._entries.macros()

    def missing(self) -> List[str]:
        return self._entries.missing()

    def add(self, name: str) -> None:
        self._entries.add(name)

    def remove(self, name: str) -> None:
        self._entries.remove(name)

    # -- running ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def cancel(self) -> bool:
        """Stop the daily after (or during) the current macro. Returns whether one was running."""
        if not self._lock.locked():
            return False
        self._cancelled.set()
        self._game.cancel()  # also aborts the macro in progress, if any
        return True

    def run(self, on_start: Optional[Callable[[Tuple[str, ...]], None]] = None) -> DailyResult:
        """Run the whole daily. ``on_start`` receives today's order before anything is executed."""
        macros = self._entries.macros()
        if not macros:
            raise DailyError("A daily esta vazia. Adicione macros com: daily add <macro>")
        missing = self._entries.missing()
        if missing:
            raise DailyError("A daily tem macros que nao existem mais: " + ", ".join(missing))
        if not self._lock.acquire(blocking=False):
            raise DailyBusy("A daily ja esta rodando (use /cancel para abortar).")
        self._cancelled.clear()
        try:
            return self._execute(macros, on_start)
        finally:
            self._lock.release()

    def _execute(self, macros: List[str], on_start) -> DailyResult:
        order = tuple(shuffled_order(macros, self._entries.last_order(), self._rng))
        # Remembered even if this run fails halfway: the next run is shuffled differently regardless.
        self._entries.record_run(order, self._now())
        self._log("daily order: " + " -> ".join(order))
        if on_start is not None:
            on_start(order)

        done: List[str] = []
        status, error = "ok", ""
        try:
            if self._ensure_running:
                self._game.start()  # does nothing when the game is already running
            for name in order:
                if self._cancelled.is_set():
                    raise MacroCancelled("daily cancelled")
                self._game.run_macro(name)
                done.append(name)
        except MacroCancelled:
            status, error = "cancelled", "Daily cancelada."
        except (GameError, MacroError, LibraryError) as exc:
            status, error = "failed", str(exc)

        frame: Optional[Frame] = None
        try:
            frame = self._game.screenshot()
        except (GameError, OSError):
            frame = None  # a missing screenshot must not turn a finished daily into an error
        return DailyResult(order, tuple(done), status, error, frame)


def open_list(settings, library: MacroLibrary) -> DailyList:
    return DailyList(Path(settings.data_dir) / "daily.json", library)


def build_runner(game: SlayerGame, settings, *, rng: Optional[random.Random] = None,
                 log: Optional[Callable[[str], None]] = None) -> DailyRunner:
    return DailyRunner(game, open_list(settings, game.library), rng=rng, log=log)
