"""Test doubles shared by the test modules."""
from __future__ import annotations

from league_bot.backend import InputSample
from league_bot.imaging import solid_frame


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


class ScriptedMouse:
    """Plays scripted presses back as a function of a clock.

    ``presses`` holds ``(press_time, release_time, x, y)`` tuples, or
    ``(press_time, release_time, x, y, x_end, y_end)`` for a drag. ``stop_at``
    is the time from which the stop key reads as held.
    """

    def __init__(self, clock, presses, stop_at=None, size=(400, 800)) -> None:
        self.clock = clock
        self.presses = presses
        self.stop_at = stop_at
        self.size = size

    def __call__(self, hwnd, stop_vk) -> InputSample:
        now = self.clock()
        x = y = 0
        down = False
        for press in self.presses:
            pressed_at, released_at, px, py = press[:4]
            ex, ey = (press[4], press[5]) if len(press) == 6 else (px, py)
            if now >= pressed_at:
                progress = 1.0 if now >= released_at else (now - pressed_at) / (released_at - pressed_at)
                x, y = round(px + (ex - px) * progress), round(py + (ey - py) * progress)
            if pressed_at <= now < released_at:
                down = True
        inside = 0 <= x < self.size[0] and 0 <= y < self.size[1]
        stop = self.stop_at is not None and now >= self.stop_at
        return InputSample(x, y, inside, down, stop)


class FakeBackend:
    """In-memory window backend implementing league_bot.backend.Backend."""

    TITLE = "Slayer Legend"

    def __init__(self, size=(400, 800), fill=(10, 10, 10)) -> None:
        self.hwnd = 101
        self.alive = True
        self.size = size
        self.fill = fill          # color of every captured pixel...
        self.frames = None        # ...unless a list of colors is given (consumed in order, last repeats)
        self.minimized = False
        self.hide_for = 0         # find_window returns None this many times first
        self.input_fn = None      # callable(hwnd, stop_vk) -> InputSample, e.g. a ScriptedMouse
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

    def poll_input(self, hwnd, stop_vk):
        if self.input_fn is not None:
            return self.input_fn(hwnd, stop_vk)
        return InputSample(0, 0, False, False, False)
