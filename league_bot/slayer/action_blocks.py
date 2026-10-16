"""Recorded free-action blocks, bounded by the game's entry/result flows."""
import copy
from pathlib import Path

from league_bot.macro import load_macro

# These recordings contain navigation and free collect/combine/training actions.
# Ads, purchases, quota-limited dungeons, pet, and cube use their dedicated guards.
FREE_BLOCKS = frozenset({
    'cobinar_equip', 'collect_familiar', 'colheita_arma_alma',
    'refinamento_skill_completed', 'collect_finished_dailys',
})


def use_action_block(name, recorded):
    if name not in FREE_BLOCKS:
        return False
    return recorded == load_macro(Path(__file__).parent / 'macros' / f'{name}.json')


def action_block(steps):
    """Keep each recorded click and delay; eliminate individual color waits."""
    result = []
    for step in steps:
        if step.get('terminal') == 'equipment_weapon':
            # Equipment was confirmed by the preceding entry flow. Selecting
            # its fixed Weapon tab is navigation, not a claim or purchase.
            result.extend([{'action':'click','x':65,'y':421},
                           {'action':'wait','seconds':.8}])
        elif step['action'] != 'wait_for_pixel':
            result.append(copy.deepcopy(step))
    return result
