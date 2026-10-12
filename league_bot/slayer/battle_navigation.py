"""Recognized navigation to Forest and Character, retaining reward actions."""
import copy
import json
from pathlib import Path
from league_bot.macro import load_macro

def profiles():
    return json.loads((Path(__file__).parent/'assets/battle-navigation.json').read_text())

def recovery_screens():
    screens=[]
    for key in ('character','character_enhance'):
        character=copy.deepcopy(profiles()[key])
        character.update(name='home_close_'+key,click={'x':33,'y':784},
                         max_clicks=2,retry_after_seconds=3)
        screens.append(character)
    return screens

def prepare_battle_entry(name,steps):
    if name not in {'floresta_circulacao','treinador'}:
        return steps
    known=load_macro(Path(__file__).parent/'macros'/f'{name}.json')
    prefix=13 if name=='floresta_circulacao' else 7
    if len(steps)<=prefix or steps[:prefix]!=known[:prefix]:
        return steps
    from .home import home_step
    from .dungeon_navigation import dungeon_entry_step
    if name=='floresta_circulacao':
        navigation=dungeon_entry_step()
        entry=copy.deepcopy(next(s for s in navigation['screens'] if s['name']=='dungeon_ready'))
        entry.update(click={'x':302,'y':551},max_clicks=2,retry_after_seconds=3)
        terminal=profiles()['forest']
        first=[copy.deepcopy(steps[0]),navigation]
    else:
        entry=copy.deepcopy(next(s for s in home_step()['screens'] if s['name']=='main'))
        entry.update(click={'x':33,'y':784},max_clicks=2,retry_after_seconds=3)
        terminal=profiles()['character']
        first=[copy.deepcopy(steps[0])]
    flow=dict(action='screen_flow',terminal=terminal['name'],screens=[entry,terminal],
              timeout=35,poll_seconds=.3,stable_frames=2,frame_size=[434,810])
    if name=='floresta_circulacao':
        rows=[profiles()['forest_120_recorded'],profiles()['forest_120_current']]
        popup=profiles()['forest_popup']
        select=dict(flow,terminal=popup['name'],screens=[*rows,popup])
        return [*first,flow,select,*copy.deepcopy(steps[prefix:])]
    enhance=copy.deepcopy(profiles()['character_enhance'])
    enhance.update(click={'x':130,'y':539},max_clicks=2,retry_after_seconds=3)
    flow['screens'].insert(1,enhance)
    return [*first,flow,*copy.deepcopy(steps[prefix:])]
