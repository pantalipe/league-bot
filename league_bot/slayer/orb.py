"""Black Orb collection from recognized counters; never replay a claim click."""
import copy
import json
from dataclasses import dataclass
from pathlib import Path

from league_bot.game import GameError
from league_bot.macro import MacroRunner, MacroError, MacroCancelled
from league_bot.screens import matching_screens
from .status import DailyStatusError

TASK = 'macro:blorb'


def profiles():
    return json.loads((Path(__file__).parent / 'assets/orb.json').read_text(encoding='utf-8'))


def recovery_screens():
    screens = {s['name']: s for s in profiles()['screens']}
    result = []
    for name, click in [('orb_modal', {'x':217,'y':750}), ('orb_panel', {'x':43,'y':773})]:
        screen = copy.deepcopy(screens[name])
        screen.update(name='home_close_' + name, click=click)
        result.append(screen)
    current = copy.deepcopy(next(s for s in screens.values() if s['name'] == 'orb_panel_current'))
    current.update(name='home_close_orb_panel_current', click={'x':41,'y':779})
    result.append(current)
    current_modal = copy.deepcopy(screens['orb_modal_current'])
    current_modal.update(name='home_close_orb_modal_current', click={'x':217,'y':760})
    result.append(current_modal)
    return result


def _current_accessories_screen():
    """Recognize the current Accessories layout by its tab and action control.

    The game moved the selected tab label down a few pixels and added the
    Batch Combine control, invalidating the old sampled text raster. Keep that
    legacy profile for its fixtures and add a small, independent signature for
    the new layout. Equipment navigation anchors constrain the screen; the two
    samples confirm Accessories and its visible page action.
    """
    from .equipment import equipment_screen
    screen = equipment_screen()
    screen['name'] = 'orb_accessories_current'
    screen['anchors'].extend([
        {'x': 120 / 433, 'y': 428 / 809, 'color': [255, 255, 255], 'tolerance': 20, 'radius': 0},
        {'x': 200 / 433, 'y': 710 / 809, 'color': [227, 141, 30], 'tolerance': 20, 'radius': 1},
    ])
    return screen


def _white(rgb):
    return rgb is not None and min(rgb) >= 140 and max(rgb)-min(rgb) <= 65


def read_counter(frame, data=None):
    data = data or profiles()
    if frame is None or (frame.width,frame.height) != (434,810):
        raise MacroError('Contador do Black Orb ilegivel; nenhuma coleta autorizada.')
    left,top,right,bottom = data['counter_box']
    points = {(x,y) for y in range(top,bottom) for x in range(left,right) if _white(frame.pixel(x,y))}
    if not points:
        raise MacroError('Contador do Black Orb ilegivel; nenhuma coleta autorizada.')
    x0,y0 = min(x for x,y in points), min(y for x,y in points)
    x1,y1 = max(x for x,y in points), max(y for x,y in points)
    mask = [''.join('1' if (x,y) in points else '0' for x in range(x0,x1+1)) for y in range(y0,y1+1)]
    matches = set()
    for candidate in data['counters']:
        template = candidate['mask']
        if len(template) != len(mask) or len(template[0]) != len(mask[0]):
            continue
        errors = sum(a != b for row,ref in zip(mask,template) for a,b in zip(row,ref))
        if errors <= 6:
            matches.add((candidate['used'],candidate['total']))
    if len(matches) != 1:
        raise MacroError('Contador do Black Orb desconhecido; nenhuma coleta autorizada.')
    return next(iter(matches))


@dataclass(frozen=True)
class OrbState:
    kind: str
    progress: int


def classify(frame, data=None):
    data = data or profiles()
    modal_screens = [s for s in data['screens'] if s['name'] in ('orb_modal','orb_modal_current')]
    modal_matches = matching_screens(frame,modal_screens)
    if len(modal_matches) != 1:
        raise MacroError('Painel Black Orb desconhecido; nenhuma coleta autorizada.')
    # The observed state after both ad claims replaces Daily limit with a
    # feather icon and price. Recognize it only to stop; never click its Obtain.
    paid = [{'name': name, 'anchors': anchors} for name, anchors in data['buttons'].items()
            if name in {'paid', 'paid_current'}]
    if matching_screens(frame, paid):
        return OrbState('exhausted',3)
    used,total = read_counter(frame,data)
    if total not in (1,2) or not 0 <= used <= total:
        raise MacroError('Limite do Black Orb desconhecido; nenhuma coleta autorizada.')
    progress = used if total == 1 else 1 + used
    if used == total:
        return OrbState('exhausted' if total == 2 else 'free_exhausted',progress)
    buttons = [{'name':name,'anchors':anchors} for name,anchors in data['buttons'].items()
               if name not in {'paid', 'paid_current'}]
    matches = matching_screens(frame,buttons)
    # Current game captures use a brighter red on the ad button than the
    # legacy profile. Keep each raster strict, but normalize the current
    # profile alias before deciding which action the observed state permits.
    kinds = {'ad_current': 'ad'}
    observed = {kinds.get(name, name) for name in matches}
    if len(observed) > 1:
        raise MacroError('Botao ou custo do Black Orb desconhecido; nenhuma coleta autorizada.')
    kind = next(iter(observed), None)
    if kind == 'free' and total == 1:
        return OrbState('free_ready',progress)
    if kind == 'ad' and total == 2:
        return OrbState('ad_ready',progress)
    if kind == 'cooldown' and total == 2:
        return OrbState('cooldown',progress)
    raise MacroError('Botao ou custo do Black Orb desconhecido; nenhuma coleta autorizada.')


@dataclass(frozen=True)
class OrbOutcome:
    progress: int
    acquired: int = 0
    deferred: bool = False
    reason: str = ''
    recorded: bool = False

    @property
    def skipped(self):
        return self.acquired == 0

    def __str__(self):
        return self.reason or f'Black Orb: {self.progress}/3 coletas confirmadas.'


class OrbRunner(MacroRunner):
    def __init__(self,*args,store=None,cycle=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.store,self.cycle = store,cycle
        self.data = profiles()
        self.screens = {s['name']:s for s in self.data['screens']}
        self.outcome = None

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id() != self.cycle:
            raise MacroCancelled('O ciclo diario mudou durante a coleta Black Orb.')

    def _flow(self,hwnd,terminal,screens,timeout=20):
        step = dict(action='screen_flow',terminal=terminal,screens=screens,
            timeout=timeout,poll_seconds=.3,stable_frames=2,frame_size=[434,810])
        if terminal == 'orb_panel' and any(s['name'] == 'orb_panel_current' for s in screens):
            step['terminal_aliases'] = ['orb_panel_current']
        return super()._do_screen_flow(step,hwnd)

    def _open_modal(self,hwnd):
        current = self.screens['orb_panel_current']
        if matching_screens(self._backend.capture(hwnd), [current]) == ['orb_panel_current']:
            panel = copy.deepcopy(current)
            panel.update(click={'x':380,'y':770})
            return self._flow(hwnd,'orb_modal_current',[panel,self.screens['orb_modal_current']])
        panel = copy.deepcopy(self.screens['orb_panel'])
        panel.update(click={'x':380,'y':770},max_clicks=2,retry_after_seconds=3)
        return self._flow(hwnd,'orb_modal',[panel,self.screens['orb_modal']])

    def _state(self,hwnd,timeout=8):
        deadline = self._clock()+timeout
        previous,stable,last_error = None,0,''
        while self._clock() < deadline:
            self._check_cancel()
            frame = self._backend.capture(hwnd)
            self._last_frame = frame
            try:
                if self._backend.client_size(hwnd) != (434,810):
                    raise MacroError('Geometria do Black Orb mudou; nenhuma coleta autorizada.')
                state = classify(frame,self.data)
            except MacroError as exc:
                previous,stable,last_error = None,0,str(exc)
            else:
                stable = stable+1 if state == previous else 1
                previous = state
                if stable >= 2 and self._clock() < deadline:
                    return state
            self._pause(min(.3,max(0,deadline-self._clock())))
        raise MacroError(last_error or 'Estado do Black Orb instavel; nenhuma coleta autorizada.')

    def _record(self,progress,acquired):
        if self.store:
            previous = self.store.snapshot().get('tasks',{}).get(TASK,{})
            if previous.get('progress',0) > progress:
                raise MacroError('Contador Black Orb menor que o progresso salvo; nenhuma nova coleta autorizada.')
            if not acquired and previous.get('progress') == progress and not previous.get('last_error'):
                return
            self.store.mark_progress(TASK,progress,3,label='blorb',
                source='macro' if acquired else 'visual',expected_cycle=self.cycle)

    def _do_screen_flow(self,step,hwnd):
        if not step.get('black_orb'):
            return super()._do_screen_flow(step,hwnd)
        from .home import home_step
        from .equipment import equipment_entry_step,equipment_screen
        hwnd = super()._do_screen_flow(home_step(),hwnd)
        hwnd = super()._do_screen_flow(equipment_entry_step(),hwnd)
        # This is a subtab selector, not a reward/purchase. Verify Equipment
        # again before selecting Accessories; only its recognized icon opens Orb.
        hwnd = self._flow(hwnd,'equipment_open',[equipment_screen()])
        self._check_cancel()
        self._backend.click(hwnd,150,417,False)
        accessories = copy.deepcopy(self.screens['orb_accessories'])
        accessories.update(click={'x':401,'y':453},max_clicks=2,retry_after_seconds=3)
        current_accessories = _current_accessories_screen()
        current_accessories.update(click={'x':401,'y':453},max_clicks=2,retry_after_seconds=3)
        current_panel = self.screens['orb_panel_current']
        hwnd = self._flow(hwnd,'orb_panel',[accessories,current_accessories,self.screens['orb_panel'],current_panel])
        hwnd = self._open_modal(hwnd)
        state = self._state(hwnd)
        # Reconcile a previously confirmed game action before another claim;
        # a mismatch fails closed instead of replaying the old recording.
        self._record(state.progress,False)
        if state.kind in {'cooldown','exhausted','free_exhausted'}:
            reason = ('Black Orb: intervalo ativo; coleta pendente para a proxima daily.'
                      if state.kind == 'cooldown' else
                      'Black Orb: limite desta modalidade esgotado; nenhuma nova coleta realizada.')
            self.outcome = OrbOutcome(state.progress,deferred=True,reason=reason,recorded=bool(self.store))
            return super()._do_screen_flow(home_step(),hwnd)
        # Re-observe the ready counter/button before ONE irreversible claim.
        if self._state(hwnd) != state:
            raise MacroError('Black Orb mudou antes da coleta; nenhum clique realizado.')
        self._check_cancel()
        self._backend.click(hwnd,217,656,False)
        # Unknown ad/loading screens receive no input. Only an observed return
        # to the Orb panel can open the counter again, and Obtain is never retried.
        hwnd = self._flow(hwnd,'orb_panel',[
            self.screens['orb_panel'], self.screens['orb_panel_current']
        ],timeout=120)
        hwnd = self._open_modal(hwnd)
        after = self._state(hwnd)
        if after.progress != state.progress+1:
            raise MacroError('Black Orb: coleta sem incremento confirmado do contador; nao repetir Obtain.')
        self._record(after.progress,True)
        self.outcome = OrbOutcome(after.progress,acquired=1,recorded=bool(self.store))
        return super()._do_screen_flow(home_step(),hwnd)


def run_orb(game):
    from .home import home_step
    store,cycle = game._status_store,None
    previous = game._runner_factory
    runners=[]
    with game._exclusive():
        try:
            cycle = store.cycle_id() if store else None
            def factory(backend,title,foreground,log):
                original = previous(backend,title,foreground,log)
                if not isinstance(original,MacroRunner):
                    raise GameError('Black Orb exige o executor visual.')
                runner = OrbRunner(backend,title,foreground,log,sleep=original._sleep,
                    clock=original._clock,store=store,cycle=cycle)
                runners.append(runner)
                return runner
            game._runner_factory=factory
            game._run_steps([{'action':'wait_window','timeout':5},{'action':'prepare_window'},
                {'action':'move_resize','width':438,'height':814},dict(home_step(),black_orb=True),
                *game.final_steps()],'blorb',game._title())
            return runners[-1].outcome
        except DailyStatusError as exc:
            raise GameError('Nao foi possivel salvar o acompanhamento do Black Orb.') from exc
        finally:
            game._runner_factory=previous
