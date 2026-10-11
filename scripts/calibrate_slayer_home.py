"""Calibrate navigation-only recovery from existing local UI captures."""
import json
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from league_bot.config import load_settings
from league_bot.slayer.game import SlayerDailyGame
from league_bot.slayer.navigation import load_daily_navigation

SOURCE = Path(sys.argv[1])
SHELTER = Path(sys.argv[2])
OUT = ROOT / "tests/fixtures/slayer/home"
OUT.mkdir(parents=True, exist_ok=True)
images = {name: Image.open(SOURCE / file).convert("RGB") for name,file in {
    "main":"0001_before.png", "adventure":"0001_after.png", "dungeon":"0003_before.png",
    "rift_free":"0004_before.png", "rift_exhausted":"0007_before.png", "multiplier":"0006_before.png",
}.items()}
images["shelter"] = Image.open(SHELTER).convert("RGB")

def anchors(name, points):
    return [dict(x=x/433,y=y/809,color=list(images[name].getpixel((x,y))),tolerance=20,radius=0)
            for x,y in points]

cube=json.loads((ROOT/"league_bot/slayer/assets/cube.json").read_text(encoding="utf-8"))
main=next(s for s in cube if s["name"]=="main")
map_points=[(300,790),(353,800),(320,802),(310,789),(330,793),(337,791),(323,784),(46,778),(77,801),(404,790)]
points=[]
for y in range(767,790,2):
    for x in range(37,65,2):
        rgb=images["rift_free"].getpixel((x,y))
        other=images["shelter"].getpixel((x,y))
        if max(abs(a-b) for a,b in zip(rgb,other))<=15 and (min(rgb)>160 or rgb[0]>180 and rgb[1]<70 and rgb[2]<70):
            points.append((x,y))
points=points[::max(1,len(points)//28)]
screens=[main,
    dict(name="adventure_map",anchors=anchors("dungeon",map_points),click=dict(x=325,y=784),max_clicks=1),
    dict(name="red_back_panel",anchors=anchors("rift_free",points),click=dict(x=45,y=775),max_clicks=3),
]
multiplier=next(s for s in cube if s["name"]=="multiplier")
multiplier["name"]="multiplier_back"
multiplier["anchors"]=[a for a in multiplier["anchors"] if not 644 <= round(a["y"]*809) <= 665]
multiplier["click"]={"x":45,"y":775}
screens.append(multiplier)
(ROOT/"league_bot/slayer/assets/home-recovery.json").write_text(json.dumps(screens,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
for name,img in images.items():
    draw=ImageDraw.Draw(img)
    draw.rectangle((0,0,433,33),fill=(0,0,0))
    draw.rectangle((0,34,370,79),fill=(0,0,0))
    img.save(OUT/f"{name}.png")
print("Home recovery calibration and masked fixtures saved.")
