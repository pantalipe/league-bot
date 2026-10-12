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


def equipment_entry_step():
    from .home import load_screens
    main = copy.deepcopy(next(s for s in load_screens() if s["name"] == "main"))
    main.update(click={"x": 184, "y": 784}, max_clicks=2, retry_after_seconds=3)
    return {"action": "screen_flow", "terminal": "equipment_open",
            "timeout": 12, "poll_seconds": .3, "stable_frames": 2,
            "frame_size": [434, 810], "screens": [main, equipment_screen()]}


def prepare_soul_harvest(steps):
    """Replace only the known recording's blind entry; retain every reward guard.

    Local recordings take precedence over shipped macros. A different custom
    entry is left intact instead of silently rewriting unknown user steps.
    """
    if (len(steps) < 5 or [s.get("action") for s in steps[:4]] !=
            ["wait_window", "wait_for_pixel", "click", "wait"]):
        return steps
    guard, click = steps[1:3]
    if any(s.get("x") != "42.51%" or s.get("y") != "96.85%" for s in (guard, click)):
        return steps
    if guard.get("color") != [63, 63, 65]:
        return steps
    return [copy.deepcopy(steps[0]), equipment_entry_step(), *copy.deepcopy(steps[4:])]
