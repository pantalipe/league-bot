"""Guild-pet clean bursts followed by visual quota confirmation."""
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from .status import DailyStatusError
from league_bot.game import GameError
from league_bot.macro import MacroCancelled, MacroError, MacroRunner
from league_bot.screens import matching_screens

TASK = "mission:pet-da-guild"


@dataclass(frozen=True)
class PetOutcome:
    progress: int
    skipped: bool = False
    reason: str = ""

    def __str__(self):
        return self.reason if self.skipped else f"Pet da guild: {self.progress}/5 limpezas confirmadas."


def load_screens():
    assets = Path(__file__).resolve().parent / 'assets'
    screens = json.loads((assets / 'pet.json').read_text(encoding='utf-8'))
    current = json.loads((assets / 'pet-current.json').read_text(encoding='utf-8'))
    screens.extend([current['panel'], current['reward']])
    left,top,right,bottom = current['counter_box']
    xs,ys = list(range(left,right,current['stride'])), list(range(top,bottom,current['stride']))
    for sample in current['counters']:
        if len(sample['rows']) != len(ys) or any(len(row) != 6*len(xs) for row in sample['rows']):
            raise ValueError('Amostra de contador do pet invalida.')
        anchors = copy.deepcopy(current['panel']['anchors'])
        for y,row in zip(ys,sample['rows']):
            for index,x in enumerate(xs):
                color = list(bytes.fromhex(row[6*index:6*(index+1)]))
                anchors.append(dict(x=x/433,y=y/809,color=color,tolerance=15,radius=0))
        screens.append(dict(name=f"pet_current_{sample['used']}", anchors=anchors))
    return screens


class PetRunner(MacroRunner):
    def __init__(self, *args, store=None, cycle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.cycle = store, cycle
        self.outcome = None
        self.profiles = {s["name"]: s for s in load_screens()}

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id() != self.cycle:
            raise MacroCancelled("O ciclo diario mudou durante o pet da guild.")

    def _flow(self, hwnd, terminal, screens):
        step = dict(action="screen_flow", terminal=terminal, screens=screens,
                    timeout=40, poll_seconds=.3, stable_frames=2, frame_size=[434,810])
        if terminal == 'pet_open' and any(s['name'] == 'pet_open_current' for s in screens):
            step['terminal_aliases'] = ['pet_open_current']
        return super()._do_screen_flow(step, hwnd)

    def _enter(self, hwnd):
        from .guild_navigation import guild_entry_step
        entry = guild_entry_step()
        hwnd = self._flow(hwnd, entry["terminal"], entry["screens"])
        guild = copy.deepcopy(self.profiles["guild"])
        # Opening the Pet tab is navigation only. Retry once if the recognized
        # Guild screen remains after the first click; never apply this policy
        # to the clean/reward controls below.
        guild.update(click=dict(x=181, y=773), max_clicks=2, retry_after_seconds=3)
        panels = [s for name,s in self.profiles.items() if name in {'pet_open','pet_open_current'}]
        return self._flow(hwnd, "pet_open", [guild, *panels])

    def _exit(self, hwnd):
        from .home import home_step
        panel = copy.deepcopy(self.profiles["pet_open"])
        panel["click"] = dict(x=217,y=746)
        guild = copy.deepcopy(self.profiles["guild"])
        guild["click"] = dict(x=52,y=777)
        recovery = [s for s in home_step()["screens"] if s["name"] not in
                    {"red_back_panel", "multiplier_back", "home_close_pet", "home_return_guild"}]
        return self._flow(hwnd,"main",[panel,guild,*recovery])

    def _counter(self, hwnd):
        candidates = [self.profiles[f"pet_{n}"] for n in range(6)]
        candidates += [s for name,s in self.profiles.items() if name.startswith('pet_current_')]
        matches = matching_screens(self._last_frame,candidates)
        if len(matches) != 1:
            raise MacroError("Contador ou custo do pet da guild desconhecido; nenhum gasto autorizado.")
        name = matches[0]
        hwnd = self._flow(hwnd,name,[self.profiles[name]])
        return hwnd, int(name[-1])

    def _record(self, progress):
        if self.store:
            self.store.mark_progress(TASK,progress,5,label="Pet da guild",source="visual",expected_cycle=self.cycle)

    def _stored_complete(self):
        snapshot = getattr(self.store, "snapshot", None)
        if not callable(snapshot):
            return False
        task = snapshot().get("tasks", {}).get(TASK, {})
        return task.get("target") == 5 and task.get("progress") == 5

    def _click_pet(self, hwnd, x, y):
        self._check_cancel()
        if hwnd is None or not self._backend.is_window(hwnd):
            hwnd = self._backend.find_window(self._title)
        if hwnd is None:
            raise MacroError("Janela do jogo indisponivel durante o lote de limpezas.")
        width, height = self._backend.client_size(hwnd)
        if (width, height) != (434, 810):
            raise MacroError("Geometria do pet mudou; nenhuma limpeza adicional autorizada.")
        if not (0 <= x < width and 0 <= y < height):
            raise MacroError("Coordenada de limpeza fora da janela.")
        self._check_cancel()
        self._backend.click(hwnd, x, y, False)
        return hwnd

    def _clean_batch(self, hwnd, progress, count, *, confirm_rewards=True):
        # Count is derived only from the recognized initial counter and remains
        # hard-capped by the known five-clean quota.
        count = min(count, 5 - progress)
        for _ in range(count):
            hwnd = self._click_pet(hwnd, 216, 651)
            if confirm_rewards:
                hwnd = self._click_pet(hwnd, 216, 660)
        return hwnd, count

    def _final_progress(self, hwnd, *, starting_progress, max_progress, timeout=40):
        """Observe a stable counter after the bounded click batch; confirm reward only if seen."""
        counters = [self.profiles[f"pet_{number}"] for number in range(6)]
        counters += [s for name,s in self.profiles.items() if name.startswith('pet_current_')]
        rewards = [s for name,s in self.profiles.items() if name in {'reward','reward_current'}]
        deadline = self._clock() + timeout
        candidate, stable = None, 0
        reward_clicks, reward_clicked_at = 0, None
        last_seen = "unknown"
        while True:
            self._check_cancel()
            if self._clock() >= deadline:
                raise MacroError(f"Pet da guild sem contador final estavel; ultimo estado: {last_seen}.")
            if hwnd is None or not self._backend.is_window(hwnd):
                hwnd = self._backend.find_window(self._title)
            frame = None
            if hwnd is not None and not self._backend.is_minimized(hwnd):
                frame = self._backend.capture(hwnd)
            if frame is not None:
                self._last_frame = frame
                if (frame.width, frame.height) != (434, 810) or self._backend.client_size(hwnd) != (434, 810):
                    raise MacroError("Geometria do pet mudou durante a confirmacao final.")
                matches = matching_screens(frame, [*counters, *rewards])
            else:
                matches = []
            if len(matches) > 1:
                raise MacroError("Contador ou recompensa final ambiguos; nenhuma acao adicional autorizada.")
            current = matches[0] if matches else None
            last_seen = current or "unknown"
            stable = stable + 1 if current is not None and current == candidate else (1 if current else 0)
            candidate = current
            if current in {s['name'] for s in rewards} and stable >= 2:
                reward = next(s for s in rewards if s['name'] == current)
                retry = reward.get("retry_after_seconds", 2.0)
                due = reward_clicked_at is None or self._clock() - reward_clicked_at >= retry
                if due:
                    if reward_clicks >= reward.get("max_clicks", 2):
                        raise MacroError("Recompensa do pet permaneceu visivel apos as confirmacoes limitadas.")
                    click = reward["click"]
                    hwnd = self._click_pet(hwnd, click["x"], click["y"])
                    reward_clicks += 1
                    reward_clicked_at = self._clock()
                    candidate, stable = None, 0
            elif current and current.startswith("pet_") and current.rsplit('_',1)[-1].isdigit() and stable >= 2:
                progress = int(current.rsplit('_',1)[-1])
                if progress < starting_progress:
                    raise MacroError("Contador final do pet diminuiu; progresso nao confirmado.")
                if progress > max_progress:
                    raise MacroError("Contador final do pet excedeu as limpezas solicitadas.")
                return hwnd, progress
            self._pause(min(.3, max(0, deadline - self._clock())))

    def _do_screen_flow(self, step, hwnd):
        if not step.get("guild_pet"):
            return super()._do_screen_flow(step,hwnd)
        from .home import home_step
        self._check_cancel()
        if self._stored_complete():
            self.outcome = PetOutcome(5)
            return hwnd
        hwnd = super()._do_screen_flow(home_step(),hwnd)
        hwnd = self._enter(hwnd)
        hwnd, progress = self._counter(hwnd)
        self._record(progress)

        if progress == 5:
            self.outcome = PetOutcome(progress)
            return self._exit(hwnd)

        # Daily cleans are authorized regardless of the readable balance.
        # Repeat click bursts in this panel, even if a burst had no effect;
        # the counter alone determines completion. Keep an operational timeout
        # so an unresponsive game does not prevent the rest of the daily.
        deadline = self._clock() + 40
        while progress < 5:
            self._check_cancel()
            if self._clock() >= deadline:
                break
            count = 5 - progress
            hwnd, attempted = self._clean_batch(hwnd, progress, count)
            hwnd, observed = self._final_progress(hwnd, starting_progress=progress,
                max_progress=progress + attempted, timeout=max(.3, deadline-self._clock()))
            self._record(observed)
            progress = observed
            if progress < 5:
                self._pause(.3)
        self.outcome = (PetOutcome(progress) if progress == 5 else
                        PetOutcome(progress,True,
                                   f"Pet da guild: {progress}/5 limpezas confirmadas; restante pendente."))
        return self._exit(hwnd)


def run_pet(game):
    from .home import home_step
    store, cycle = game._status_store, None
    previous = game._runner_factory
    runners = []
    with game._exclusive():
        try:
            cycle = store.cycle_id() if store else None
            def factory(backend,title,foreground,log):
                original = previous(backend,title,foreground,log)
                if not isinstance(original,MacroRunner):
                    raise GameError("O pet exige o executor visual com conferencia do contador.")
                runner = PetRunner(backend,title,foreground,log,sleep=original._sleep,
                                   clock=original._clock,store=store,cycle=cycle)
                runners.append(runner)
                return runner
            game._runner_factory = factory
            marker = dict(home_step(),guild_pet=True)
            game._run_steps([{"action":"wait_window","timeout":5},{"action":"prepare_window"},
                            {"action":"move_resize","width":438,"height":814},marker,
                            *game.final_steps()],"pet_guild",game._title())
            return runners[-1].outcome
        except (MacroError,GameError) as exc:
            if store:
                store.mark_error(TASK,str(exc),expected_cycle=cycle)
            raise
        except DailyStatusError as exc:
            raise GameError("Nao foi possivel salvar o acompanhamento do pet.") from exc
        finally:
            game._runner_factory = previous
