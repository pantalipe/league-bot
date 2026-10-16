"""Select the fixed Dungeon tab before replaying calibrated dungeon actions."""
import copy
import json
from pathlib import Path
from league_bot.macro import load_macro

def dungeon_entry_step():
    from .home import home_step
    from .guild_navigation import load_profiles
    from .pet import load_screens
    main=copy.deepcopy(next(s for s in home_step()['screens'] if s['name']=='main'))
    main.update(click={'x':331,'y':784},max_clicks=2,retry_after_seconds=3)
    maps=copy.deepcopy(load_profiles()['maps'])
    adventure=next(s for s in maps if s['name']=='guild_map_adventure')
    adventure.update(name='dungeon_select',click={'x':185,'y':107},max_clicks=2,retry_after_seconds=3)
    dungeon=next(s for s in maps if s['name']=='guild_map_dungeon')
    dungeon.update(name='dungeon_ready')
    guild=copy.deepcopy(next(s for s in load_screens() if s['name']=='guild'))
    guild.update(name='dungeon_leave_guild',click={'x':52,'y':777})
    return dict(action='screen_flow',terminal='dungeon_ready',timeout=40,poll_seconds=.3,
                stable_frames=2,frame_size=[434,810],screens=[main,adventure,dungeon,guild])

def prepare_dungeon_macro(name,steps):
    if name not in {'dragao_dormente','floresta_circulacao','cave_treinoxp'}:
        return steps
    known=load_macro(Path(__file__).parent/'macros'/f'{name}.json')
    # Forest's recording starts with closing and reopening Adventure. The
    # recognized entry already reaches Dungeon, so retain actions only from
    # the forest entrance guard onward rather than replaying that toggle.
    prefix = 7 if name == 'floresta_circulacao' else 4
    if len(steps)<=prefix or steps[:prefix]!=known[:prefix]:
        return steps
    tail = copy.deepcopy(steps[prefix:])
    if name == 'dragao_dormente' and steps == known:
        gate = json.loads((Path(__file__).parent/'assets/dragon-multiplier.json').read_text(encoding='utf-8'))
        checkpoint = dict(action='screen_flow',terminal=gate['name'],screens=[gate],
                          timeout=8,poll_seconds=.3,stable_frames=2,frame_size=[434,810])
        tail = []
        for index, action in enumerate(steps[prefix:],prefix):
            if index == 16:
                tail.append(checkpoint)
            elif action['action'] != 'wait_for_pixel':
                tail.append(copy.deepcopy(action))
    return [copy.deepcopy(steps[0]),dungeon_entry_step(),*tail]

def prepare_summons(steps):
    known=load_macro(Path(__file__).parent/'macros/free_wpacs.json')
    if steps != known:
        return steps
    from .home import home_step
    from .shop import profiles
    import json
    main=copy.deepcopy(next(s for s in home_step()['screens'] if s['name']=='main'))
    main.update(click={'x':404,'y':784},max_clicks=2,retry_after_seconds=3)
    shop=copy.deepcopy(next(s for s in profiles()['screens'] if s['name']=='shop_open'))
    goods=copy.deepcopy(next(s for s in profiles()['screens'] if s['name']=='shop_goods'))
    goods.update(click={'x':55,'y':288})
    summon=json.loads((Path(__file__).parent/'assets/summon-navigation.json').read_text())
    flow=dict(action='screen_flow',terminal='shop_open',timeout=25,poll_seconds=.3,
              stable_frames=2,frame_size=[434,810],screens=[main,shop])
    select=dict(flow,terminal='shop_summon',screens=[goods,summon])
    from .summons import observation_step, popup_entry_step
    observations={7:'summon_sword',12:'summon_sword',18:'summon_accessory',
                  23:'summon_accessory',27:'summon_skill',32:'summon_skill'}
    suffix=[]
    for index,step in enumerate(steps[4:],4):
        if index == 24:
            suffix.append(dict(observation_step('summon_skill'),summon_claim_skill=True))
        if 24 <= index <= 32:
            continue
        if index == 13:
            popup = observation_step('summon_accessory', exhausted_branch=True)
            popup['summon_allow_transition'] = True
            suffix.extend([popup_entry_step('summon_accessory'), popup])
        if 13 <= index <= 18:
            continue
        prepared=copy.deepcopy(step)
        task = ('summon_sword' if 8 <= index <= 12 else
                'summon_accessory' if 19 <= index <= 23 else
                'summon_skill' if 28 <= index <= 32 else None)
        if task:
            # Once the exact quota is 3/3, suppress only that task's remaining
            # recorded claim segment. Keep the final menu-exit action live.
            prepared['summon_task']=task
        suffix.append(prepared)
        if index in observations:
            observation=observation_step(observations[index], exhausted_branch=True)
            if index in {12,23}:
                observation.update(summon_reopen_popup=True,summon_allow_transition=True,timeout=12)
            suffix.append(observation)
    return [copy.deepcopy(steps[0]),flow,select,
            observation_step('summon_skill', allow_menu=True),*suffix]
