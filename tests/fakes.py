"""Test doubles shared by the test modules."""
from __future__ import annotations

from slayerbot.imaging import solid_frame


class FakeTime:
    """Deterministic clock/sleep pair: sleeping just advances the clock."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeBackend:
    """In-memory window backend implementing slayerbot.backend.Backend."""

    TITLE = "Slayer Legend"

    def __init__(self, size=(400, 800), fill=(10, 10, 10)) -> None:
        self.hwnd = 101
        self.alive = True
        self.size = size
        self.fill = fill          # color of every captured pixel...
        self.frames = None        # ...unless a list of colors is given (consumed in order, last repeats)
        self.minimized = False
        self.hide_for = 0         # find_window returns None this many times first
        self._find_calls = 0
        self.calls = []
        self.click_log = []

    def clicks(self):
        return [(x, y, fg) for (_, x, y, fg) in self.click_log]

    def list_windows(self):
        return [self.TITLE, "Notepad"]

    def find_window(self, title):
        self._find_calls += 1
        if self._find_calls <= self.hide_for or not title.strip():
            return None
        return self.hwnd if title.lower() in self.TITLE.lower() else None

    def is_window(self, hwnd):
        return self.alive and hwnd == self.hwnd

    def client_size(self, hwnd):
        return self.size

    def capture(self, hwnd):
        self.calls.append(("capture",))
        if self.frames:
            color = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
        else:
            color = self.fill
        return solid_frame(self.size[0], self.size[1], color)

    def click(self, hwnd, x, y, foreground):
        self.calls.append(("click", x, y, foreground))
        self.click_log.append((hwnd, x, y, foreground))

    def minimize(self, hwnd):
        self.calls.append(("minimize",))
        self.minimized = True

    def restore(self, hwnd):
        self.calls.append(("restore",))
        self.minimized = False

    def is_minimized(self, hwnd):
        return self.minimized

    def move_resize(self, hwnd, x, y, width, height):
        self.calls.append(("move_resize", x, y, width, height))
