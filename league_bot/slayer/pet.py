"""Visual guild-pet cleans with a fresh balance check before each paid action."""
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
        from .home import home_step
        from .cube import load_screens as cube_screens
        main = copy.deepcopy(next(s for s in home_step()["screens"] if s["name"] == "main"))
        main["click"] = dict(x=331, y=784)
        maps = [copy.deepcopy(s) for s in cube_screens() if s["name"] in {"adventure", "dungeon"}]
        for screen in maps:
            screen["click"] = dict(x=293,y=110)
        return self._flow(hwnd,"pet_open",[main,*maps,self.profiles["guild"],self.profiles["pet_open"]])

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
        return hwnd, values[0]

    def _record(self, progress):
        if self.store:
            self.store.mark_progress(TASK,progress,5,label="Pet da guild",source="visual",expected_cycle=self.cycle)

    def _do_screen_flow(self, step, hwnd):
        if not step.get("guild_pet"):
            return super()._do_screen_flow(step,hwnd)
        from .home import home_step
        hwnd = super()._do_screen_flow(home_step(),hwnd)
        hwnd = self._enter(hwnd)
        hwnd, progress = self._counter(hwnd)
        self._record(progress)
        while progress < 5:
            if progress:
                hwnd = self._exit(hwnd)
                hwnd, balance = self._balance(hwnd)
                required = remaining_cost(progress)
                if balance < required:
                    self.outcome = PetOutcome(progress,True,
                        f"Pet da guild: {progress}/5. Saldo {balance}; precisa de {required} diamantes para as limpezas restantes. Etapas pagas puladas.")
                    return hwnd
                hwnd = self._enter(hwnd)
                hwnd, observed = self._counter(hwnd)
                if observed != progress:
                    raise MacroError("O contador do pet mudou durante a conferencia; nenhum novo gasto realizado.")
            clean = copy.deepcopy(self.profiles[f"pet_{progress}"])
            clean["click"] = dict(x=216,y=651)
            # One clean, one reward confirmation; a return to the same counter
            # never repeats the purchase. Only the next counter proves success.
            hwnd = self._flow(hwnd,f"pet_{progress+1}",
                              [clean,self.profiles["reward"],self.profiles[f"pet_{progress+1}"]])
            progress += 1
            self._record(progress)
        self.outcome = PetOutcome(progress)
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
