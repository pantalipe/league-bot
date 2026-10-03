"""Game controller: start / stop / status / screenshot / macros for Slayer Legend."""
from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from .backend import Backend
from .config import Settings
from .imaging import Frame
from .macro import MacroRunner, Step, load_macro

_MACRO_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GameError(RuntimeError):
    """Something the user can fix (bad config, game not running, ...)."""


class GameBusy(GameError):
    """Another start/macro/capture is already using the mouse and window."""


@dataclass(frozen=True)
class GameStatus:
    running: bool
    window_found: bool
    busy: bool


def _default_launcher(settings: Settings) -> None:
    if settings.launch_uri:
        # A googleplaygames:// URI opens the exact game instead of the generic library screen.
        os.startfile(settings.launch_uri)  # type: ignore[attr-defined]  # Windows only
    elif settings.play_games_exe:
        subprocess.Popen([settings.play_games_exe], cwd=str(Path(settings.play_games_exe).parent))
    else:
        raise GameError("Configure SLAYER_LAUNCH_URI ou SLAYER_PLAY_GAMES_EXE.")


def _default_runner(backend: Backend, title: str, foreground: bool, log: Callable[[str], None]) -> MacroRunner:
    return MacroRunner(backend, title, foreground, log)


class SlayerGame:
    def __init__(
        self,
        settings: Settings,
        backend: Backend,
        *,
        run_cmd: Callable = subprocess.run,
        launcher: Optional[Callable[[Settings], None]] = None,
        runner_factory: Callable = _default_runner,
        sleep: Callable[[float], None] = time.sleep,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._run_cmd = run_cmd
        self._launcher = launcher or _default_launcher
        self._runner_factory = runner_factory
        self._sleep = sleep
        self._log = log or (lambda message: None)
        self._busy = threading.Lock()
        self._runner: Optional[MacroRunner] = None
        self._runner_guard = threading.Lock()

    # -- helpers ---------------------------------------------------------------

    def _title(self) -> str:
        title = self._settings.window_title.strip()
        if not title:
            raise GameError("SLAYER_WINDOW_TITLE nao esta configurado. Rode `python -m slayerbot windows` para ver os titulos.")
        return title

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        if not self._busy.acquire(blocking=False):
            raise GameBusy("Ja existe uma operacao em andamento (use /cancel para abortar).")
        try:
            yield
        finally:
            self._busy.release()

    def _run_steps(self, steps: List[Step], name: str, title: str) -> None:
        runner = self._runner_factory(self._backend, title, self._settings.foreground_input, self._log)
        with self._runner_guard:
            self._runner = runner
        try:
            runner.run(steps, name)
        finally:
            with self._runner_guard:
                self._runner = None

    def _macro_dirs(self) -> List[Path]:
        # macros/local/ (gitignored) overrides the shared macros, for per-machine calibration.
        return [self._settings.macros_dir / "local", self._settings.macros_dir]

    def list_macros(self) -> List[str]:
        names = set()
        for directory in self._macro_dirs():
            if directory.is_dir():
                names.update(p.stem for p in directory.glob("*.json") if _MACRO_NAME.match(p.stem))
        return sorted(names)

    def load_macro_steps(self, name: str) -> List[Step]:
        if not _MACRO_NAME.match(name):
            raise GameError("Nome de macro invalido (use letras, numeros, '_' e '-').")
        for directory in self._macro_dirs():
            path = directory / f"{name}.json"
            if path.is_file():
                return load_macro(path)
        available = ", ".join(self.list_macros()) or "(nenhuma)"
        raise GameError(f"Macro '{name}' nao existe. Disponiveis: {available}")

    # -- queries ---------------------------------------------------------------

    def is_running(self) -> bool:
        wanted = {name.lower() for name in self._settings.process_names}
        if not wanted:
            return False
        result = self._run_cmd(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW,
        )
        for row in csv.reader(io.StringIO(result.stdout or "")):
            if row and row[0].strip().lower() in wanted:
                return True
        return False

    def status(self) -> GameStatus:
        title = self._settings.window_title.strip()
        window = bool(title) and self._backend.find_window(title) is not None
        return GameStatus(running=self.is_running(), window_found=window, busy=self._busy.locked())

    # -- actions ---------------------------------------------------------------

    def start(self) -> str:
        title = self._title()
        steps = self.load_macro_steps(self._settings.start_macro)  # validate before launching anything
        with self._exclusive():
            if self.is_running():
                return "Slayer Legend ja esta rodando; nada a fazer."
            self._log("launching Slayer Legend")
            self._launcher(self._settings)
            self._run_steps(steps, self._settings.start_macro, title)
        return "Slayer Legend iniciado e macro de inicio concluida."

    def run_macro(self, name: str) -> str:
        title = self._title()
        steps = self.load_macro_steps(name)
        with self._exclusive():
            self._run_steps(steps, name, title)
        return f"Macro '{name}' concluida."

    def cancel(self) -> bool:
        """Abort the macro in progress, if any. Returns whether there was one."""
        with self._runner_guard:
            runner = self._runner
        if runner is None:
            return False
        runner.cancel()
        return True

    def stop(self) -> str:
        self.cancel()
        killed, missing = [], []
        for name in self._settings.process_names:
            result = self._run_cmd(
                ["taskkill", "/IM", name, "/F", "/T"],
                capture_output=True, text=True, errors="replace", creationflags=_NO_WINDOW,
            )
            (killed if result.returncode == 0 else missing).append(name)
        if killed:
            return f"Slayer Legend finalizado ({', '.join(killed)})."
        return "Nenhum processo do jogo estava rodando."

    def screenshot(self) -> Frame:
        hwnd = self._backend.find_window(self._title())
        if hwnd is None:
            raise GameError("Janela do jogo nao encontrada (o jogo esta rodando?).")
        if not self._backend.is_minimized(hwnd):
            return self._grab(hwnd)
        # Minimized windows stop rendering, so there is nothing to capture: restore,
        # grab and minimize again (steals focus for about a second).
        if not self._busy.acquire(blocking=False):
            raise GameBusy("Janela minimizada e uma operacao esta em andamento; tente de novo em instantes.")
        try:
            self._log("window minimized: restoring briefly to capture")
            self._backend.restore(hwnd)
            self._sleep(0.8)
            try:
                return self._grab(hwnd)
            finally:
                self._backend.minimize(hwnd)
        finally:
            self._busy.release()

    def _grab(self, hwnd: int) -> Frame:
        frame = self._backend.capture(hwnd)
        if frame is None:
            raise GameError("Falha ao capturar a janela (ela pode estar sem conteudo renderizado).")
        return frame
