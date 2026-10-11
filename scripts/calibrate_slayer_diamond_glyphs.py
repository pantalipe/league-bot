"""Build strict Slayer diamond glyph masks from manually labelled recordings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "league_bot" / "slayer" / "assets" / "diamond-glyphs.json"
GLYPH_Y = (56, 62)  # six stable rows; the comma is checked separately at y=64.

# Each half-open x range is labelled by visual inspection of its recorded count.
# The first two maps were supplied by the project owner; the remaining bounds
# follow the same visible white-pixel masks in the named, labelled headers.
EXAMPLES = (
    ("pet_guild", "0001_before.png", "16027", {
        "1": (256, 258), "6": (259, 264), "0": (269, 273),
        "2": (273, 279), "7": (282, 285),
    }),
    ("pet_guild", "0016_after.png", "15027", {
        "1": (256, 258), "5": (259, 264), "0": (269, 273),
        "2": (273, 279), "7": (282, 285),
    }),
    ("ativar_scrolls", "0001_before.png", "9647", {
        "9": (256, 260), "6": (265, 270), "4": (271, 276), "7": (279, 283),
    }),
    ("cobinar_equip", "0002_before.png", "2827", {
        "2": (256, 260), "8": (265, 270), "2b": (271, 276), "7b": (278, 282),
    }),
    ("free_item_shop", "0007_before.png", "1317", {
        "1b": (256, 258), "3": (263, 268), "1c": (269, 271), "7c": (274, 277),
    }),
    ("free_item_shop", "0011_before.png", "1517", {
        "1d": (256, 258), "5": (262, 267), "1e": (269, 271), "7d": (274, 277),
    }),
    ("free_item_shop", "0006_before.png", "1267", {
        "1f": (256, 258), "2c": (262, 268), "6b": (269, 273), "7e": (276, 279),
    }),
    ("free_item_shop", "0010_before.png", "1467", {
        "1g": (256, 258), "4b": (262, 269), "6c": (270, 274), "7f": (277, 280),
    }),
    ("free_item_shop", "0017_before.png", "1667", {
        "1h": (256, 258), "6d": (262, 268), "6e": (269, 273), "7g": (276, 279),
    }),
)


def _find_recording(recordings: Path, folder: str, filename: str) -> Path:
    matches = list((recordings / folder).rglob(filename))
    if len(matches) != 1:
        raise ValueError(f"expected one {folder}/{filename}, found {len(matches)}")
    return matches[0]


def _mask(image: Image.Image, left: int, right: int) -> list[str]:
    rgb = image.convert("RGB")
    rows = []
    for y in range(*GLYPH_Y):
        rows.append("".join("1" if min(rgb.getpixel((x, y))) >= 170 else "0"
                            for x in range(left, right)))
    return rows


def calibrate(recordings: Path) -> dict:
    templates: dict[str, list[list[str]]] = {str(digit): [] for digit in range(10)}
    for folder, filename, label, bounds in EXAMPLES:
        image = Image.open(_find_recording(recordings, folder, filename))
        for label_digit, (left, right) in bounds.items():
            digit = label_digit[0]
            rows = _mask(image, left, right)
            if not any("1" in row for row in rows):
                raise ValueError(f"empty template {digit} from {folder}/{filename}")
            if rows not in templates[digit]:
                templates[digit].append(rows)

    return {
        "version": 1,
        "source": "visually labelled local Slayer recording headers",
        "threshold_min_rgb": 170,
        "crop": {"x": 252, "y": 49, "width": 48, "height": 21},
        "digit_rows": {"y_start": 56, "y_end": 62},
        "comma_row": 64,
        "templates": templates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recordings-dir", type=Path,
                        default=ROOT / "macros/local/recordings")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    document = calibrate(args.recordings_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
