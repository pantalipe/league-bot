"""Calibrate stable pet controls from local recordings, excluding account/animations."""
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1])
out = ROOT / "tests/fixtures/slayer/pet"
out.mkdir(parents=True, exist_ok=True)
images = {name: Image.open(source / file).convert("RGB") for name, file in {
    "guild": "0003_before.png", "pet_0": "0004_before.png",
    "pet_1": "0006_before.png", "pet_2": "0008_before.png",
    "pet_3": "0010_before.png", "pet_4": "0012_before.png",
    "pet_5": "0014_before.png", "reward": "0005_before.png",
}.items()}

def grid(rect, stride=3):
    x1, y1, x2, y2 = rect
    return [(x, y) for y in range(y1, y2, stride) for x in range(x1, x2, stride)]

def bright(image, rect, count=25):
    points = [p for p in grid(rect, 1) if min(image.getpixel(p)) > 190]
    return points[::max(1, len(points)//count)][:count]

def screen(name, image, points, click=None):
    result = dict(name=name, anchors=[dict(x=x/433, y=y/809,
                  color=list(image.getpixel((x, y))), tolerance=10, radius=0) for x, y in points])
    if click:
        result.update(click=dict(x=click[0], y=click[1]), max_clicks=1)
    return result

screens = [screen("guild", images["guild"], bright(images["guild"], (173,789,207,806))
                  + grid((34,764,68,790),4) + grid((382,765,402,790),4), (181,773))]
title = bright(images["pet_0"], (164,157,277,177))
screens.append(screen("pet_open", images["pet_0"], title + grid((58,477,69,571),12)))
for counter in range(6):
    name = f"pet_{counter}"
    image = images[name]
    points = title + grid((326,586,360,603),1) + grid((178,617,258,638),3)
    screens.append(screen(name, image, points))
screens.append(screen("reward", images["reward"], bright(images["reward"], (137,371,302,397))
                      + grid((170,647,179,676),3), (216,662)))
(ROOT / "league_bot/slayer/assets/pet.json").write_text(json.dumps(screens,indent=2)+"\n",encoding="utf-8")
for name,image in images.items():
    # Only calibrated controls are retained; account, guild chat and avatars omitted.
    masked = Image.new("RGB", image.size)
    for rect in ((28,150,405,180),(54,470,72,576),(326,586,362,606),
                 (162,613,275,686),(134,367,307,401),(28,760,72,807),(170,785,211,809),(380,760,406,798)):
        masked.paste(image.crop(rect), rect[:2])
    masked.save(out / f"{name}.png")
print("Pet profiles and sanitized fixtures saved.")
