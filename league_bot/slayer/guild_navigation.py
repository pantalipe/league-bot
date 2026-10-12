"""Recognized, bounded navigation into Guild Shop and Guild pet.

These profiles deliberately sample fixed navigation artwork and Guild UI, not
the account header or changing currency/count text.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


def load_profiles():
    return json.loads((Path(__file__).resolve().parent / "assets/guild-navigation.json").read_text(encoding="utf-8"))


def _guild_profile():
    from .pet import load_screens as load_pet_screens
    screen = copy.deepcopy(next(screen for screen in load_pet_screens() if screen["name"] == "guild"))
    screen["name"] = "guild_lobby"
    screen.pop("click", None)
    return screen


def _main_profile():
    from .home import home_step
    return copy.deepcopy(next(screen for screen in home_step()["screens"] if screen["name"] == "main"))


def _map_profiles():
    profiles = load_profiles()["maps"]
    result = []
    for source in profiles:
        screen = copy.deepcopy(source)
        screen["click"] = {"x": 293, "y": 110}  # fixed Guild tab
        result.append(screen)
    return result


def guild_entry_step():
    """Navigate from the recognized main/map state to the Guild lobby."""
    main = _main_profile()
    main["click"] = {"x": 331, "y": 784}  # Adventure tab
    return {
        "action": "screen_flow", "terminal": "guild_lobby", "timeout": 45,
        "poll_seconds": 0.3, "stable_frames": 2, "frame_size": [434, 810],
        "screens": [main, *_map_profiles(), _guild_profile()],
    }


def _legacy_shop_navigation(steps):
    """Match the recorded 0..9 navigation prefix, leaving all claim actions intact."""
    if not isinstance(steps, list) or len(steps) < 11:
        return False
    expected = [
        (0, "wait_window", None),
        (1, "wait_for_pixel", ("74.08%", "97.35%", [82, 72, 30])),
        (2, "click", ("74.08%", "97.35%", None)),
        (4, "wait_for_pixel", ("62.56%", "12.78%", [43, 34, 30])),
        (5, "click", ("62.56%", "12.78%", None)),
        (7, "wait_for_pixel", ("53.8%", "96.6%", [86, 47, 6])),
        (8, "click", ("53.8%", "96.6%", None)),
    ]
    for index, action, values in expected:
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
            and steps[3].get("action") == "wait" and steps[3].get("seconds") == 2.1
            and steps[6].get("action") == "wait" and steps[6].get("seconds") == 1.6
            and steps[9].get("action") == "wait" and steps[9].get("seconds") == 2.6)


def prepare_guild_shop(steps):
    """Replace only the known coordinate-based shop entry; preserve claim/reward steps."""
    if not _legacy_shop_navigation(steps):
        return copy.deepcopy(steps)
    main = _main_profile()
    main["click"] = {"x": 331, "y": 784}
    guild = _guild_profile()
    guild["click"] = {"x": 234, "y": 775}  # center of the fixed Daily Shop icon
    # If the recognized lobby remains after the first control click, allow one
    # delayed retry. A transition to Shop changes the screen and ends this path.
    guild["max_clicks"] = 2
    guild["retry_after_seconds"] = 3.0
    shop = copy.deepcopy(load_profiles()["guild_shop"])
    step = {
        "action": "screen_flow", "terminal": "guild_shop", "timeout": 55,
        "poll_seconds": 0.3, "stable_frames": 2, "frame_size": [434, 810],
        "screens": [main, *_map_profiles(), guild, shop],
    }
    return [step, *copy.deepcopy(steps[10:])]
