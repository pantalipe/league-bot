"""Visual guild-pet cleans with one budget check before the clean sequence."""
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
    return json.loads((Path(__file__).resolve().parent / "assets/pet.json").read_text(encoding="utf-8"))


def remaining_cost(progress):
    return sum(100 * n for n in range(max(1, progress), 5))


class PetRunner(MacroRunner):
    def __init__(self, *args, store=None, cycle=None, balance_reader=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.cycle = store, cycle
        if balance_reader is None:
            from .diamonds import read_diamonds
            balance_reader = read_diamonds
        self.balance_reader = balance_reader
        self.outcome = None
        self.profiles = {s["name"]: s for s in load_screens()}

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id() != self.cycle:
            raise MacroCancelled("O ciclo diario mudou durante o pet da guild.")

    def _flow(self, hwnd, terminal, screens):
        return super()._do_screen_flow(dict(action="screen_flow", terminal=terminal,
            screens=screens, timeout=40, poll_seconds=.3, stable_frames=2, frame_size=[434,810]), hwnd)

    def _enter(self, hwnd):
        from .guild_navigation import guild_entry_step
        entry = guild_entry_step()
        hwnd = self._flow(hwnd, entry["terminal"], entry["screens"])
        guild = copy.deepcopy(self.profiles["guild"])
        # Opening the Pet tab is navigation only. Retry once if the recognized
        # Guild screen remains after the first click; never apply this policy
        # to the clean/reward controls below.
        guild.update(click=dict(x=181, y=773), max_clicks=2, retry_after_seconds=3)
        return self._flow(hwnd, "pet_open", [guild, self.profiles["pet_open"]])

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
        matches = matching_screens(self._last_frame,candidates)
        if len(matches) != 1:
            raise MacroError("Contador ou custo do pet da guild desconhecido; nenhum gasto autorizado.")
        name = matches[0]
        hwnd = self._flow(hwnd,name,[self.profiles[name]])
        return hwnd, int(name[-1])

    def _balance(self, hwnd):
        from .home import home_step
        main = next(s for s in home_step()["screens"] if s["name"] == "main")
        values = []
        for _ in range(2):
            hwnd = self._flow(hwnd,"main",[main])
            values.append(self.balance_reader(self._last_frame))
            self._check_cancel()
        if values[0] != values[1]:
            raise MacroError("Saldo de diamantes instavel; nenhum gasto realizado.")
        if type(values[0]) is not int or values[0] < 0:
            raise MacroError("Saldo de diamantes desconhecido; nenhum gasto autorizado.")
        return hwnd, values[0]

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
        reward = self.profiles["reward"]
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
                matches = matching_screens(frame, [*counters, reward])
            else:
                matches = []
            if len(matches) > 1:
                raise MacroError("Contador ou recompensa final ambiguos; nenhuma acao adicional autorizada.")
            current = matches[0] if matches else None
            last_seen = current or "unknown"
            stable = stable + 1 if current is not None and current == candidate else (1 if current else 0)
            candidate = current
            if current == reward["name"] and stable >= 2:
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
            elif current and current.startswith("pet_") and current[4:].isdigit() and stable >= 2:
                progress = int(current[4:])
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
        balance_error = None
        try:
            # One stable main-screen balance check authorizes the whole
            # remaining sequence. No navigation occurs between paid cleans.
            hwnd, balance = self._balance(hwnd)
        except MacroCancelled:
            raise
        except MacroError as exc:
            balance_error, balance = exc, None
        hwnd = self._enter(hwnd)
        hwnd, progress = self._counter(hwnd)
        self._record(progress)

        if progress == 5:
            self.outcome = PetOutcome(progress)
            return self._exit(hwnd)

        initial_progress = progress
        required = remaining_cost(initial_progress)
        if balance_error is not None:
            if progress == 0:
                # The free action is safe at a recognized zero counter. Batch
                # only that clean, then verify its actual result before failing.
                hwnd, _ = self._clean_batch(hwnd, progress, 1, confirm_rewards=False)
                hwnd, observed = self._final_progress(hwnd, starting_progress=progress,
                                                      max_progress=1)
                if observed < progress:
                    raise MacroError("Contador final do pet diminuiu; progresso nao confirmado.")
                self._record(observed)
                hwnd = self._exit(hwnd)
            else:
                hwnd = self._exit(hwnd)
            raise balance_error

        if balance < required:
            count = 1 if progress == 0 else 0
            hwnd, attempted = self._clean_batch(hwnd, progress, count, confirm_rewards=False)
            hwnd, observed = self._final_progress(hwnd, starting_progress=progress,
                                                  max_progress=progress + attempted)
            self._record(observed)
            reason = (f"Pet da guild: {observed}/5. Saldo {balance}; precisa de {required} "
                      "diamantes para as limpezas restantes. Etapas pagas puladas.")
            self.outcome = PetOutcome(observed,True,reason)
            return self._exit(hwnd)

        # If a burst confirms some progress but not all of it, a bounded
        # follow-up burst may use the initial full-budget authorization. A
        # burst that makes no progress ends the run without replaying clicks.
        for _ in range(5):
            count = 5 - progress
            if count <= 0:
                break
            hwnd, attempted = self._clean_batch(hwnd, progress, count)
            hwnd, observed = self._final_progress(hwnd, starting_progress=progress,
                                                  max_progress=progress + attempted)
            self._record(observed)
            if observed == 5:
                progress = observed
                break
            if observed <= progress:
                progress = observed
                break
            progress = observed
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
                    raise GameError("O pet exige o executor visual com conferencia de saldo.")
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
