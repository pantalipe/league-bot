"""Shared Slayer game flows; host input guard, status and placement are injected."""
import copy
import logging
from league_bot.game import SlayerGame, GameError
from league_bot.macro import MacroCancelled, MacroError
from .status import DailyStatusError
from .navigation import load_daily_navigation, load_attendance_screens
logger = logging.getLogger(__name__)

class SlayerDailyGame(SlayerGame):
    """Recognize attendance and daily flows with caller-owned state/placement."""

    def __init__(self, *args, status_store=None, final_position=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._status_store = status_store
        self._final_position = final_position
        from .api import open_library
        self._library = open_library(self._settings)

    def run_macro(self, name):
        if name == "pet_guild":
            from .pet import run_pet
            return run_pet(self)
        if name == "cubo_de_melhora":
            from .cube import run_cube
            return run_cube(self)
        return super().run_macro(name)

    def _run_observed_steps(self, steps, name, title):
        previous_log = self._log
        claimed = False
        try:
            cycle = self._status_store.cycle_id() if self._status_store else None
        except DailyStatusError as exc:
            raise GameError("Nao foi possivel ler o acompanhamento diario.") from exc

        def observe(message):
            nonlocal claimed
            if message.startswith("screen 'attendance_claim_ready' clicked"):
                claimed = True
            if self._status_store and (message.startswith("screen 'attendance_claimed' clicked")
                                      or message.startswith("screen 'attendance_claimed_settings' clicked")):
                # The disabled Claim state was seen twice before this click.
                self._status_store.mark_progress("attendance", 1, source="visual", expected_cycle=cycle)
            previous_log(message)

        self._log = observe
        try:
            self._run_steps(steps, name, title)
        except DailyStatusError as exc:
            raise GameError("Nao foi possivel salvar o acompanhamento da presenca.") from exc
        except MacroCancelled:
            raise
        except MacroError as exc:
            if self._status_store:
                try:
                    self._status_store.mark_error("attendance", str(exc), expected_cycle=cycle)
                except DailyStatusError:
                    logger.exception("Falha ao registrar erro de presenca")
            raise
        finally:
            self._log = previous_log
        return claimed

    def start(self):
        if self._settings.start_macro != "start_game_recognized":
            return super().start()
        title = self._title()
        steps = self.load_macro_steps(self._settings.start_macro)
        with self._exclusive():
            if self._backend.find_window(title) is None:
                self._log("launching Slayer Legend")
                self._launcher(self._settings)
            else:
                self._log("resuming Slayer Legend startup on existing window")
            self._last_start_claimed = self._run_observed_steps(steps, self._settings.start_macro, title)
        return "Slayer Legend pronto; inicio concluido (presenca tratada quando exibida)."

    def check_attendance(self):
        from .home import home_step
        title = self._title()
        startup = self.load_macro_steps("start_game_recognized")
        main = copy.deepcopy(next(screen for step in startup if step["action"] == "screen_flow"
                                  for screen in step["screens"] if screen["name"] == "main"))
        nav = load_daily_navigation()
        main["anchors"].extend(nav["main_closed_anchors"])
        enter_main = copy.deepcopy(main)
        enter_main["click"] = {"x": 408, "y": 59}
        enter_main["max_clicks"] = 1
        flow = {"action": "screen_flow", "timeout": 40, "poll_seconds": .2,
                "stable_frames": 2, "frame_size": [434, 810]}
        enter = dict(flow, terminal="attendance_open", screens=[enter_main, nav["menu_open"],
                     nav["settings_open"], nav["attendance_open"]])
        finish = dict(flow, terminal="main", screens=[main, *load_attendance_screens(),
                      nav["attendance_claimed_settings"], nav["settings_return"], nav["menu_return"]])
        steps = [{"action": "wait_window", "timeout": 5}, {"action": "prepare_window"},
                 {"action": "move_resize", "width": 438, "height": 814}, home_step(), enter, finish,
                 *self.final_steps()]
        with self._exclusive():
            claimed_at_start = getattr(self, "_last_start_claimed", False)
            claimed = self._run_observed_steps(steps, "attendance_check", title)
            self._last_start_claimed = False
        return "claimed" if claimed or claimed_at_start else "already_claimed"

    def load_macro_steps(self, name):
        steps = super().load_macro_steps(name)
        from .plan import MACRO_CATALOG
        if name in MACRO_CATALOG and name != "cubo_de_melhora":
            from .home import home_step
            steps = copy.deepcopy(steps)
            # Recorded pixel guards and waits remain intact. Recover main
            # before each recording and confirm navigation back afterward.
            steps = [{"action": "wait_window", "timeout": 5},
                     {"action": "prepare_window"},
                     {"action": "move_resize", "width": 438, "height": 814},
                     home_step(), *steps, home_step(),
                     *self.final_steps()]
        if name == "start_game_recognized" and steps and steps[-1]["action"] == "minimize":
            attendance = load_attendance_screens()
            nav = load_daily_navigation()
            attendance += [nav["attendance_claimed_settings"], nav["settings_return"]]
            steps = copy.deepcopy(steps)
            flows = [step for step in steps if step["action"] == "screen_flow" and step.get("terminal") == "main"]
            if len(flows) != 1:
                raise GameError("Macro de inicio sem um unico reconhecimento da tela principal.")
            flow = flows[0]
            from .home import home_step
            recovery = home_step()["screens"]
            # Startup retains its attendance claim flow; recovery only adds
            # navigation actions and a main profile without account/XP pixels.
            stable_main = next(s for s in recovery if s["name"] == "main")
            flow["screens"] = [stable_main if s["name"] == "main" else s for s in flow["screens"]]
            attendance += [s for s in recovery if s["name"] != "main" and not s["name"].startswith("home_close_attendance")]
            names = {screen["name"] for screen in flow["screens"]}
            for screen in attendance:
                if screen["name"] not in names:
                    flow["screens"].append(screen)
                    names.add(screen["name"])
            # Place only after screen_flow succeeds, while still inside the
            # library's exclusive/cancellable run, before final minimization.
            steps = steps[:-1] + self.final_steps()
        return steps

    def final_steps(self):
        placement = {"action": "move_resize", "width": 438, "height": 814}
        if self._final_position is not None:
            placement.update(x=self._final_position[0], y=self._final_position[1])
        return [placement, {"action": "minimize"}]
