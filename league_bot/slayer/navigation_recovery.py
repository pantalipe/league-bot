"""Bounded, navigation-only recovery to Slayer's recognized main screen."""
from __future__ import annotations

from .home import home_step


# These are controls whose existing calibrated profiles close a known panel or
# return through navigation. Keep this list explicit so adding a new action to
# ``home_step`` cannot silently make it part of recovery.
_NAVIGATION_SCREENS = frozenset({
    "main",
    "adventure_map",
    "red_back_panel",
    "multiplier_back",
    "home_close_companion",
    "home_close_beast",
    "home_close_active_mount",
    "home_close_beast_shop",
    "home_close_scrolls",
    "home_close_character_expanded_current",
    "home_close_latent_power_current",
    "home_close_training_diary_current",
    "home_close_forest_current",
    "home_close_forest_difficulty_120_current",
    "home_close_character",
    "home_close_character_enhance",
    "home_close_character_promotion",
    "home_close_character_current",
    "home_close_character_enhance_current",
    "home_close_training_diary",
    "home_close_dragon_difficulty_current",
    "recovery_quest_repeat",
    "recovery_quest_daily",
    "home_close_mailbox",
    "home_close_mailbox_current",
    "home_close_refinement",
    "home_close_skill",
    "home_close_adventurers_guild",
    "home_close_skill_current",
    "home_close_refinement_current",
    "home_close_shop",
    "home_close_summon_sword",
    "home_close_summon_accessory",
    "home_close_summon_sword_current",
    "home_close_summon_accessory_current",
    "home_close_orb_modal",
    "home_close_orb_panel",
    "home_close_orb_panel_current",
    "home_close_orb_modal_current",
    "home_close_equipment",
    "settings_return",
    "menu_return",
    "home_return_guild",
    "home_close_pet",
    "home_close_pet_current",
    "home_return_guild_shop",
})

_PET_REWARD_SCREENS = frozenset({
    "home_confirm_pet_reward",
    "home_confirm_pet_reward_current",
})


def navigation_home_step(*, include_pet_reward: bool = False, timeout: float = 30):
    """Build a bounded screen flow that closes recognized panels and reaches main.

    The default whitelist contains navigation controls only. Set
    ``include_pet_reward`` only when the pet reward is already earned and its
    confirmation should be dismissed as part of recovery. Claims, attendance,
    summon rewards, purchases, and entry controls are never included.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise ValueError("timeout must be greater than 0 and no more than 30 seconds")

    step = home_step()
    allowed = _NAVIGATION_SCREENS | (_PET_REWARD_SCREENS if include_pet_reward else frozenset())
    screens = [screen for screen in step["screens"] if screen["name"] in allowed]

    # Keep recovery bounded even if an underlying profile is later changed.
    for screen in screens:
        if screen["name"] == "main":
            continue
        screen["max_clicks"] = min(screen.get("max_clicks", 1), 2)
        if screen["name"] in _PET_REWARD_SCREENS:
            screen["max_clicks"] = 2
            screen["retry_after_seconds"] = min(screen.get("retry_after_seconds", 3), 3)

    return {
        "action": "screen_flow",
        "timeout": timeout,
        "poll_seconds": min(step.get("poll_seconds", 0.3), 0.5),
        "stable_frames": step.get("stable_frames", 2),
        "frame_size": step.get("frame_size", [434, 810]),
        "terminal": "main",
        "screens": screens,
    }


def recover_home(runner, *, include_pet_reward: bool = False, timeout: float = 30):
    """Run one bounded navigation recovery step on an existing macro runner."""
    return runner.run(
        [navigation_home_step(include_pet_reward=include_pet_reward, timeout=timeout)],
        name="recover_main",
    )
