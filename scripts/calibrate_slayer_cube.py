"""Build UI anchors/anonymous fixtures from the user's cube recording."""
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
OUT = ROOT / "tests/fixtures/slayer/cube"
OUT.mkdir(parents=True, exist_ok=True)
images = {name: Image.open(SOURCE / file).convert("RGB") for name, file in {
    "main": "0001_before.png", "adventure": "0001_after.png", "dungeon": "0003_before.png",
    "rift_free": "0004_before.png", "multiplier": "0006_before.png",
    "rift_exhausted": "0007_before.png", "loading": "0006_after.png",
    "returned_main": "0008_after.png",
}.items()}

def anchors(name, points):
    return [dict(x=x/433, y=y/809, color=list(images[name].getpixel((x,y))),
                 tolerance=15, radius=0) for x,y in points]

def grid(rect, step=4):
    x1,y1,x2,y2=rect
    return [(x,y) for y in range(y1,y2,step) for x in range(x1,x2,step)]

def bright(name, rect, count=14):
    points=[p for p in grid(rect, 2) if max(images[name].getpixel(p)) > 180]
    return points[::max(1,len(points)//count)][:count]

def screen(name, points, click=None):
    result=dict(name=name, anchors=anchors(name,points))
    if click:
        result.update(click=dict(x=click[0],y=click[1]),max_clicks=1)
    return result

rift_title = bright("rift_free", (139,95,300,113))
screens=[
    screen("adventure",bright("adventure",(160,125,290,141))+bright("adventure",(39,80,112,99)),(185,107)),
    screen("dungeon",bright("dungeon",(159,150,280,174))+bright("dungeon",(127,100,206,118)),(282,422)),
    screen("rift_free",rift_title+grid((196,648,240,663),3),(230,664)),
    screen("multiplier",bright("multiplier",(28,692,405,712),20)+grid((329,573,360,593),4)+grid((196,648,240,663),3),(346,584)),
    screen("rift_exhausted",rift_title+grid((185,646,212,666),3)),
]
settings=load_settings(environ={"SLAYER_WINDOW_TITLE":"Slayer Legend"},env_file=None)
game=SlayerDailyGame(settings,backend=object())
main=next(s for st in game.load_macro_steps("start_game_recognized") if st["action"]=="screen_flow"
          for s in st["screens"] if s["name"]=="main")
main["anchors"] = [a for a in main["anchors"] if a["y"] > .1]
main["anchors"].extend(load_daily_navigation()["main_closed_anchors"])
screens.insert(0,main)
(ROOT / "league_bot/slayer/assets/cube.json").write_text(json.dumps(screens,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
for name,img in images.items():
    draw=ImageDraw.Draw(img)
    draw.rectangle((0,0,433,33),fill=(0,0,0))
    draw.rectangle((0,34,370,79),fill=(0,0,0))
    img.save(OUT / f"{name}.png")
print("Cube calibration and masked fixtures saved.")
