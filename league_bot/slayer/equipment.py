"""Recognized Equipment navigation, independent of the selected subtab/items."""
import copy


def equipment_screen():
    # Selected Equipment navigation plus the fixed tab strip. These anchors
    # exclude moving battle/account/item pixels and all action buttons.
    points = [(160, 785, [255, 146, 0]), (180, 797, [255, 146, 0]),
              (151, 775, [255, 146, 0]), (29, 415, [44, 34, 28]),
              (75, 417, [44, 34, 28])]
    return {"name": "equipment_open", "anchors": [
        {"x": x / 433, "y": y / 809, "color": color,
         "tolerance": 15, "radius": 0} for x, y, color in points
    ]}


def _equipment_subtab_screen(name, sample, color):
    """Recognize one selected Equipment subtab without using item content."""
    screen = copy.deepcopy(equipment_screen())
    screen["name"] = name
    x, y = sample
    screen["anchors"].append({
        "x": x / 433, "y": y / 809, "color": color,
        "tolerance": 25, "radius": 2,
    })
    return screen


def equipment_weapon_screen():
    # The bright Weapon label is distinct from Accessories when Equipment is
    # already selected; the other anchors verify the containing navigation.
    return _equipment_subtab_screen("equipment_weapon", (50, 422), [149, 145, 143])


def equipment_accessories_screen():
    return _equipment_subtab_screen("equipment_accessories", (135, 422), [163, 159, 157])


def equipment_entry_step():
    from .home import load_screens
    main = copy.deepcopy(next(s for s in load_screens() if s["name"] == "main"))
    main.update(click={"x": 184, "y": 784}, max_clicks=2, retry_after_seconds=3)
    return {"action": "screen_flow", "terminal": "equipment_open",
            "timeout": 12, "poll_seconds": .3, "stable_frames": 2,
            "frame_size": [434, 810], "screens": [main, equipment_screen()]}


def equipment_weapon_step():
    """Select Weapon only from a recognized Accessories state; verify it stably."""
    accessories = equipment_accessories_screen()
    accessories["click"] = {"x": 65, "y": 421}
    weapon = equipment_weapon_screen()
    return {"action": "screen_flow", "terminal": "equipment_weapon",
            "timeout": 12, "poll_seconds": .3, "stable_frames": 2,
            "frame_size": [434, 810], "screens": [accessories, weapon]}


def prepare_soul_harvest(steps):
    """Replace only the known recording's blind entry; retain every reward guard.

    Local recordings take precedence over shipped macros. A different custom
    entry is left intact instead of silently rewriting unknown user steps.
    """
    if (len(steps) < 7 or [s.get("action") for s in steps[:4]] !=
            ["wait_window", "wait_for_pixel", "click", "wait"]):
        return steps
    entry_guard, entry_click = steps[1:3]
    if any(s.get("x") != "42.51%" or s.get("y") != "96.85%"
           for s in (entry_guard, entry_click)):
        return steps
    if entry_guard.get("color") != [63, 63, 65]:
        return steps
    weapon_guard, weapon_click = steps[4:6]
    if (weapon_guard.get("action") != "wait_for_pixel"
            or weapon_guard.get("x") != "15.09%"
            or weapon_guard.get("y") != "52.04%"
            or weapon_guard.get("color") != [135, 130, 128]
            or weapon_click.get("action") != "click"
            or weapon_click.get("x") != "15.09%"
            or weapon_click.get("y") != "52.04%"):
        return steps
    # The old guard and click both assumed Weapon was already selected. Move
    # to Weapon only from the visually recognized Accessories state, then
    # keep the original delay and every later reward guard/click unchanged.
    return [copy.deepcopy(steps[0]), equipment_entry_step(), equipment_weapon_step(),
            *copy.deepcopy(steps[6:])]
