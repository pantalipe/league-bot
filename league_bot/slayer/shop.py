"""Fail-closed, ad-only collection from the Slayer Goods shop."""
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from league_bot.game import GameError
from league_bot.macro import MacroRunner, MacroError, MacroCancelled
from league_bot.screens import matching_screens
from .status import DailyStatusError

TASK = 'macro:free_item_shop'


def profiles():
    return json.loads((Path(__file__).parent / 'assets/shop.json').read_text(encoding='utf-8'))


def recovery_screens():
    """Recognize the general Shop surface and close via its selected nav tab."""
    screen = copy.deepcopy(next(s for s in profiles()['screens'] if s['name'] == 'shop_open'))
    screen.update(name='home_close_shop', click={'x':404,'y':784})
    return [screen]


def _white(rgb):
    return rgb is not None and min(rgb) >= 140 and max(rgb)-min(rgb) <= 65


def read_counters(frame, data=None):
    """Read only calibrated exact count glyphs; an unfamiliar digit is unknown."""
    data = data or profiles()
    if frame is None or (frame.width, frame.height) != (434, 810):
        raise MacroError('Contadores da loja ilegiveis; nenhuma coleta autorizada.')
    return {kind: read_counter(frame,kind,data) for kind in data['counter_boxes']}


def read_counter(frame, kind, data=None):
    data=data or profiles()
    if frame is None or (frame.width,frame.height)!=(434,810) or kind not in data['counter_boxes']:
        raise MacroError('Contador da loja ilegivel; nenhuma coleta autorizada.')
    boxes=data.get('counter_box_variants', {}).get(kind, [data['counter_boxes'][kind]])
    readings=set()
    for left,top,right,bottom in boxes:
        points={(x,y) for y in range(top,bottom) for x in range(left,right) if _white(frame.pixel(x,y))}
        if not points:
            continue
        x0,y0=min(x for x,y in points),min(y for x,y in points)
        x1,y1=max(x for x,y in points),max(y for x,y in points)
        mask=[''.join('1' if (x,y) in points else '0' for x in range(x0,x1+1))
              for y in range(y0,y1+1)]
        distances=sorted((_mask_distance(mask,sample['mask']),sample['used'],sample['total'])
                         for sample in data['counter_templates'])
        if (not distances or distances[0][0] > 0.065
                or (distances[0][0] > 0.002 and len(distances)>1
                    and distances[1][0]-distances[0][0] < 0.015)):
            continue
        readings.add((distances[0][1],distances[0][2]))
    if len(readings)!=1:
        raise MacroError(f'Contador {kind} desconhecido; coleta pendente.')
    return next(iter(readings))


def _validate_increment(before, after, selected):
    other='emeralds' if selected=='diamonds' else 'diamonds'
    used,total=before[selected]
    if after[selected]!=(used+1,total) or after[other]!=before[other]:
        raise MacroError('Loja: contador desconhecido; coleta pendente.')


def _mask_distance(left, right):
    """Hamming distance after centering glyph lines with small capture variance."""
    height=max(len(left),len(right)); width=max(len(left[0]),len(right[0]))
    def pad(mask):
        rows=(height-len(mask))//2
        out=['0'*width]*rows
        for row in mask:
            left_pad=(width-len(row))//2
            out.append('0'*left_pad+row+'0'*(width-len(row)-left_pad))
        out.extend(['0'*width]*(height-len(out)))
        return out
    a,b=pad(left),pad(right)
    return sum(x != y for ra,rb in zip(a,b) for x,y in zip(ra,rb))/(height*width)


@dataclass(frozen=True)
class ShopOutcome:
    progress: int
    acquired: int = 0
    deferred: bool = False
    reason: str = ''
    recorded: bool = False

    @property
    def skipped(self):
        return self.deferred and self.progress < 20

    def __str__(self):
        return self.reason or f'Loja: {self.progress} anuncios gratuitos confirmados.'


class ShopRunner(MacroRunner):
    def __init__(self,*args,store=None,cycle=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.store,self.cycle = store,cycle
        self.data = profiles()
        self.screens = {screen['name']: screen for screen in self.data['screens']}
        self.goods = self.screens['shop_goods']
        self.shop_open = self.screens['shop_open']
        self.claim_toast = self.data['claim_toast']
        self.outcome = None

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id() != self.cycle:
            raise MacroCancelled('O ciclo diario mudou durante a coleta da loja.')

    def _flow(self,hwnd,terminal,screens,timeout=20):
        return super()._do_screen_flow(dict(action='screen_flow',terminal=terminal,
            screens=screens,timeout=timeout,poll_seconds=.3,stable_frames=2,
            frame_size=[434,810]),hwnd)

    def _observe(self,hwnd,timeout=8):
        deadline=self._clock()+timeout
        previous,stable,last_error=None,0,''
        while self._clock()<deadline:
            self._check_cancel()
            frame=self._backend.capture(hwnd); self._last_frame=frame
            if self._backend.client_size(hwnd)!=(434,810):
                raise MacroError('Geometria da loja mudou; nenhuma coleta autorizada.')
            if matching_screens(frame,[self.claim_toast]) == ['claim_toast']:
                last_error='Mensagem de recompensa ainda visivel; aguardando contador limpo.'
                previous,stable=None,0
            elif matching_screens(frame,[self.goods]) != ['shop_goods']:
                last_error='Painel Goods desconhecido; nenhuma coleta autorizada.'
                previous,stable=None,0
            else:
                try: counters=read_counters(frame,self.data)
                except MacroError as exc:
                    counters=None; last_error=str(exc)
                    previous,stable=None,0
                if counters is not None:
                    stable=stable+1 if counters==previous else 1; previous=counters
                    if stable>=2:
                        return counters,frame
            self._pause(min(.3,max(0,deadline-self._clock())))
        raise MacroError(last_error or 'Contadores da loja instaveis; nenhuma coleta autorizada.')

    def _ensure_goods(self,hwnd):
        """Select Goods only after the general Shop surface is recognized."""
        deadline=self._clock()+8
        candidate,stable=None,0
        while self._clock()<deadline:
            self._check_cancel()
            frame=self._backend.capture(hwnd); self._last_frame=frame
            if self._backend.client_size(hwnd)!=(434,810):
                raise MacroError('Geometria da loja mudou; nenhuma coleta autorizada.')
            if matching_screens(frame,[self.goods]) == ['shop_goods']:
                stable=stable+1 if candidate=='goods' else 1; candidate='goods'
                if stable>=2: return hwnd
            elif matching_screens(frame,[self.shop_open]) == ['shop_open']:
                stable=stable+1 if candidate=='shop' else 1; candidate='shop'
                if stable>=2:
                    self._check_cancel()
                    self._backend.click(hwnd,215,277,False)
                    return self._flow(hwnd,'shop_goods',[self.goods],timeout=30)
            else:
                candidate,stable=None,0
            self._pause(min(.3,max(0,deadline-self._clock())))
        raise MacroError('Loja indisponivel; coleta pendente.')

    def _record(self,progress,source):
        if not self.store:
            return
        old=self.store.snapshot().get('tasks',{}).get(TASK,{})
        if old.get('progress',0)>progress:
            raise MacroError('Contadores da loja menores que o progresso salvo; nenhuma coleta autorizada.')
        if old.get('progress')==progress and not old.get('last_error'):
            return
        self.store.mark_progress(TASK,progress,20,label='free_item_shop',source=source,
            expected_cycle=self.cycle)

    def _ad_ready(self,frame,kind):
        profile=self.data['ad_buttons'][kind]
        screen={'name':'ad_'+kind,'anchors':profile['anchors']}
        matches=matching_screens(frame,[screen])
        return matches==['ad_'+kind]

    def _claim_once(self,hwnd,kind,counts,frame,timeout=120):
        before,frame=self._observe(hwnd)
        if before!=counts or not self._ad_ready(frame,kind):
            raise MacroError('Loja mudou antes do anuncio; coleta pendente.')
        used,total=counts[kind]
        if not any(s['used']==used+1 and s['total']==total for s in self.data['counter_templates']):
            raise MacroError('Loja: contador desconhecido; coleta pendente.')
        self._check_cancel()
        click=self.data['ad_buttons'][kind]['click']
        self._backend.click(hwnd,click['x'],click['y'],False)
        after,frame=self._wait_for_increment(hwnd,before,kind,timeout=timeout)
        return hwnd,after,frame

    def _wait_for_increment(self,hwnd,before,kind,timeout=120):
        """Wait for Goods to show the exact reward increment after one ad click."""
        deadline=self._clock()+timeout
        expected=(before[kind][0]+1,before[kind][1])
        previous,stable,last_error=None,0,''
        while self._clock()<deadline:
            self._check_cancel()
            frame=self._backend.capture(hwnd); self._last_frame=frame
            if self._backend.client_size(hwnd)!=(434,810):
                raise MacroError('Geometria da loja mudou; nenhuma coleta autorizada.')
            # Ads and transitions can obscure the panel. Only a recognized Goods
            # frame is evidence about the counters; generic Shop anchors overlap.
            if matching_screens(frame,[self.claim_toast]) == ['claim_toast']:
                previous,stable=None,0
                last_error='Mensagem de recompensa ainda visivel; aguardando contador limpo.'
            elif matching_screens(frame,[self.goods]) != ['shop_goods']:
                previous,stable=None,0
                last_error='Painel Goods desconhecido; coleta pendente.'
            else:
                try:
                    observed=read_counters(frame,self.data)
                except MacroError as exc:
                    previous,stable=None,0
                    last_error=str(exc)
                else:
                    if observed==before:
                        previous,stable=observed,0
                    else:
                        _validate_increment(before,observed,kind)
                        stable=stable+1 if observed==previous else 1
                        previous=observed
                        if stable>=2:
                            return observed,frame
            self._pause(min(.3,max(0,deadline-self._clock())))
        raise MacroError(last_error or 'Loja: incremento do anuncio nao confirmado; coleta pendente.')

    def _do_screen_flow(self,step,hwnd):
        if not step.get('free_item_shop'):
            return super()._do_screen_flow(step,hwnd)
        from .home import home_step
        hwnd=super()._do_screen_flow(home_step(),hwnd)
        # Open Shop only from the recognized main page. The general Shop
        # surface is separately calibrated before selecting Goods.
        main=next(s for s in home_step()['screens'] if s['name']=='main')
        entry=copy.deepcopy(main); entry.update(click={'x':404,'y':784})
        hwnd=self._flow(hwnd,'shop_open',[entry,self.shop_open])
        hwnd=self._ensure_goods(hwnd)
        counts,frame=self._observe(hwnd)
        progress=sum(value[0] for value in counts.values())
        self._record(progress,'visual')
        acquired=0
        while progress < 20 and acquired < 20:
            self._check_cancel()
            selected=None
            for kind in ('diamonds','emeralds'):
                used,total=counts[kind]
                if used < total:
                    selected=kind; break
            if selected is None:
                break
            used,total=counts[selected]
            # Never click unless both the exact expected result and the free
            # ad button have been calibrated in the captured frame.
            if not any(s['used']==used+1 and s['total']==total
                       for s in self.data['counter_templates']):
                self.outcome=ShopOutcome(progress,acquired,True,
                    'Loja: contador desconhecido; coleta pendente.',
                    bool(self.store))
                break
            if not self._ad_ready(frame,selected):
                self.outcome=ShopOutcome(progress,acquired,True,
                    'Loja: anuncio gratuito indisponivel; coleta pendente.',
                    bool(self.store))
                break
            # One click only; exact increment validation can fail but is never retried.
            hwnd,after,frame=self._claim_once(hwnd,selected,counts,frame)
            counts=after; progress=sum(value[0] for value in counts.values())
            acquired+=1; self._record(progress,'macro')
        if self.outcome is None:
            complete=progress>=20
            self.outcome=ShopOutcome(progress,acquired,not complete,
                '' if complete else 'Loja: anuncio gratuito indisponivel; coleta pendente.',bool(self.store))
        return super()._do_screen_flow(home_step(),hwnd)


def run_shop(game):
    from .home import home_step
    store,cycle=game._status_store,None
    previous=game._runner_factory; runners=[]
    with game._exclusive():
        try:
            cycle=store.cycle_id() if store else None
            def factory(backend,title,foreground,log):
                original=previous(backend,title,foreground,log)
                if not isinstance(original,MacroRunner):
                    raise GameError('Loja exige o executor visual.')
                runner=ShopRunner(backend,title,foreground,log,sleep=original._sleep,
                    clock=original._clock,store=store,cycle=cycle)
                runners.append(runner); return runner
            game._runner_factory=factory
            game._run_steps([{'action':'wait_window','timeout':5},{'action':'prepare_window'},
                {'action':'move_resize','width':438,'height':814},dict(home_step(),free_item_shop=True),
                *game.final_steps()],'free_item_shop',game._title())
            return runners[-1].outcome
        except DailyStatusError as exc:
            raise GameError('Nao foi possivel salvar o acompanhamento da loja.') from exc
        finally:
            game._runner_factory=previous
