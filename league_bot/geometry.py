"""Reference-frame geometry for game backends.

The adapter keeps existing runners in their calibrated client coordinate space,
while translating clicks and captured pixels to the live game viewport.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Optional, Tuple

from .imaging import Frame

Rect = Tuple[int, int, int, int]
Size = Tuple[int, int]


class GeometryError(OSError, ValueError):
    """An observed geometry cannot safely use the calibrated coordinate space."""


def _size(value: Size, name: str) -> Size:
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or any(type(v) is not int or v <= 0 for v in value)):
        raise ValueError(f"{name} must contain two positive integers")
    return int(value[0]), int(value[1])


def _rect(value: Optional[Rect], size: Size, name: str) -> Rect:
    if value is None:
        return 0, 0, size[0], size[1]
    if (not isinstance(value, (tuple, list)) or len(value) != 4
            or any(type(v) is not int for v in value)):
        raise ValueError(f"{name} must be [left, top, width, height] integers")
    left, top, width, height = map(int, value)
    if left < 0 or top < 0 or width <= 0 or height <= 0 or left + width > size[0] or top + height > size[1]:
        raise ValueError(f"{name} must be a positive rectangle within its client size")
    return left, top, width, height


def map_point(
    x: int, y: int, reference_size: Size, target_size: Size,
    reference_viewport: Optional[Rect] = None, target_viewport: Optional[Rect] = None,
) -> Tuple[int, int]:
    """Map a reference-client point into a live-client point with bounds checks."""
    rw, rh = _size(reference_size, "reference_size")
    tw, th = _size(target_size, "target_size")
    rv = _rect(reference_viewport, (rw, rh), "reference_viewport")
    tv = _rect(target_viewport, (tw, th), "target_viewport")
    if type(x) is not int or type(y) is not int or not (rv[0] <= x < rv[0] + rv[2] and rv[1] <= y < rv[1] + rv[3]):
        raise ValueError(f"reference point ({x}, {y}) is outside the calibrated game viewport")
    # Pixel-center scaling keeps the first/last pixels within the destination rect.
    dx = tv[0] + min(tv[2] - 1, ((x - rv[0]) * tv[2]) // rv[2])
    dy = tv[1] + min(tv[3] - 1, ((y - rv[1]) * tv[3]) // rv[3])
    return dx, dy


def normalize_frame(
    frame: Frame, reference_size: Size, reference_viewport: Optional[Rect] = None,
    target_viewport: Optional[Rect] = None,
) -> Frame:
    """Crop the live game viewport and nearest-neighbor resample into reference space."""
    rw, rh = _size(reference_size, "reference_size")
    rv = _rect(reference_viewport, (rw, rh), "reference_viewport")
    if target_viewport is None:
        if rv != (0, 0, rw, rh) or not _aspect_compatible((rw, rh), (frame.width, frame.height)):
            raise ValueError("live viewport is unknown; provide a calibrated live viewport")
    tv = _rect(target_viewport, (frame.width, frame.height), "target_viewport")
    _require_compatible_aspect(rv[2:], tv[2:])
    if (frame.width, frame.height) == (rw, rh) and rv == tv:
        return frame
    out_row = ((rw * 3 + 3) // 4) * 4
    out = bytearray(out_row * rh)  # black outside the reference game viewport
    source_x = [tv[0] + min(tv[2] - 1, x * tv[2] // rv[2]) for x in range(rv[2])]
    for y in range(rv[3]):
        sy = tv[1] + min(tv[3] - 1, y * tv[3] // rv[3])
        dst_y = rh - 1 - (rv[1] + y)
        src_row = (frame.height - 1 - sy) * frame.row_size
        dst_row = dst_y * out_row + rv[0] * 3
        for x in range(rv[2]):
            src = src_row + source_x[x] * 3
            dst = dst_row + x * 3
            out[dst:dst + 3] = frame.bgr[src:src + 3]
    return Frame(rw, rh, bytes(out))


def _aspect_compatible(reference: Size, target: Size) -> bool:
    reference_ratio = reference[0] / reference[1]
    target_ratio = target[0] / target[1]
    return abs(target_ratio / reference_ratio - 1.0) < 0.01


def _require_compatible_aspect(reference: Size, target: Size) -> None:
    if not _aspect_compatible(reference, target):
        raise ValueError("live game viewport aspect ratio differs from calibration by 1% or more")


def clip_viewport(origin: Tuple[int, int], surface_size: Size, client_size: Size,
                  max_overflow: int = 8) -> Rect:
    """Clip a slightly oversized child surface to its visible root-client intersection."""
    root_w, root_h = _size(client_size, "client_size")
    surface_w, surface_h = _size(surface_size, "surface_size")
    if (not isinstance(origin, (tuple, list)) or len(origin) != 2
            or any(type(v) is not int for v in origin)):
        raise ValueError("origin must contain two integers")
    left, top = origin
    if left < 0 or top < 0:
        raise ValueError("emulator surface origin is outside the game client area")
    overflow_x = left + surface_w - root_w
    overflow_y = top + surface_h - root_h
    if overflow_x > max_overflow or overflow_y > max_overflow:
        raise ValueError("emulator surface extends too far outside the game client area")
    width = min(surface_w, root_w - left)
    height = min(surface_h, root_h - top)
    if width <= 0 or height <= 0:
        raise ValueError("emulator surface does not intersect the game client area")
    return left, top, width, height


class ReferenceBackend:
    """Present a backend in calibrated coordinates while preserving physical size."""

    def __init__(self, backend, reference_size: Size = (434, 810),
                 reference_viewport: Optional[Rect] = None,
                 target_viewport: Optional[Rect] = None, preserve_size: bool = True):
        self.backend = backend
        self.reference_size = _size(reference_size, "reference_size")
        if reference_viewport is None:
            raise ValueError("reference_viewport must be explicitly calibrated")
        self.reference_viewport = _rect(reference_viewport, self.reference_size, "reference_viewport")
        self.target_viewport = target_viewport
        self.preserve_size = preserve_size

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def client_size(self, hwnd):
        return self.reference_size

    def _live_viewport(self, hwnd, target_size):
        viewport = self.target_viewport
        if viewport is None:
            getter = getattr(self.backend, "viewport", None)
            if callable(getter):
                viewport = getter(hwnd)
        if viewport is None:
            raise ValueError("live viewport is unknown; backend must provide viewport(hwnd) or a calibrated target_viewport")
        tv = _rect(viewport, target_size, "target_viewport")
        _require_compatible_aspect(self.reference_viewport[2:], tv[2:])
        return tv

    def capture(self, hwnd):
        frame = self.backend.capture(hwnd)
        if frame is None:
            return None
        target_size = (frame.width, frame.height)
        try:
            viewport = self._live_viewport(hwnd, target_size)
            return normalize_frame(frame, self.reference_size, self.reference_viewport, viewport)
        except ValueError as exc:
            raise GeometryError(str(exc)) from exc

    def click(self, hwnd, x, y, foreground):
        target_size = self.backend.client_size(hwnd)
        try:
            viewport = self._live_viewport(hwnd, target_size)
            mapped = map_point(x, y, self.reference_size, target_size, self.reference_viewport, viewport)
        except ValueError as exc:
            raise GeometryError(str(exc)) from exc
        self.backend.click(hwnd, *mapped, foreground)

    def drag(self, hwnd, x1, y1, x2, y2):
        target_size=self.backend.client_size(hwnd)
        try:
            viewport=self._live_viewport(hwnd,target_size)
            start=map_point(x1,y1,self.reference_size,target_size,self.reference_viewport,viewport)
            end=map_point(x2,y2,self.reference_size,target_size,self.reference_viewport,viewport)
        except ValueError as exc:
            raise GeometryError(str(exc)) from exc
        self.backend.drag(hwnd,*start,*end)

    def poll_input(self, hwnd, stop_vk):
        sample = self.backend.poll_input(hwnd, stop_vk)
        size = self.backend.client_size(hwnd)
        try:
            viewport = self._live_viewport(hwnd, size)
            if not (sample.inside and viewport[0] <= sample.x < viewport[0] + viewport[2]
                    and viewport[1] <= sample.y < viewport[1] + viewport[3]):
                return replace(sample, x=-1, y=-1, inside=False)
            x, y = map_point(sample.x, sample.y, size, self.reference_size,
                             viewport, self.reference_viewport)
            return replace(sample, x=x, y=y)
        except ValueError as exc:
            raise GeometryError(str(exc)) from exc

    def move_resize(self, hwnd, x, y, width, height):
        if not self.preserve_size:
            return self.backend.move_resize(hwnd, x, y, width, height)
        if x is None and y is None:
            return None
        move = getattr(self.backend, "move_position", None)
        if not callable(move):
            raise OSError("backend cannot move the game window without changing its physical size")
        move(hwnd, x, y)


def load_geometry_profile(data_dir) -> Optional[dict]:
    """Load and validate the optional v1 calibration/geometry.json profile."""
    path = Path(data_dir) / "calibration" / "geometry.json"
    if not path.exists():
        return None
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read geometry profile {path}: {exc}") from exc
    if not isinstance(profile, dict) or profile.get("version") != 1:
        raise ValueError("geometry profile must be an object with version 1")
    if "reference_size" not in profile or "reference_viewport" not in profile:
        raise ValueError("geometry profile requires reference_size and reference_viewport")
    reference_size = _size(profile["reference_size"], "reference_size")
    reference_viewport = _rect(profile["reference_viewport"], reference_size, "reference_viewport")
    preserve_size = profile.get("preserve_size", True)
    if type(preserve_size) is not bool:
        raise ValueError("geometry profile preserve_size must be a boolean")
    return {"reference_size": reference_size, "reference_viewport": reference_viewport,
            "preserve_size": preserve_size}


def wrap_backend(backend, data_dir):
    """Opt in to reference geometry when a validated profile exists."""
    profile = load_geometry_profile(data_dir)
    if profile is None:
        return backend
    return ReferenceBackend(backend, **profile)
