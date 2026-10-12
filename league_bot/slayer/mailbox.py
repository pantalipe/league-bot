"""Recognized, fail-closed collection for the Slayer Mailbox."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

from league_bot.game import GameError
from league_bot.macro import MacroCancelled, MacroError, MacroRunner
from league_bot.screens import matching_screens
from .status import DailyStatusError

TASK = "macro:mailbox"


def load_profiles():
    return json.loads((Path(__file__).resolve().parent / "assets/mailbox.json").read_text(encoding="utf-8"))


def recovery_screens():
    """Close the panel only after its fixed Mailbox frame has been recognized."""
    data = load_profiles()
    screen = copy.deepcopy(next(s for s in data["screens"] if s["name"] == "mailbox_panel"))
    screen.update(name="home_close_mailbox", click=dict(data["close"]))
    return [screen]


@dataclass(frozen=True)
class MailboxOutcome:
    progress: int = 1
    empty: bool = False
    reason: str = ""

    def __str__(self):
        return self.reason or ("Mailbox vazio; nenhuma coleta pendente." if self.empty else "Mailbox: recompensas coletadas.")


class MailboxRunner(MacroRunner):
    def __init__(self, *args, store=None, cycle=None, claim_steps=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.cycle = store, cycle
        self.claim_steps = copy.deepcopy(claim_steps)
        self.data = load_profiles()
        self.screens = {s["name"]: s for s in self.data["screens"]}
        self.outcome = None

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id() != self.cycle:
            raise MacroCancelled("O ciclo diario mudou durante a coleta do Mailbox.")

    def _flow(self, hwnd, terminal, screens, timeout=40):
        step = dict(action="screen_flow", terminal=terminal, screens=screens,
                    timeout=timeout, poll_seconds=.3, stable_frames=2,
                    frame_size=[434, 810])
        return super()._do_screen_flow(step, hwnd)

    def _observe_state(self, hwnd, timeout=10):
        deadline = self._clock() + timeout
        candidates = [self.screens["mailbox_populated"], self.screens["mailbox_empty"]]
        previous = None
        stable = 0
        last_error = "Mailbox desconhecido; nenhuma recompensa acionada."
        while self._clock() < deadline:
            self._check_cancel()
            frame = self._backend.capture(hwnd)
            self._last_frame = frame
            if self._backend.client_size(hwnd) != (434, 810):
                raise MacroError("Geometria do Mailbox mudou; nenhuma recompensa acionada.")
            # The common title/frame must also match. State profiles include the
            # same anchors, but this separate check prevents partial UI matches.
            panel = self.screens["mailbox_panel"]
            if matching_screens(frame, [panel]) != ["mailbox_panel"]:
                name = None
            else:
                matches = matching_screens(frame, candidates)
                name = matches[0] if len(matches) == 1 else None
            if name is None:
                previous, stable = None, 0
            else:
                stable = stable + 1 if name == previous else 1
                previous = name
                if stable >= 2:
                    return hwnd, name
            self._pause(min(.3, max(0, deadline - self._clock())))
        raise MacroError(last_error)

    def _record(self):
        if self.store:
            self.store.mark_progress(TASK, 1, 1, label="Mailbox", source="visual",
                                     expected_cycle=self.cycle)

    def _do_screen_flow(self, step, hwnd):
        if not step.get("mailbox_collection"):
            return super()._do_screen_flow(step, hwnd)
        from .home import home_step
        recovery = home_step()
        hwnd = super()._do_screen_flow(recovery, hwnd)
        main = copy.deepcopy(next(s for s in recovery["screens"] if s["name"] == "main"))
        main.update(click={"x": 408, "y": 60}, max_clicks=2, retry_after_seconds=3)
        from .navigation import load_daily_navigation
        menu = copy.deepcopy(load_daily_navigation()["menu_open"])
        menu.update(click={"x": 377, "y": 90}, max_clicks=2, retry_after_seconds=3)
        hwnd = self._flow(hwnd, "mailbox_panel", [main, menu, self.screens["mailbox_panel"]])
        hwnd, state = self._observe_state(hwnd)
        if state == "mailbox_empty":
            close = copy.deepcopy(self.screens["mailbox_panel"])
            close.update(name="mailbox_close_empty", click=dict(self.data["close"]))
            exits = [s for s in recovery["screens"] if s["name"] != "home_close_mailbox"]
            hwnd = self._flow(hwnd, "main", [close, *exits])
            self.outcome = MailboxOutcome(empty=True)
        else:
            # The recorded suffix contains only the two claim/reward flows and
            # recorded exits. Execute it once as-is; never retry a claim.
            if not self.claim_steps:
                raise MacroError("Passos originais de recompensa do Mailbox ausentes.")
            super().run(self.claim_steps, "mailbox_claims")
            self.outcome = MailboxOutcome()
        self._record()
        return hwnd


def _stock_entry_prefix(steps):
    """Recognize only the shipped menu-entry prefix before adding empty handling."""
    if not isinstance(steps, list) or len(steps) < 8:
        return False
    stock_path = Path(__file__).resolve().parent / "macros" / "mailbox.json"
    stock = json.loads(stock_path.read_text(encoding="utf-8"))["steps"]
    # Exact entry and first guard signature. Any personalized navigation or
    # reward guard falls back to the untouched recorder path; a personalized
    # suffix after this point remains the exact suffix executed when populated.
    return len(stock) >= 8 and steps[:8] == stock[:8]


def run_mailbox(game):
    store = game._status_store
    previous = game._runner_factory
    runners = []
    try:
        cycle = store.cycle_id() if store else None
        steps = game._library.load_steps("mailbox")
        if not _stock_entry_prefix(steps):
            # A personalized macro keeps full recorder behavior and its own
            # actions. Do not infer empty-state handling from a custom prefix.
            with game._exclusive():
                game._run_steps(game.load_macro_steps("mailbox"), "mailbox", game._title())
            return None
        def factory(backend, title, foreground, log):
            original = previous(backend, title, foreground, log)
            if not isinstance(original, MacroRunner):
                raise GameError("Mailbox exige o executor visual.")
            runner = MailboxRunner(backend, title, foreground, log,
                sleep=original._sleep, clock=original._clock, store=store,
                cycle=cycle, claim_steps=steps[7:])
            runners.append(runner)
            return runner
        with game._exclusive():
            game._runner_factory = factory
            # _do_screen_flow owns the recognized entry and only then decides
            # whether the exact recorded reward suffix should run.
            from .home import home_step
            marker = copy.deepcopy(home_step())
            marker["mailbox_collection"] = True
            game._run_steps([{"action": "wait_window", "timeout": 5}, {"action": "prepare_window"},
                {"action": "move_resize", "width": 438, "height": 814}, marker,
                *game.final_steps()], "mailbox", game._title())
        return runners[-1].outcome
    except (MacroError, GameError) as exc:
        if store:
            store.mark_error(TASK, str(exc), expected_cycle=cycle)
        raise
    except DailyStatusError as exc:
        raise GameError("Nao foi possivel salvar o acompanhamento do Mailbox.") from exc
    finally:
        game._runner_factory = previous
