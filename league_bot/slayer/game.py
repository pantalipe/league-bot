"""Shared Slayer game flows; host input guard, status and placement are injected."""
import copy
import logging
import random
from league_bot.game import SlayerGame, GameError
from league_bot.macro import MacroCancelled, MacroError
from .status import DailyStatusError
from .navigation import load_daily_navigation, load_attendance_screens
from .pacing import ClickPacedBackend, normalize_delay_range
logger = logging.getLogger(__name__)

class SlayerDailyGame(SlayerGame):
    """Recognize attendance and daily flows with caller-owned state/placement."""

    def __init__(self, *args, status_store=None, final_position=None,
                 action_rng=None, click_delay_range=(0, 0), **kwargs):
        self._action_rng = action_rng if action_rng is not None else random.Random()
        self._click_delay_range = normalize_delay_range(click_delay_range)
        super().__init__(*args, **kwargs)
        from league_bot.geometry import wrap_backend
        self._backend = wrap_backend(self._backend, self._settings.data_dir)
        self._status_store = status_store
        self._final_position = final_position
        from .api import open_library
        self._library = open_library(self._settings)

    def _pause_before_click(self, seconds):
        runner = self._runner
        pause = getattr(runner, "_pause", None)
        if not callable(pause):
            raise GameError("Pacing de clique exige um runner visual cancelavel.")
        pause(seconds)

    def _run_steps(self, steps, name, title):
        from league_bot.screens import calibrated_matching
        cache = {}
        def profiles(screens):
            import json
            key = json.dumps(screens, sort_keys=True)
            if key not in cache:
                cache[key] = self._calibrate_screen(dict(action="screen_flow", screens=screens,
                                                        frame_size=[434, 810]))["screens"]
            return cache[key]
        with calibrated_matching(profiles):
            return self._run_calibrated_steps(steps, name, title)

    def _run_calibrated_steps(self, steps, name, title):
        from .calibration import CalibrationError, apply_overrides
        try:
            steps = [self._calibrate_screen(step) if step.get("action") == "screen_flow" else step
                     for step in steps]
        except CalibrationError as exc:
            raise GameError(f"Calibragem local invalida: {exc}") from exc
        if self._click_delay_range[1] == 0:
            return super()._run_steps(steps, name, title)
        original_backend = self._backend
        self._backend = ClickPacedBackend(original_backend, rng=self._action_rng,
            pause=self._pause_before_click, delay_range=self._click_delay_range)
        try:
            return super()._run_steps(steps, name, title)
        finally:
            self._backend = original_backend

    def _calibrate_screen(self, step):
        # Specialized runners create navigation flows during execution too.
        from .calibration import CalibrationError, apply_overrides
        try:
            from .calibration_global import transform
            return apply_overrides([transform(step, self._settings.data_dir)], self._settings.data_dir)[0]
        except ValueError as exc:
            raise MacroError(f"Calibragem local invalida: {exc}") from exc

    def _calibrate_step(self, step):
        from .calibration_global import transform
        try:
            return transform(step, self._settings.data_dir)
        except ValueError as exc:
            raise MacroError(f"Calibragem local invalida: {exc}") from exc

    def run_macro(self, name):
        if name == "ativar_scrolls":
            from .scrolls import run_scrolls
            return run_scrolls(self)
        if name == "free_wpacs":
            from .summons import run_summons
            return run_summons(self)
        if name == "mailbox":
            from .mailbox import run_mailbox
            return run_mailbox(self)
        if name == "free_item_shop":
            from .shop import run_shop
            return run_shop(self)
        if name == "blorb":
            from .orb import run_orb
            return run_orb(self)
        if name == "pet_guild":
            from .pet import run_pet
            return run_pet(self)
        if name == "cubo_de_melhora":
            from .cube import run_cube
            return run_cube(self)
        return super().run_macro(name)

    def recover_home(self):
        """Recover through recognized navigation only, never reward controls."""
        from .home import home_step
        steps = [{"action": "wait_window", "timeout": 5},
                 {"action": "prepare_window"},
                 {"action": "move_resize", "width": 438, "height": 814},
                 home_step(), *self.final_steps()]
        with self._exclusive():
            self._run_steps(steps, "daily_recovery", self._title())
        return True

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
        from .battle_navigation import prepare_battle_entry
        steps = prepare_battle_entry(name, steps)
        from .dungeon_navigation import prepare_dungeon_macro, prepare_summons
        steps = prepare_dungeon_macro(name, steps)
        if name == "free_wpacs":
            steps = prepare_summons(steps)
        if name == "loja_guild_free":
            from .guild_navigation import prepare_guild_shop
            steps = prepare_guild_shop(steps)
        if name == "collect_finished_dailys":
            from .quest_navigation import prepare_quest_collection
            steps = prepare_quest_collection(steps)
        if name == "colheita_arma_alma":
            from .equipment import prepare_soul_harvest
            steps = prepare_soul_harvest(steps)
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
