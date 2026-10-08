"""Game controller: start / stop / status / screenshot / macros for Slayer Legend."""
from __future__ import annotations

import csv
import io
import os
import subprocess
import threading
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, List, Optional, Sequence, Tuple

from .backend import Backend, GuardedBackend
from .config import Settings
from .imaging import Frame
from .library import LibraryError, MacroLibrary
from .macro import MacroRunner, Step
from .recorder import DEFAULT_STOP_VK, Recorder

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
    recording: bool = False


@dataclass(frozen=True)
class RecordingResult:
    """Outcome of a background recording; ``error`` is set when nothing was saved."""

    name: str
    path: Optional[Path]
    clicks: int
    skipped_gestures: int
    duration: float
    warnings: Tuple[str, ...] = ()
    error: str = ""
    shots_path: Optional[Path] = None
    image_count: int = 0


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
        recorder_factory: Callable = Recorder,
        input_guard: Optional[Callable[[], ContextManager[Any]]] = None,
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
        self._library = MacroLibrary(settings.macros_dir)
        self._recorder_factory = recorder_factory
        self._input_guard = input_guard  # context manager entered around real mouse input
        self._recorder: Optional[Recorder] = None

    # -- helpers ---------------------------------------------------------------

    @property
    def library(self) -> MacroLibrary:
        return self._library

    def _title(self) -> str:
        title = self._settings.window_title.strip()
        if not title:
            raise GameError("SLAYER_WINDOW_TITLE nao esta configurado. Rode `python -m league_bot windows` para ver os titulos.")
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
        backend = GuardedBackend(self._backend, self._input_guard) if self._input_guard else self._backend
        runner = self._runner_factory(backend, title, self._settings.foreground_input, self._log)
        if isinstance(runner, MacroRunner):
            runner.diagnostics_dir = self._settings.data_dir / "diagnostics"
        with self._runner_guard:
            self._runner = runner
        try:
            runner.run(steps, name)
        finally:
            with self._runner_guard:
                self._runner = None

    def list_macros(self) -> List[str]:
        return self._library.names()

    def load_macro_steps(self, name: str) -> List[Step]:
        try:
            return self._library.load_steps(name)
        except LibraryError as exc:
            raise GameError(str(exc)) from None

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
        return GameStatus(
            running=self.is_running(), window_found=window, busy=self._busy.locked(),
            recording=self._recorder is not None,
        )

    # -- actions ---------------------------------------------------------------

    def start(self) -> str:
        title = self._title()
        steps = self.load_macro_steps(self._settings.start_macro)  # validate before launching anything
        with self._exclusive():
            if self.is_running() and self._backend.find_window(title) is not None:
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

    def start_recording(
        self,
        name: str,
        *,
        anchors: bool = False,
        shots: bool = False,
        stop_vk: int = DEFAULT_STOP_VK,
        description: str = "",
        tags: Sequence[str] = (),
        overwrite: bool = False,
        max_seconds: float = 900.0,
        on_done: Optional[Callable[[RecordingResult], None]] = None,
    ) -> None:
        """Record the user's clicks in the background into a local macro.

        Returns right away. Recording ends on the stop key, ``stop_recording()`` or the time
        limit, and ``on_done`` then receives the result. The game is busy meanwhile.
        """
        title = self._title()
        try:
            self._library.check_name(name)
            if self._library.find(name) is not None and not overwrite:
                raise LibraryError(f"Ja existe uma macro chamada '{name}'. Escolha outro nome ou use force.")
        except LibraryError as exc:
            raise GameError(str(exc)) from None
        if self._backend.find_window(title) is None:
            raise GameError("Janela do jogo nao encontrada (o jogo esta rodando?).")
        if not self._busy.acquire(blocking=False):
            raise GameBusy("Ja existe uma operacao em andamento (use /cancel para abortar).")
        try:
            options = {"shots_dir": self._library.new_recording_dir(name)} if shots else {}
            recorder = self._recorder_factory(
                self._backend, title, anchors=anchors, stop_vk=stop_vk, max_seconds=max_seconds, log=self._log,
                **options,
            )
            with self._runner_guard:
                self._recorder = recorder
            threading.Thread(
                target=self._record_worker, name="league-recorder", daemon=True,
                args=(recorder, name, description, tuple(tags), overwrite, on_done),
            ).start()
        except BaseException:
            with self._runner_guard:
                self._recorder = None
            self._busy.release()
            raise

    def _record_worker(self, recorder, name, description, tags, overwrite, on_done) -> None:
        guard = self._input_guard or nullcontext
        try:
            try:
                with guard():  # e.g. lifts a keyboard/mouse lock so the user can actually click
                    recording = recorder.record()
                if recording.clicks == 0:
                    result = RecordingResult(
                        name, None, 0, recording.skipped_gestures, recording.duration,
                        tuple(recording.warnings), "Nenhum clique gravado; nada foi salvo.",
                    )
                else:
                    path = self._library.save(
                        name, recording.steps, description=description, tags=tags,
                        window=recording.window_size, overwrite=overwrite,
                    )
                    result = RecordingResult(
                        name, path, recording.clicks, recording.skipped_gestures,
                        recording.duration, tuple(recording.warnings),
                        shots_path=recording.shots_path, image_count=recording.image_count,
                    )
            except Exception as exc:  # a thread has nobody to raise to: report instead
                self._log(f"recording failed: {exc}")
                result = RecordingResult(name, None, 0, 0, 0.0, (), str(exc))
        finally:
            with self._runner_guard:
                self._recorder = None
            self._busy.release()
        if on_done is not None:
            try:
                on_done(result)
            except Exception as exc:
                self._log(f"recording callback failed: {exc}")

    def stop_recording(self) -> bool:
        """Ask the running recording to finish (and be saved). Returns whether there was one."""
        with self._runner_guard:
            recorder = self._recorder
        if recorder is None:
            return False
        recorder.stop()
        return True

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
        # grab and minimize again using the backend's nonactivating window operations.
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
