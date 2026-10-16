"""Read free-summon quotas from frames, independently of game input."""
import json
import copy
from pathlib import Path

from league_bot.game import GameError
from league_bot.macro import MacroCancelled, MacroError, MacroRunner
from league_bot.screens import matching_screens
from .shop import _white
from .status import DailyStatusError

TASKS = ('summon_sword', 'summon_accessory', 'summon_skill')


def profiles():
    return json.loads((Path(__file__).parent / 'assets/summons.json').read_text(encoding='utf-8'))


def read_summon_menu(frame, data=None):
    """Return a specifically recognized summon menu, without reading a quota."""
    data = data or profiles()
    if frame is None or (frame.width, frame.height) != tuple(data['frame_size']):
        return None
    matches = matching_screens(frame, data.get('menu_screens', []))
    return matches[0] if len(matches) == 1 else None


def recovery_screens():
    screens=[]
    for screen in profiles()['screens']:
        if screen['counter_surface']!='popup':
            continue
        screen=copy.deepcopy(screen)
        screen.update(name='home_close_'+screen['name'],click={'x':20,'y':340},
                      max_clicks=2,retry_after_seconds=3)
        screens.append(screen)
    return screens


def read_summons(frame, data=None):
    """Return only visually recognized USED quotas; unknowns are absent.

    This function takes a Frame only. It neither captures nor navigates, clicks,
    writes status, or infers success from a macro. GUI observers can reuse it.
    """
    data = data or profiles()
    if frame is None or (frame.width, frame.height) != tuple(data['frame_size']):
        return {}
    matches = matching_screens(frame, data['screens'])
    if len(matches) != 1:
        return {}
    screen = next(s for s in data['screens'] if s['name'] == matches[0])
    surface = screen['counter_surface']
    left, top, right, bottom = data['counter_boxes'][surface]
    points = {(x,y) for y in range(top,bottom) for x in range(left,right)
              if _white(frame.pixel(x,y))}
    if not points:
        return {}
    x0=min(x for x,y in points); x1=max(x for x,y in points)
    y0=min(y for x,y in points); y1=max(y for x,y in points)
    mask=[''.join('1' if (x,y) in points else '0' for x in range(x0,x1+1))
          for y in range(y0,y1+1)]
    readings=set()
    for sample in data['counter_templates'][surface]:
        if mask==sample['mask']:
            readings.add((sample['used'],sample['total']))
    # These small fractions require a near-exact labelled mask. Unknown digits
    # (including uncalibrated rasters) must not become the closest known count.
    if len(readings)!=1:
        return {}
    return {screen.get('task',screen['name']): next(iter(readings))[0]}


def current_cooldown(frame, data=None):
    """Recognize the current weapon popup and its fixed clock colon, never a cost."""
    data = data or profiles()
    if frame is None or (frame.width,frame.height) != tuple(data['frame_size']):
        return False
    popup = [s for s in data['screens'] if s['name'] in
             {'summon_sword_current', 'summon_accessory_current'}]
    if len(matching_screens(frame,popup)) != 1:
        return False
    timer = data.get('current_cooldown_colon')
    if not timer:
        return False
    left,top,right,bottom = timer['box']
    # The timer is centered again as digit widths change; the separator keeps
    # its two-dot shape while shifting a few columns horizontally.
    return any(''.join('1' if _white(frame.pixel(x,y)) else '0' for y in range(top,bottom))
               == timer['column_mask'] for x in range(left,right))


class _SummonCooldown(Exception):
    pass


def record_summons(store, readings, cycle):
    """Persist an observed quota without overwriting newer/manual progress."""
    if store is None:
        return
    if store.cycle_id() != cycle:
        raise MacroCancelled('O ciclo diario mudou durante a conferencia das invocacoes.')
    snapshot=store.snapshot()
    for task,progress in readings.items():
        if task not in TASKS or type(progress) is not int or not 0 <= progress <= 3:
            raise ValueError('Contador de invocacoes invalido.')
        old=snapshot['tasks'].get(task,{})
        if progress < old.get('progress',0):
            continue
        if old.get('progress')==progress and old.get('source')=='visual' and not old.get('last_error'):
            continue
        store.mark_progress(task,progress,3,source='visual',expected_cycle=cycle)


def observation_step(task, *, allow_menu=False, exhausted_branch=False):
    screen=next(s for s in profiles()['screens'] if s['name']==task)
    step={'action':'screen_flow','summon_observe':task,'screens':[screen],
            'terminal':task,'timeout':3,'poll_seconds':.3,'stable_frames':2,
            'frame_size':[434,810]}
    if allow_menu:
        step['summon_allow_menu']=True
    if exhausted_branch:
        step['summon_exhausted_branch']=True
    return step


def popup_entry_step(task):
    step = observation_step(task)
    step['summon_open_popup'] = task
    return step


class SummonRunner(MacroRunner):
    def __init__(self,*args,store=None,cycle=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.store,self.cycle=store,cycle
        self._cooldown_stable=0
        self._exhausted_task=None

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id()!=self.cycle:
            raise MacroCancelled('O ciclo diario mudou durante a conferencia das invocacoes.')

    def _cooldown(self, frame):
        if current_cooldown(frame):
            readings = read_summons(frame)
            record_summons(self.store,readings,self.cycle)
            task = next(iter(readings), 'summon_sword')
            quota = readings.get(task)
            detail = f' ({quota}/3)' if quota is not None else ''
            label = 'acessorios' if task == 'summon_accessory' else 'espada'
            raise _SummonCooldown(f'Invocacoes: {label} em intervalo{detail}; coleta pendente para a proxima daily.')

    def _observe_pixel_frame(self,frame):
        self._check_cancel()
        self._cooldown_stable = self._cooldown_stable+1 if current_cooldown(frame) else 0
        if self._cooldown_stable >= 2:
            self._cooldown(frame)

    def _do_screen_flow(self,step,hwnd):
        if step.get('summon_open_popup') == 'summon_accessory':
            hwnd = self._window(hwnd, 'open accessory quota')
            deadline, stable = self._clock() + 8, 0
            while self._clock() < deadline:
                self._check_cancel()
                frame = self._backend.capture(hwnd)
                self._last_frame = frame
                stable = stable + 1 if read_summon_menu(frame) == 'summon_equipment' else 0
                if stable >= 2:
                    self._backend.click(hwnd, 385, 512, False)
                    return hwnd
                self._pause(.3)
            raise MacroError('Menu de invocacoes desconhecido; acessorios nao abertos.')
        task=step.get('summon_observe')
        if not task:
            return super()._do_screen_flow(step,hwnd)
        exhausted_branch=step.get('summon_exhausted_branch',False)
        if self._exhausted_task and self._exhausted_task != task:
            self._exhausted_task=None
        # Observation markers never execute screen clicks, even on timeout.
        hwnd=self._window(hwnd,'observe summons')
        deadline=self._clock()+step['timeout']
        previous,stable,menu_stable=None,0,0
        while self._clock()<deadline:
            self._check_cancel()
            if self.store and self.store.cycle_id()!=self.cycle:
                raise MacroCancelled('O ciclo diario mudou durante a conferencia das invocacoes.')
            frame=self._backend.capture(hwnd)
            self._last_frame=frame
            self._observe_pixel_frame(frame)
            menu = read_summon_menu(frame)
            if exhausted_branch and self._exhausted_task==task:
                menu_stable=menu_stable+1 if menu=='summon_equipment' else 0
                if menu_stable>=2:
                    return hwnd
                self._pause(min(.3,max(0,deadline-self._clock())))
                continue
            readings=read_summons(frame) if self._backend.client_size(hwnd)==(434,810) else {}
            current=readings.get(task)
            menu_stable = menu_stable+1 if menu=='summon_equipment' else 0
            if step.get('summon_allow_menu') and menu_stable >= 2:
                return hwnd
            if (menu == 'summon_equipment'
                    and current is None and not step.get('summon_allow_menu')
                    and not step.get('summon_allow_transition')):
                # The recorded macro's next summon buttons spend diamonds. This
                # combined menu has no safe quota for the pending item action.
                raise MacroError('Invocacoes: menu de equipamento reconhecido; clique registrado nao autorizado.')
            stable=stable+1 if current is not None and current==previous else (1 if current is not None else 0)
            previous=current
            if stable>=2:
                record_summons(self.store,{task:current},self.cycle)
                self._log(f'Invocacoes: {task} {current}/3 confirmado visualmente.')
                if exhausted_branch and current==3:
                    # This exact quota authorizes only the tested outside-popup
                    # dismissal. Require the equipment menu to return stably.
                    self._check_cancel()
                    self._backend.click(hwnd,20,340,False)
                    menu_stable=0
                    while self._clock()<deadline:
                        self._check_cancel()
                        if self.store and self.store.cycle_id()!=self.cycle:
                            raise MacroCancelled('O ciclo diario mudou durante a conferencia das invocacoes.')
                        frame=self._backend.capture(hwnd)
                        self._last_frame=frame
                        menu_stable=menu_stable+1 if read_summon_menu(frame)=='summon_equipment' else 0
                        if menu_stable>=2:
                            self._exhausted_task=task
                            self._log(f'Invocacoes: {task} esgotada; popup fechado sem repetir clique.')
                            return hwnd
                        self._pause(min(.3,max(0,deadline-self._clock())))
                    raise MacroError(f'Invocacoes: {task} 3/3, mas o menu nao retornou apos fechar popup.')
                return hwnd
            self._pause(min(.3,max(0,deadline-self._clock())))
        raise MacroError(f'Invocacoes: {task} sem leitura visual segura; nenhum clique registrado autorizado.')

    def _skip_exhausted_step(self,step):
        return bool(self._exhausted_task and step.get('summon_task')==self._exhausted_task)

    def _do_wait(self,step,hwnd):
        if self._skip_exhausted_step(step):
            self._log(f"Invocacoes: ignorando etapa restante de {self._exhausted_task} esgotada.")
            return hwnd
        return super()._do_wait(step,hwnd)

    def _do_wait_for_pixel(self,step,hwnd):
        if self._skip_exhausted_step(step):
            self._log(f"Invocacoes: ignorando etapa restante de {self._exhausted_task} esgotada.")
            return hwnd
        return super()._do_wait_for_pixel(step,hwnd)

    def _do_click(self,step,hwnd):
        if self._skip_exhausted_step(step):
            self._log(f"Invocacoes: ignorando clique restante de {self._exhausted_task} esgotada.")
            return hwnd
        return super()._do_click(step,hwnd)

    def _do_click_if_pixel(self,step,hwnd):
        if self._skip_exhausted_step(step):
            self._log(f"Invocacoes: ignorando clique restante de {self._exhausted_task} esgotada.")
            return hwnd
        return super()._do_click_if_pixel(step,hwnd)


def run_summons(game):
    previous=game._runner_factory
    store=game._status_store
    with game._exclusive():
        try:
            cycle=store.cycle_id() if store else None
            def factory(backend,title,foreground,log):
                original=previous(backend,title,foreground,log)
                if not isinstance(original,MacroRunner):
                    raise GameError('Invocacoes exigem o executor visual.')
                return SummonRunner(backend,title,foreground,log,sleep=original._sleep,
                                    clock=original._clock,store=store,cycle=cycle)
            game._runner_factory=factory
            try:
                game._run_steps(game.load_macro_steps('free_wpacs'),'free_wpacs',game._title())
            except _SummonCooldown as exc:
                from .home import home_step
                from .daily import DeferredOutcome
                game._runner_factory=previous
                game._run_steps([home_step(),*game.final_steps()], 'summons_cooldown_return',game._title())
                return DeferredOutcome(str(exc))
        except DailyStatusError as exc:
            raise GameError('Nao foi possivel salvar a conferencia das invocacoes.') from exc
        finally:
            game._runner_factory=previous
