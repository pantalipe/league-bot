"""Navigation-only recovery to the recognized Slayer main page."""
import copy
import json
from pathlib import Path


def load_screens():
    return json.loads((Path(__file__).resolve().parent / "assets/home-recovery.json").read_text(encoding="utf-8"))


def home_step():
    from .navigation import load_daily_navigation, load_attendance_screens
    screens = load_screens()
    from .companion import recovery_screens as companion_recovery
    screens.extend(companion_recovery())
    from .scrolls import recovery_screens as scroll_recovery
    screens.extend(scroll_recovery())
    from .battle_navigation import recovery_screens as battle_recovery
    from .quest_navigation import recovery_screens as quest_recovery
    screens.extend(battle_recovery())
    screens.extend(json.loads((Path(__file__).resolve().parent / "assets/dragon-recovery.json").read_text(encoding="utf-8")))
    screens.extend(quest_recovery())
    from .mailbox import recovery_screens as mailbox_recovery
    screens.extend(mailbox_recovery())
    screens.extend(json.loads((Path(__file__).resolve().parent / "assets/refinement-recovery.json").read_text(encoding="utf-8")))
    from .shop import recovery_screens as shop_recovery
    screens.extend(shop_recovery())
    from .summons import recovery_screens as summon_recovery
    screens.extend(summon_recovery())
    from .orb import recovery_screens
    screens.extend(recovery_screens())
    from .equipment import equipment_screen
    equipment = equipment_screen()
    equipment["name"] = "home_close_equipment"
    equipment["click"] = {"x": 184, "y": 784}
    screens.append(equipment)
    nav = load_daily_navigation()
    screens += [nav["settings_return"], nav["menu_return"]]
    from .pet import load_screens as pet_screens
    for screen in pet_screens():
        if screen["name"] in {"reward", "reward_current"}:
            screen = copy.deepcopy(screen)
            screen.update(name="home_confirm_pet_" + screen['name'], max_clicks=2, retry_after_seconds=3)
            screens.append(screen)
        elif screen["name"] in {"pet_open", "pet_open_current", "guild"}:
            screen = copy.deepcopy(screen)
            panel = screen["name"] != "guild"
            screen["name"] = ("home_close_pet_current" if screen['name'] == 'pet_open_current' else
                              "home_close_pet" if panel else "home_return_guild")
            screen["click"] = {"x":217,"y":746} if panel else {"x":52,"y":777}
            screens.append(screen)
    for screen in [*load_attendance_screens(), nav["attendance_claimed_settings"]]:
        screen = copy.deepcopy(screen)
        screen["name"] = "home_close_" + screen["name"]
        screen["click"] = {"x":217,"y":712}
        screens.append(screen)
    from .guild_navigation import load_profiles as guild_profiles
    guild_shop = copy.deepcopy(guild_profiles()["guild_shop"])
    guild_shop.update(name="home_return_guild_shop",click={"x":50,"y":777})
    screens.append(guild_shop)
    return dict(action="screen_flow", timeout=40, poll_seconds=.3,
                stable_frames=2, frame_size=[434,810], terminal="main", screens=screens)
