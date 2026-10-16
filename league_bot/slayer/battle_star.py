"""Detect the Battle settings star and wait for it to return after a battle."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from league_bot.imaging import Frame
from league_bot.macro import MacroCancelled, MacroError


_ASSET = Path(__file__).parent / "assets" / "battle-star.json"
_DATA = json.loads(_ASSET.read_text(encoding="utf-8"))
_REFERENCE_WIDTH, _REFERENCE_HEIGHT = _DATA["reference_size"]
_ORIGIN_X, _ORIGIN_Y = _DATA["origin"]
_TEMPLATES = tuple(tuple(tuple(row) for row in template) for template in _DATA["templates"])


def _luma(rgb) -> int:
    return (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) // 1000


def _usable(frame: Frame) -> bool:
    """Reject a black PrintWindow frame; it cannot prove the star disappeared."""
    step_x = max(1, frame.width // 24)
    step_y = max(1, frame.height // 24)
    for y in range(max(step_y // 2, frame.height // 20), frame.height - frame.height // 40, step_y):
        for x in range(max(step_x // 2, frame.width // 40), frame.width - frame.width // 40, step_x):
            pixel = frame.pixel(x, y)
            if pixel is not None and max(pixel) > 8:
                return True
    return False


def _score_template(frame: Frame, template, center_x: float, center_y: float,
                    scale_x: float, scale_y: float) -> float:
    height, width = len(template), len(template[0])
    scaled_w = max(1, round(width * scale_x))
    scaled_h = max(1, round(height * scale_y))
    left = round(center_x - (scaled_w - 1) / 2)
    top = round(center_y - (scaled_h - 1) / 2)
    threshold = _DATA["threshold"]
    intersection = union = expected_count = observed_count = 0
    for y in range(scaled_h):
        source_y = min(height - 1, int(y / scale_y))
        for x in range(scaled_w):
            source_x = min(width - 1, int(x / scale_x))
            expected = template[source_y][source_x] == "#"
            pixel = frame.pixel(left + x, top + y)
            if pixel is None:
                return 0.0
            observed = _luma(pixel) >= threshold
            expected_count += bool(expected)
            observed_count += bool(observed)
            intersection += bool(expected and observed)
            union += bool(expected or observed)
    if not expected_count or not observed_count or not union:
        return 0.0
    iou = intersection / union
    recall = intersection / expected_count
    precision = intersection / observed_count
    if (iou < _DATA["minimum_iou"] or recall < _DATA["minimum_recall"]
            or precision < _DATA["minimum_precision"]):
        return 0.0
    return iou


def battle_star_present(frame: Optional[Frame]) -> bool:
    """Return true only when the star-shaped Battle settings icon is visible."""
    if frame is None or not _usable(frame):
        return False
    sx = frame.width / _REFERENCE_WIDTH
    sy = frame.height / _REFERENCE_HEIGHT
    base_x = (_ORIGIN_X + (len(_TEMPLATES[0][0]) - 1) / 2) * sx
    base_y = (_ORIGIN_Y + (len(_TEMPLATES[0]) - 1) / 2) * sy
    shifts = (-3, -2, -1, 0, 1, 2, 3)
    for template in _TEMPLATES:
        for factor in (0.9, 1.0, 1.1):
            for dy in shifts:
                for dx in shifts:
                    if _score_template(frame, template, base_x + dx * sx,
                                       base_y + dy * sy, sx * factor, sy * factor):
                        return True
    return False


class StarBattleWaiter:
    """Wait for the Battle settings star to disappear, then return stably."""

    def __init__(self, backend, title: str, pause: Callable[[float], None],
                 clock: Callable[[], float] = time.monotonic,
                 diagnostics_dir: Optional[Path] = None):
        self.backend = backend
        self.title = title
        self.pause = pause
        self.clock = clock
        self.diagnostics_dir = Path(diagnostics_dir) if diagnostics_dir is not None else None
        self.last_frame: Optional[Frame] = None

    def _capture(self) -> Optional[Frame]:
        try:
            hwnd = self.backend.find_window(self.title)
            if hwnd is None:
                return None
            frame = self.backend.capture(hwnd)
        except MacroCancelled:
            raise
        except (OSError, ValueError, MacroError):
            return None
        if frame is not None and _usable(frame):
            self.last_frame = frame
            return frame
        return None

    def _fail(self, message: str) -> MacroError:
        path = None
        if self.last_frame is not None and self.diagnostics_dir is not None:
            try:
                self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
                path = self.diagnostics_dir / f"battle-star-{uuid4().hex}.png"
                path.write_bytes(self.last_frame.to_png())
            except OSError:
                path = None
        if path is not None:
            message += f" (screenshot saved to {path})"
        return MacroError(message)

    def wait(self, entry_timeout: float = 30, battle_timeout: float = 600) -> None:
        """Wait for two absent frames, then three returned frames a second apart."""
        self.last_frame = None
        entry_deadline = self.clock() + entry_timeout
        battle_deadline = None
        absent = returned = 0
        while True:
            now = self.clock()
            if battle_deadline is None and now >= entry_deadline:
                raise self._fail("Battle did not start: Battle settings star never disappeared")
            if battle_deadline is not None and now >= battle_deadline:
                raise self._fail("Battle did not finish: Battle settings star did not return")

            frame = self._capture()
            if frame is None:
                absent = returned = 0
            else:
                visible = battle_star_present(frame)
                if battle_deadline is None:
                    if visible:
                        absent = 0
                    else:
                        absent += 1
                        if absent >= 2:
                            battle_deadline = now + battle_timeout
                            returned = 0
                elif visible:
                    returned += 1
                    if returned >= 3:
                        return
                else:
                    returned = 0

            deadline = entry_deadline if battle_deadline is None else battle_deadline
            self.pause(min(1.0, max(0.0, deadline - self.clock())))
