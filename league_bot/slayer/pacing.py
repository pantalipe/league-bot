"""Optional click-only pacing for Slayer's visual runner."""
from __future__ import annotations

import math
from numbers import Real
from typing import Callable, Tuple


def normalize_delay_range(value) -> Tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("click_delay_range must contain two finite nonnegative numbers")
    low, high = value
    if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) or v < 0
           for v in (low, high)):
        raise ValueError("click_delay_range must contain two finite nonnegative numbers")
    if low > high:
        raise ValueError("click_delay_range lower bound must not exceed its upper bound")
    return float(low), float(high)


class ClickPacedBackend:
    """Forward backend operations, pausing cancelably before each actual click."""

    def __init__(self, backend, *, rng, pause: Callable[[float], None], delay_range):
        self._backend = backend
        self._rng = rng
        self._pause = pause
        self._delay_range = normalize_delay_range(delay_range)

    def click(self, hwnd, x, y, foreground):
        low, high = self._delay_range
        delay = self._rng.uniform(low, high) if high else 0.0
        if delay > 0:
            self._pause(delay)
        self._backend.click(hwnd, x, y, foreground)

    def __getattr__(self, name):
        return getattr(self._backend, name)
