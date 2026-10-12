"""Recognized navigation into Daily Quest without touching reward actions."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def load_profiles():
    return json.loads((Path(__file__).resolve().parent / "assets/quest-navigation.json").read_text(encoding="utf-8"))


def _legacy_prefix(steps):
    if not isinstance(steps, list) or len(steps) < 8:
        return False
    signature = [
        (0, "wait_window", None),
        (1, "wait_for_pixel", ("95.05%", "13.52%", [168, 42, 15])),
        (2, "click", ("95.05%", "13.52%", None)),
        (3, "wait", None),
        (4, "wait_for_pixel", ("13.94%", "30.8%", [110, 102, 94])),
        (5, "click", ("13.94%", "30.8%", None)),
        (6, "wait", None),
        (7, "wait_for_pixel", ("83.06%", "48.21%", [227, 141, 30])),
    ]
    for index, action, values in signature:
        step = steps[index]
        if step.get("action") != action:
            return False
        if values is not None:
            x, y, color = values
            if step.get("x") != x or step.get("y") != y:
                return False
            if color is not None and step.get("color") != color:
                return False
    return (steps[0].get("timeout") == 30
            and all(steps[index].get(key) == value for index in (1, 4, 7)
                    for key, value in (("radius", 2), ("tolerance", 30),
                                       ("poll_seconds", 0.5), ("timeout", 30)))
            and all(steps[index].get("x") == "95.05%"
                    and steps[index].get("y") == "13.52%" for index in (1, 2))
            and steps[3].get("seconds") == 1.7
            and steps[5].get("radius") is None
            and steps[5].get("tolerance") is None
            and steps[6].get("seconds") == 1.4)


def prepare_quest_collection(steps):
    """Replace only the recorded Quest entry/tab prefix; retain all claims."""
    if not _legacy_prefix(steps):
        return copy.deepcopy(steps)

    from .home import home_step

    main = copy.deepcopy(next(screen for screen in home_step()["screens"] if screen["name"] == "main"))
    main.update(click={"x": 412, "y": 109}, max_clicks=2, retry_after_seconds=3.0)
    profiles = load_profiles()
    repeat = copy.deepcopy(profiles["quest_repeat"])
    daily = copy.deepcopy(profiles["quest_daily"])
    step = {
        "action": "screen_flow", "terminal": "quest_daily", "timeout": 50,
        "poll_seconds": 0.3, "stable_frames": 2, "frame_size": [434, 810],
        # Daily is a terminal; Repeat alone owns the tab click. If Quest already
        # opens on Daily, it is accepted without an extra click.
        "screens": [main, repeat, daily],
    }
    return [step, *copy.deepcopy(steps[7:])]


def recovery_screens():
    """Close only the two recognized Quest tabs; no Daily reward is claimed."""
    profiles = load_profiles()
    screens = []
    for key in ("quest_repeat", "quest_daily"):
        screen = copy.deepcopy(profiles[key])
        screen["name"] = "recovery_" + key
        screen["click"] = {"x": 390, "y": 205}
        screen["max_clicks"] = 1
        screens.append(screen)
    return screens
