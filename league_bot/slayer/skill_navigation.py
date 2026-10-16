"""Navigation through the current Skill toolbar."""
import copy
import json
from pathlib import Path


def skill_screen():
    screens = json.loads((Path(__file__).parent / 'assets/refinement-recovery.json').read_text(encoding='utf-8'))
    screen = copy.deepcopy(next(s for s in screens if s['name'] == 'home_close_skill_current'))
    screen['name'] = 'skill_current'
    screen.pop('click')
    return screen


def prepare_refinement(name, steps):
    """Use entry/result checkpoints for the known free refinement recording."""
    from league_bot.macro import load_macro
    if name != 'refinamento_skill':
        return steps
    known = load_macro(Path(__file__).parent / 'macros/refinamento_skill.json')
    if steps != known:
        return steps
    from .home import home_step
    main = copy.deepcopy(next(s for s in home_step()['screens'] if s['name'] == 'main'))
    main.update(click={'x': 105, 'y': 785})
    skill = skill_screen()
    entry = dict(action='screen_flow', terminal='skill_current', timeout=15,
                 poll_seconds=.3, stable_frames=2, frame_size=[434,810],
                 screens=[main, skill])
    profiles = json.loads((Path(__file__).parent / 'assets/refinement-recovery.json').read_text(encoding='utf-8'))
    grounds = copy.deepcopy(next(s for s in profiles if s['name'] == 'home_close_refinement_current'))
    grounds.update(name='refinement_ground')
    grounds.pop('click', None)
    skill = copy.deepcopy(skill)
    skill.update(click={'x':293, 'y':582})
    open_ground = dict(action='screen_flow', terminal='refinement_ground', timeout=15,
                       poll_seconds=.3, stable_frames=2, frame_size=[434,810],
                       screens=[skill, grounds])
    # Navigation guards in the old recording sampled individual animated pixels.
    # The panel checkpoint authorizes one free start; preserve its actions/delays
    # and verify the return through the caller's final home flow.
    tail = [copy.deepcopy(s) for s in steps[7:] if s['action'] != 'wait_for_pixel']
    return [copy.deepcopy(steps[0]), entry, open_ground, *tail]
