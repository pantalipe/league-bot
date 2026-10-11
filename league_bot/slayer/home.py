"""Navigation-only recovery to the recognized Slayer main page."""
import copy
import json
from pathlib import Path


def load_screens():
    return json.loads((Path(__file__).resolve().parent / "assets/home-recovery.json").read_text(encoding="utf-8"))


def home_step():
    from .navigation import load_daily_navigation, load_attendance_screens
    screens = load_screens()
    nav = load_daily_navigation()
    screens += [nav["settings_return"], nav["menu_return"]]
    from .pet import load_screens as pet_screens
    for screen in pet_screens():
        if screen["name"] in {"pet_open", "guild"}:
            screen = copy.deepcopy(screen)
            panel = screen["name"] == "pet_open"
            screen["name"] = "home_close_pet" if panel else "home_return_guild"
            screen["click"] = {"x":217,"y":746} if panel else {"x":52,"y":777}
            screens.append(screen)
    for screen in [*load_attendance_screens(), nav["attendance_claimed_settings"]]:
        screen = copy.deepcopy(screen)
        screen["name"] = "home_close_" + screen["name"]
        screen["click"] = {"x":217,"y":712}
        screens.append(screen)
    return dict(action="screen_flow", timeout=40, poll_seconds=.3,
                stable_frames=2, frame_size=[434,810], terminal="main", screens=screens)
