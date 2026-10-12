"""Recognized free-entry cube flow; never clicks an entrance priced in feathers."""
import copy
import json
from pathlib import Path

from .status import DailyStatusError
from league_bot.game import GameError
from league_bot.macro import MacroCancelled, MacroError, MacroRunner

MACRO = "cubo_de_melhora"
TASK = "mission:cubo-de-melhora"


class CubeRunner(MacroRunner):
    """Retry an ignored multiplier click once; never repeat Enter."""

    def _do_screen_flow(self, step, hwnd):
        if step["terminal"] != "rift_exhausted":
            return super()._do_screen_flow(step, hwnd)
        started = self._clock()
        first = dict(step, timeout=min(12, step["timeout"]))
        try:
            return super()._do_screen_flow(first, hwnd)
        except MacroCancelled:
            raise
        except MacroError as exc:
            message = str(exc)
            if not message.startswith("screen flow timed out;"):
                raise
            retry = message.endswith("last screen: multiplier; last click: multiplier")
            screens = copy.deepcopy([s for s in step["screens"] if s["name"] != "rift_free"])
            if not retry:
                for screen in screens:
                    screen.pop("click", None)
            # Capture/match the modal again before a single retry. Loading frames
            # receive no input. Original deadline and cancellation are preserved.
            remaining = step["timeout"] - (self._clock() - started)
            self._log("cube multiplier retry" if retry else "cube waiting for return without clicks")
            return super()._do_screen_flow(dict(step, screens=screens, timeout=max(.01,remaining)), hwnd)


def load_screens():
    return json.loads((Path(__file__).resolve().parent / "assets/cube.json").read_text(encoding="utf-8"))


def cube_steps():
    from .home import home_step
    screens = {s["name"]: s for s in load_screens()}
    from .dungeon_navigation import dungeon_entry_step
    dungeon_nav = dungeon_entry_step()
    main = copy.deepcopy(next(s for s in home_step()['screens'] if s['name']=='main'))
    main["click"] = {"x": 331, "y": 784}
    main["max_clicks"] = 1
    # Title-only entry observation. Check the counter in a separate flow before Enter.
    rift = copy.deepcopy(screens["rift_free"])
    rift.update(name="rift_open", anchors=rift["anchors"][:14])
    rift.pop("click", None)
    flow = dict(action="screen_flow", poll_seconds=.3, stable_frames=2, frame_size=[434,810])
    back = copy.deepcopy(screens["rift_exhausted"])
    back["click"] = {"x":45,"y":775}
    dungeon = copy.deepcopy(next(s for s in dungeon_nav['screens'] if s['name']=='dungeon_ready'))
    dungeon["click"] = {"x":325,"y":784}
    main.pop('click', None)
    return [
        {"action":"wait_window","timeout":5}, {"action":"prepare_window"},
        {"action":"move_resize","width":438,"height":814},
        home_step(),
        dungeon_nav,
        dict(flow,timeout=40,terminal="rift_open",screens=[dict(copy.deepcopy(dungeon),click=screens['dungeon']['click']),rift]),
        dict(flow,timeout=360,terminal="rift_exhausted",screens=[screens["rift_free"],screens["multiplier"],screens["rift_exhausted"]]),
        dict(flow,timeout=40,terminal="main",screens=[back,dungeon,main]),
        {"action":"move_resize","width":438,"height":814},
        {"action":"minimize"},
    ]


def run_cube(game):
    store = game._status_store
    cycle = None
    entered = False
    previous_log = game._log
    def observe(message):
        nonlocal entered
        if message.startswith("screen 'rift_free' clicked"):
            entered = True
        if message == "screen flow complete: rift_exhausted" and store:
            # A feather-priced entrance replaces the (0/3) free-entry counter.
            # This records consumed chances, not victory or a reward amount.
            store.mark_progress(TASK, 3, 3, source="visual", expected_cycle=cycle)
        previous_log(message)

    with game._exclusive():
        previous_factory = game._runner_factory
        def factory(backend, title, foreground, log):
            original = previous_factory(backend, title, foreground, log)
            if not isinstance(original, MacroRunner):
                return original
            return CubeRunner(backend, title, foreground, log,
                              sleep=original._sleep, clock=original._clock)
        try:
            cycle = store.cycle_id() if store else None
            game._log = observe
            game._runner_factory = factory
            game._run_steps(cube_steps()[:-2] + game.final_steps(), MACRO, game._title())
        except MacroCancelled:
            raise
        except (MacroError, GameError) as exc:
            if store:
                try:
                    store.mark_error(TASK, str(exc), expected_cycle=cycle)
                except DailyStatusError:
                    previous_log("Nao foi possivel registrar o erro dos cubos.")
            raise
        except DailyStatusError as exc:
            raise GameError("Nao foi possivel salvar o acompanhamento dos cubos.") from exc
        finally:
            game._log = previous_log
            game._runner_factory = previous_factory
    if entered:
        return "Cubo de melhora: fluxo 3x concluido; entradas gratuitas esgotadas (3/3)."
    return "Cubo de melhora: entradas gratuitas ja esgotadas hoje (3/3); nenhum combate iniciado."
