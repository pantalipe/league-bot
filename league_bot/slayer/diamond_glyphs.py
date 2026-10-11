"""Exact, fail-closed matcher for the Slayer diamond counter's pixel glyphs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from typing import Any

from league_bot.macro import MacroError

_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "diamond-glyphs.json"
_CROP_SIZE = (48, 21)
_THRESHOLD = 170
_ROW_START = 7  # absolute screen y=56 in crop y=49
_ROW_END = 13   # absolute screen y=62, exclusive
_COMMA_ROW = 15 # absolute screen y=64


@dataclass(frozen=True)
class _Glyph:
    digit: str
    rows: tuple[str, ...]

    @property
    def width(self) -> int:
        return len(self.rows[0])


@lru_cache(maxsize=4)
def _load_templates(path: Path = _TEMPLATE_PATH) -> dict[str, tuple[_Glyph, ...]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != 1 or raw.get("threshold_min_rgb") != _THRESHOLD:
            raise ValueError("unsupported template set")
        templates = raw["templates"]
        result = {}
        for digit in "0123456789":
            glyphs = []
            for rows in templates[digit]:
                rows = tuple(rows)
                if (len(rows) != _ROW_END - _ROW_START or not rows
                        or len({len(row) for row in rows}) != 1
                        or any(set(row) - {"0", "1"} for row in rows)
                        or not any("1" in row for row in rows)):
                    raise ValueError(f"invalid {digit} mask")
                glyphs.append(_Glyph(digit, rows))
            if not glyphs:
                raise ValueError(f"missing digit {digit}")
            result[digit] = tuple(glyphs)
        return result
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise MacroError("calibração dos dígitos de diamantes inválida") from exc


def _binary_rows(image: Any) -> tuple[tuple[bool, ...], ...]:
    if image.size != _CROP_SIZE:
        raise MacroError("recorte do cabeçalho de diamantes com tamanho inesperado")
    rgb = image.convert("RGB")
    return tuple(
        tuple(min(rgb.getpixel((x, y))) >= _THRESHOLD for x in range(rgb.width))
        for y in range(_ROW_START, _ROW_END)
    )


def _candidates(rows: tuple[tuple[bool, ...], ...],
                templates: dict[str, tuple[_Glyph, ...]]) -> list[tuple[int, int, str, _Glyph]]:
    width = len(rows[0])
    candidates = []
    for digit, glyphs in templates.items():
        for glyph in glyphs:
            for start in range(width - glyph.width + 1):
                if all(
                    all(rows[y][start + x] == (glyph.rows[y][x] == "1")
                        for x in range(glyph.width))
                    for y in range(len(rows))
                ):
                    candidates.append((start, start + glyph.width, digit, glyph))
    return sorted(set(candidates), key=lambda match: (match[0], match[1], match[2]))


def _has_valid_comma(image: Any, matches: tuple[tuple[int, int, str, _Glyph], ...]) -> bool:
    digits = len(matches)
    rgb = image.convert("RGB")
    comma_x = [x for x in range(image.width)
               if min(rgb.getpixel((x, _COMMA_ROW))) >= _THRESHOLD]
    if digits <= 3:
        return not comma_x
    # Thousands separators must appear exactly after the leading group.
    separator_index = digits - 4
    left = matches[separator_index][1]
    right = matches[separator_index + 1][0]
    return bool(comma_x) and all(left <= x < right for x in comma_x)


def _fully_covers(rows: tuple[tuple[bool, ...], ...],
                  matches: tuple[tuple[int, int, str, _Glyph], ...]) -> bool:
    expected = [[False] * len(rows[0]) for _ in rows]
    for start, _, _, glyph in matches:
        for y, row in enumerate(glyph.rows):
            for x, pixel in enumerate(row):
                if pixel == "1":
                    expected[y][start + x] = True
    return all(expected[y][x] == rows[y][x]
               for y in range(len(rows)) for x in range(len(rows[0])))


def read_header_digits(header_crop: Any, *, template_path: Path = _TEMPLATE_PATH) -> int:
    """Read a 48x21 header-only crop or raise MacroError on any uncertainty.

    The crop corresponds to screen coordinates x=252..299, y=49..69. It contains
    only the balance text; the caller remains responsible for checking the cyan
    diamond icon and full frame dimensions before calling this function.
    """
    image = header_crop.convert("RGB")
    rows = _binary_rows(image)
    templates = _load_templates(template_path)
    candidates = _candidates(rows, templates)
    readings: set[str] = set()
    occupied = tuple(x for x in range(image.width) if any(row[x] for row in rows))

    def visit(path: tuple[tuple[int, int, str, _Glyph], ...]) -> None:
        if len(readings) > 1:
            return
        if len(path) >= 1:
            text = "".join(item[2] for item in path)
            if (len(text) <= 6 and _fully_covers(rows, path)
                    and _has_valid_comma(image, path)):
                readings.add(text)
        if len(path) == 6:
            return
        last_end = path[-1][1] if path else 0
        next_ink = next((x for x in occupied if x >= last_end), None)
        if next_ink is None:
            return
        for candidate in candidates:
            start = candidate[0]
            # Each extension must cover the next foreground column. Skipping
            # it can never produce a complete reading and causes huge searches.
            if start < last_end or start > next_ink or candidate[1] <= next_ink:
                continue
            if path and start - last_end > 6:
                continue
            visit(path + (candidate,))

    visit(())

    if len(readings) != 1:
        raise MacroError("saldo de diamantes ilegível ou ambíguo")
    text = next(iter(readings))
    return int(text)


def load_glyph_templates() -> dict[str, tuple[_Glyph, ...]]:
    """Return the validated built-in template set for calibration checks."""
    return _load_templates()
