"""Macro recorder: turns real mouse clicks on the game window into a macro.

The mouse is polled through the backend (no hooks, no dependencies). Every tap
becomes ``[wait] [wait_for_pixel] click`` steps in the same JSON format that
hand-written macros use, so recorded macros can be edited and shared like any other.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .backend import Backend
from .macro import Step

DEFAULT_STOP_VK = 0x79  # F10

# A foreground click itself takes about this long on replay, so it is taken off the recorded gaps.
CLICK_OVERHEAD = 0.4
TAP_RADIUS = 12          # px the cursor may travel during a press and still count as a tap
MAX_TAP_SECONDS = 0.6    # longer presses are holds, which macros cannot replay yet
MIN_WAIT = 0.3           # shorter gaps are not worth a wait step
ANCHOR_TOLERANCE = 30
ANCHOR_TIMEOUT = 30
ANCHOR_RADIUS = 2  # patch radius used both to record the color and to compare it on replay


class RecorderError(RuntimeError):
    """Recording cannot start (window missing, bad stop key, ...)."""


def vk_from_name(name: str) -> int:
    """Virtual-key code for a stop key name; only F1-F12 are accepted."""
    key = name.strip().upper()
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return 0x70 + int(key[1:]) - 1
    raise RecorderError(f"stop key must be F1-F12 (got {name!r})")


@dataclass
class Recording:
    steps: List[Step]
    clicks: int
    skipped_gestures: int
    duration: float
    window_size: Tuple[int, int]
    warnings: List[str] = field(default_factory=list)


@dataclass
class _Press:
    t: float
    x: int
    y: int
    width: int
    height: int
    color: Optional[Tuple[int, int, int]]
    travel: float = 0.0


def _percent(value: int, dimension: int) -> str:
    """Pixel -> "NN.NN%" of the window, using the pixel's center so replay lands on the same pixel."""
    return f"{round((value + 0.5) / dimension * 100, 2):g}%"


class Recorder:
    def __init__(
        self,
        backend: Backend,
        title: str,
        *,
        anchors: bool = True,
        stop_vk: int = DEFAULT_STOP_VK,
        poll_interval: float = 0.005,
        capture_interval: float = 0.15,
        max_seconds: float = 900.0,
        background_capture: bool = True,
        log: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._backend = backend
        self._title = title
        self._anchors = anchors
        self._stop_vk = stop_vk
        self._poll_interval = poll_interval
        self._capture_interval = capture_interval
        self._max_seconds = max_seconds
        self._background = background_capture
        self._log = log or (lambda message: None)
        self._clock = clock
        self._sleep = sleep
        self._stop = threading.Event()
        self._hwnd: Optional[int] = None
        self._frame = None

    def stop(self) -> None:
        """Ask a running ``record()`` to finish (safe from any thread)."""
        self._stop.set()

    # -- frames ----------------------------------------------------------------

    def _grab(self) -> None:
        try:
            frame = self._backend.capture(self._hwnd)
        except Exception:  # the window can vanish between polls; the main loop notices that
            return
        if frame is not None:
            self._frame = frame

    def _frame_loop(self, done: threading.Event) -> None:
        # Captures take tens of milliseconds, so they run beside the polling loop
        # instead of delaying it: a very quick tap must not fall between two polls.
        while not done.is_set():
            self._grab()
            done.wait(self._capture_interval)

    def _color_at(self, x: int, y: int) -> Optional[Tuple[int, int, int]]:
        if self._frame is None:
            self._grab()
        frame = self._frame
        return frame.average(x, y, ANCHOR_RADIUS) if frame is not None else None

    # -- recording -------------------------------------------------------------

    def record(self) -> Recording:
        hwnd = self._backend.find_window(self._title)
        if hwnd is None:
            raise RecorderError(f"window '{self._title}' not found (is the game open?)")
        self._hwnd = hwnd
        self._frame = None
        self._stop.clear()
        window_size = self._backend.client_size(hwnd)

        clicks: List[_Press] = []
        skipped = 0
        warnings: List[str] = []
        press: Optional[_Press] = None
        prev_down = True  # a button already held when recording starts is ignored until released
        done = threading.Event()
        worker = None
        if self._background:
            worker = threading.Thread(target=self._frame_loop, args=(done,), daemon=True)
            worker.start()
        start = end = self._clock()
        last_capture = float("-inf")
        try:
            while not self._stop.is_set():
                now = end = self._clock()
                if now - start > self._max_seconds:
                    warnings.append(f"stopped at the {self._max_seconds:g}s limit")
                    break
                if not self._backend.is_window(hwnd):
                    warnings.append("the game window closed; recording ended early")
                    break
                sample = self._backend.poll_input(hwnd, self._stop_vk)
                if sample.stop_pressed:
                    break
                if (not self._background and not sample.left_down and sample.inside
                        and now - last_capture >= self._capture_interval):
                    self._grab()
                    last_capture = now
                if sample.left_down and not prev_down and sample.inside:
                    width, height = self._backend.client_size(hwnd)
                    # The color comes from the latest frame, taken before this press changed the screen.
                    press = _Press(now, sample.x, sample.y, width, height, self._color_at(sample.x, sample.y))
                elif sample.left_down and press is not None:
                    press.travel = max(press.travel, math.hypot(sample.x - press.x, sample.y - press.y))
                elif not sample.left_down and press is not None:
                    if press.travel <= TAP_RADIUS and now - press.t <= MAX_TAP_SECONDS:
                        clicks.append(press)
                        self._log(f"click {len(clicks)}: ({_percent(press.x, press.width)}, {_percent(press.y, press.height)})")
                    else:
                        skipped += 1
                        self._log("drag/hold ignored (not supported yet)")
                    press = None
                prev_down = sample.left_down
                self._sleep(self._poll_interval)
        except KeyboardInterrupt:
            pass  # Ctrl+C in the terminal is a normal way to finish
        finally:
            done.set()
            if worker is not None:
                worker.join(timeout=2)
        return Recording(self._build_steps(clicks), len(clicks), skipped, end - start, window_size, warnings)

    def _build_steps(self, clicks: List[_Press]) -> List[Step]:
        steps: List[Step] = [{"action": "wait_window", "timeout": 30}]
        previous: Optional[float] = None
        for click in clicks:
            if previous is not None:
                gap = round(click.t - previous - CLICK_OVERHEAD, 1)
                if gap >= MIN_WAIT:
                    steps.append({"action": "wait", "seconds": gap})
            x, y = _percent(click.x, click.width), _percent(click.y, click.height)
            if self._anchors and click.color is not None:
                # Replay waits for the recorded delay and then for the target to actually be on
                # screen, so a slower load than during recording cannot misplace the click.
                steps.append({
                    "action": "wait_for_pixel", "x": x, "y": y, "color": list(click.color),
                    "radius": ANCHOR_RADIUS, "tolerance": ANCHOR_TOLERANCE, "poll_seconds": 0.5, "timeout": ANCHOR_TIMEOUT,
                })
            steps.append({"action": "click", "x": x, "y": y})
            previous = click.t
        return steps
