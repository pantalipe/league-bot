"""Macro engine: validates and runs JSON step lists against a window backend."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .backend import Backend

Step = Dict[str, Any]


class MacroError(RuntimeError):
    """A macro is invalid or a step could not complete."""


class MacroCancelled(MacroError):
    """The macro was cancelled while running."""


# action -> keys that must be present (everything else has a sensible default)
REQUIRED_KEYS: Dict[str, Tuple[str, ...]] = {
    "wait_window": (),
    "wait": (),
    "click": ("x", "y"),
    "wait_for_pixel": ("x", "y", "color"),
    "click_if_pixel": ("x", "y", "color"),
    "move_resize": ("width", "height"),
    "minimize": (),
}


def resolve_coord(value: Any, dimension: int) -> int:
    """Resolve a macro coordinate: ``"center"``, ``"NN%"`` of the dimension, or absolute pixels.

    Percentages keep clicks on target when the game scales its UI with the window size.
    """
    if value == "center":
        return dimension // 2
    if isinstance(value, str):
        if value.endswith("%"):
            try:
                return int(dimension * float(value[:-1]) / 100)
            except ValueError:
                pass
        raise MacroError(f"invalid coordinate {value!r} (use 'center', 'NN%' or a pixel number)")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MacroError(f"invalid coordinate {value!r} (use 'center', 'NN%' or a pixel number)")
    return int(value)


def validate_steps(steps: Any) -> None:
    """Fail early, before touching the game, if the macro has a typo."""
    if not isinstance(steps, list) or not steps:
        raise MacroError("a macro must be a non-empty list of steps")
    for number, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise MacroError(f"step {number}: must be an object")
        action = step.get("action")
        if action not in REQUIRED_KEYS:
            raise MacroError(f"step {number}: unknown action {action!r} (known: {', '.join(sorted(REQUIRED_KEYS))})")
        missing = [key for key in REQUIRED_KEYS[action] if key not in step]
        if missing:
            raise MacroError(f"step {number} ({action}): missing {', '.join(missing)}")
        for axis in ("x", "y"):
            if axis in step and action != "move_resize":
                try:
                    resolve_coord(step[axis], 100)
                except MacroError as exc:
                    raise MacroError(f"step {number} ({action}): {exc}") from None
        if "color" in step:
            color = step["color"]
            if not (isinstance(color, list) and len(color) == 3 and all(isinstance(c, int) and 0 <= c <= 255 for c in color)):
                raise MacroError(f"step {number} ({action}): color must be [R, G, B] with values 0-255")
        if "radius" in step:
            radius = step["radius"]
            if isinstance(radius, bool) or not isinstance(radius, int) or not 0 <= radius <= 20:
                raise MacroError(f"step {number} ({action}): radius must be an integer from 0 to 20")


def load_macro(path: Path) -> List[Step]:
    """Load a macro file: either a list of steps or ``{"steps": [...], ...metadata}``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise MacroError(f"{Path(path).name}: invalid JSON ({exc})") from None
    steps = data.get("steps") if isinstance(data, dict) else data
    validate_steps(steps)
    return steps


def _describe_seen(seen) -> str:
    if seen is None:
        return "the window could not be captured (is it minimized?)"
    return f"last seen {list(seen)}"


class MacroRunner:
    """Executes validated steps. One runner per run; ``cancel()`` is safe from any thread."""

    def __init__(
        self,
        backend: Backend,
        title: str,
        foreground: bool = True,
        log: Optional[Callable[[str], None]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._title = title
        self._foreground = foreground
        self._log = log or (lambda message: None)
        self._sleep = sleep
        self._clock = clock
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def _check_cancel(self) -> None:
        if self._cancelled.is_set():
            raise MacroCancelled("macro cancelled")

    def _pause(self, seconds: float) -> None:
        self._check_cancel()
        if self._sleep is not None:
            self._sleep(seconds)
        else:
            self._cancelled.wait(seconds)  # wakes immediately on cancel()
        self._check_cancel()

    def run(self, steps: List[Step], name: str = "macro") -> None:
        validate_steps(steps)
        hwnd: Optional[int] = None
        for number, step in enumerate(steps, 1):
            self._check_cancel()
            handler = getattr(self, "_do_" + step["action"])
            hwnd = handler(step, hwnd)
        self._log(f"macro '{name}' finished ({len(steps)} steps)")

    # -- helpers ---------------------------------------------------------------

    def _window(self, hwnd: Optional[int], purpose: str) -> int:
        """A live handle for the game window, re-resolved by title if the old one died."""
        if hwnd is not None and self._backend.is_window(hwnd):
            return hwnd
        found = self._backend.find_window(self._title)
        if found is None:
            raise MacroError(f"window '{self._title}' not found (needed to {purpose})")
        return found

    def _poll_pixel(self, step: Step, hwnd: Optional[int], timeout: float):
        """Capture in a loop until the pixel matches. Returns (matched, hwnd, x_px, y_px, last_seen).

        Tolerates the window briefly disappearing: login/splash and main windows
        of some apps do not share a handle, so the handle is re-resolved by title.
        """
        target = [int(c) for c in step["color"]]
        tolerance = step.get("tolerance", 20)
        radius = int(step.get("radius", 0))  # 0 = the exact pixel; N = mean of the (2N+1)^2 patch around it
        poll = float(step.get("poll_seconds", 1))
        deadline = self._clock() + timeout
        x_px = y_px = 0
        seen = None
        while True:
            if hwnd is None or not self._backend.is_window(hwnd):
                hwnd = self._backend.find_window(self._title)
            if hwnd is not None:
                width, height = self._backend.client_size(hwnd)
                x_px = resolve_coord(step["x"], width)
                y_px = resolve_coord(step["y"], height)
                frame = self._backend.capture(hwnd)
                pixel = None
                if frame is not None:
                    pixel = frame.average(x_px, y_px, radius) if radius else frame.pixel(x_px, y_px)
                if pixel is not None:
                    seen = pixel
                if pixel is not None and all(abs(pixel[i] - target[i]) <= tolerance for i in range(3)):
                    return True, hwnd, x_px, y_px, seen
            if self._clock() >= deadline:
                return False, hwnd, x_px, y_px, seen
            self._pause(poll)

    # -- actions ---------------------------------------------------------------

    def _do_wait_window(self, step: Step, hwnd: Optional[int]) -> int:
        timeout = float(step.get("timeout", 30))
        self._log(f"waiting for window '{self._title}' (up to {timeout:g}s)")
        deadline = self._clock() + timeout
        while True:
            found = self._backend.find_window(self._title)
            if found is not None:
                return found
            if self._clock() >= deadline:
                raise MacroError(f"window '{self._title}' did not appear within {timeout:g}s")
            self._pause(1.0)

    def _do_wait(self, step: Step, hwnd: Optional[int]) -> Optional[int]:
        self._pause(float(step.get("seconds", 1)))
        return hwnd

    def _do_click(self, step: Step, hwnd: Optional[int]) -> int:
        hwnd = self._window(hwnd, "click")
        width, height = self._backend.client_size(hwnd)
        self._backend.click(hwnd, resolve_coord(step["x"], width), resolve_coord(step["y"], height), self._foreground)
        return hwnd

    def _do_wait_for_pixel(self, step: Step, hwnd: Optional[int]) -> Optional[int]:
        timeout = float(step.get("timeout", 20))
        self._log(f"waiting for pixel {step['color']} at ({step['x']}, {step['y']}) (up to {timeout:g}s)")
        matched, hwnd, x_px, y_px, seen = self._poll_pixel(step, hwnd, timeout)
        if not matched:
            raise MacroError(f"expected pixel {step['color']} did not appear within {timeout:g}s ({_describe_seen(seen)})")
        self._log(f"pixel found at ({x_px}, {y_px})")
        return hwnd

    def _do_click_if_pixel(self, step: Step, hwnd: Optional[int]) -> Optional[int]:
        timeout = float(step.get("timeout", 20))
        self._log(f"looking for pixel {step['color']} at ({step['x']}, {step['y']}) (up to {timeout:g}s)")
        matched, hwnd, x_px, y_px, seen = self._poll_pixel(step, hwnd, timeout)
        if matched and hwnd is not None:
            self._log(f"pixel found at ({x_px}, {y_px}) -- clicking")
            self._backend.click(hwnd, x_px, y_px, self._foreground)
        else:
            self._log(f"pixel not found within {timeout:g}s ({_describe_seen(seen)}) -- continuing without clicking")
        return hwnd

    def _do_move_resize(self, step: Step, hwnd: Optional[int]) -> int:
        hwnd = self._window(hwnd, "move/resize")
        x = int(step["x"]) if "x" in step else None
        y = int(step["y"]) if "y" in step else None
        self._backend.move_resize(hwnd, x, y, int(step["width"]), int(step["height"]))
        return hwnd

    def _do_minimize(self, step: Step, hwnd: Optional[int]) -> int:
        hwnd = self._window(hwnd, "minimize")
        self._backend.minimize(hwnd)
        return hwnd
