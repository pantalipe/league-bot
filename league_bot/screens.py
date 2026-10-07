"""Offline screen-state matching from calibrated color anchors."""
from __future__ import annotations

import math
from numbers import Real
from typing import Any

from .imaging import Frame


class ScreenError(ValueError):
    """Raised when a screen-state definition is malformed or inconsistent."""


def _fail(message: str) -> None:
    raise ScreenError(message)


def _validate_screens(screens: list[dict[str, Any]]) -> set[str]:
    if not isinstance(screens, list):
        _fail("screens must be a list")
    names: set[str] = set()
    for index, screen in enumerate(screens):
        where = f"screens[{index}]"
        if not isinstance(screen, dict):
            _fail(f"{where} must be an object")
        name = screen.get("name")
        if not isinstance(name, str) or not name.strip():
            _fail(f"{where}.name must be a nonempty string")
        if name in names:
            _fail(f"duplicate screen name: {name}")
        names.add(name)

        anchors = screen.get("anchors")
        if not isinstance(anchors, list) or len(anchors) < 2:
            _fail(f"{where}.anchors must contain at least two anchors")
        for anchor_index, anchor in enumerate(anchors):
            ap = f"{where}.anchors[{anchor_index}]"
            if not isinstance(anchor, dict):
                _fail(f"{ap} must be an object")
            for axis in ("x", "y"):
                value = anchor.get(axis)
                if (isinstance(value, bool) or not isinstance(value, Real)
                        or not math.isfinite(value) or not 0 <= value <= 1):
                    _fail(f"{ap}.{axis} must be a finite normalized number from 0 to 1")
            color = anchor.get("color")
            if (not isinstance(color, (list, tuple)) or len(color) != 3
                    or any(isinstance(channel, bool) or not isinstance(channel, int)
                           or not 0 <= channel <= 255 for channel in color)):
                _fail(f"{ap}.color must contain three RGB integers from 0 to 255")
            tolerance = anchor.get("tolerance", 20)
            if (isinstance(tolerance, bool) or not isinstance(tolerance, int)
                    or not 0 <= tolerance <= 255):
                _fail(f"{ap}.tolerance must be an integer from 0 to 255")
            radius = anchor.get("radius", 0)
            if (isinstance(radius, bool) or not isinstance(radius, int)
                    or not 0 <= radius <= 20):
                _fail(f"{ap}.radius must be an integer from 0 to 20")

        click = screen.get("click")
        if "click" in screen and (not isinstance(click, dict) or "x" not in click or "y" not in click):
            _fail(f"{where}.click must be an object containing x and y")
        max_clicks = screen.get("max_clicks", 1)
        if isinstance(max_clicks, bool) or not isinstance(max_clicks, int) or max_clicks <= 0:
            _fail(f"{where}.max_clicks must be a positive integer")
    return names


def validate_screens(screens: list[dict], terminal: str) -> None:
    """Validate screen definitions and ensure terminal is a non-clickable state."""
    names = _validate_screens(screens)
    if not isinstance(terminal, str) or terminal not in names:
        _fail("terminal must name one of the configured screens")
    terminal_screen = next(screen for screen in screens if screen["name"] == terminal)
    if "click" in terminal_screen:
        _fail("terminal screen must not define a click")


def matching_screens(frame: Frame | None, screens: list[dict]) -> list[str]:
    """Return every screen whose anchors all match the frame's sampled colors.

    Returning all matches lets callers stop safely when calibration makes a frame
    ambiguous. A missing or unusable frame has no matches.
    """
    _validate_screens(screens)
    if frame is None or not isinstance(frame, Frame):
        return []
    matches: list[str] = []
    for screen in screens:
        matched = True
        for anchor in screen["anchors"]:
            x = round(anchor["x"] * (frame.width - 1))
            y = round(anchor["y"] * (frame.height - 1))
            sample = frame.average(x, y, anchor.get("radius", 0))
            if sample is None or any(
                abs(actual - expected) > anchor.get("tolerance", 20)
                for actual, expected in zip(sample, anchor["color"])
            ):
                matched = False
                break
        if matched:
            matches.append(screen["name"])
    return matches
