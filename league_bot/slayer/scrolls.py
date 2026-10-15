"""Daily blessings from observed quotas, with one click per confirmed increment."""
import copy
import json
from pathlib import Path

from league_bot.game import GameError
from league_bot.macro import MacroCancelled, MacroError, MacroRunner
from league_bot.screens import matching_screens


def profiles():
    return json.loads((Path(__file__).parent / "assets/scrolls.json").read_text(encoding="utf-8"))


def recovery_screens():
    data = profiles()
    screen = copy.deepcopy(data["screen"])
    screen.update(name="home_close_scrolls", click=data["close"], max_clicks=1)
    return [screen]


def read_counts(frame, data=None):
    """Return four exact USED limits. An unfamiliar raster authorizes no click."""
    data = data or profiles()
    if frame is None or (frame.width, frame.height) != tuple(data["frame_size"]):
        return None
    if matching_screens(frame, [data["screen"]]) != ["scrolls_panel"]:
        return None
    result = []
    for left, top, right, bottom in data["counter_boxes"]:
        points = set()
        for y in range(top, bottom):
            for x in range(left, right):
                color = frame.pixel(x, y)
                if min(color) >= 180 and max(color) - min(color) <= 65:
                    points.add((x, y))
        if not points:
            return None
        x0, x1 = min(x for x, y in points), max(x for x, y in points)
        y0, y1 = min(y for x, y in points), max(y for x, y in points)
        mask = ["".join("1" if (x, y) in points else "0" for x in range(x0, x1 + 1))
                for y in range(y0, y1 + 1)]
        matches = {sample["used"] for sample in data["counter_templates"]
                   if sample["total"] == 2 and sample["mask"] == mask}
        if len(matches) != 1:
            return None
        result.append(next(iter(matches)))
    return tuple(result)


class ScrollRunner(MacroRunner):
    def __init__(self, *args, store=None, cycle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.data = profiles()
        self.store, self.cycle = store, cycle

    def _check_cancel(self):
        super()._check_cancel()
        if self.store and self.store.cycle_id() != self.cycle:
            raise MacroCancelled("O ciclo diario mudou durante a ativacao dos scrolls.")

    def _counts(self, hwnd, expected=None, timeout=8):
        from .home import home_step
        main = home_step()
        if self.screen_transform:
            main = self.screen_transform(main)
        main = next(s for s in main["screens"] if s["name"] == "main")
        started, previous, stable, main_stable, reopened = self._clock(), None, 0, 0, False
        deadline = started + timeout
        while self._clock() < deadline:
            self._check_cancel()
            frame = self._backend.capture(hwnd)
            self._last_frame = frame
            if self._backend.client_size(hwnd) != (434, 810):
                raise MacroError("Geometria dos scrolls mudou; nenhuma nova ativacao autorizada.")
            current = read_counts(frame, self.data)
            if current is not None:
                if expected is not None and any(a > b for a, b in zip(current, expected)):
                    raise MacroError("Contador dos scrolls mudou inesperadamente; nao repetir clique.")
                stable = stable + 1 if current == previous else 1
                previous = current
                if stable >= 2 and (expected is None or current == expected):
                    return current
            else:
                previous, stable = None, 0
            # An ad may return to main rather than reopen Ad Items. Reopen only
            # recognized navigation once; never touch an unknown video/loading frame.
            main_stable = main_stable + 1 if matching_screens(frame, [main]) == ["main"] else 0
            if expected is not None and not reopened and main_stable >= 2 and self._clock() - started >= 3:
                self._backend.click(hwnd, 409, 175, False)
                reopened = True
            self._pause(min(.3, max(0, deadline - self._clock())))
        raise MacroError("Scrolls: contador nao confirmado apos anuncio/transicao; nao repetir ativacao.")

    def _do_screen_flow(self, step, hwnd):
        if not step.get("daily_scrolls"):
            return super()._do_screen_flow(step, hwnd)
        from .home import home_step
        hwnd = super()._do_screen_flow(home_step(), hwnd)
        main = next(s for s in home_step()["screens"] if s["name"] == "main")
        main.update(click={"x": 409, "y": 175}, max_clicks=1)
        hwnd = super()._do_screen_flow(dict(action="screen_flow", terminal="scrolls_panel",
            screens=[main, self.data["screen"]], frame_size=[434,810],
            timeout=20, poll_seconds=.3, stable_frames=2), hwnd)
        counts = self._counts(hwnd)
        for index in range(4):
            for _ in range(2 - counts[index]):
                # Re-observe before each claim. Never retry it after a timeout.
                before = self._counts(hwnd)
                if before != counts:
                    raise MacroError("Scrolls mudaram antes do clique; nenhuma ativacao repetida.")
                self._check_cancel()
                self._backend.click(hwnd, *self.data["clicks"][index], False)
                expected = list(counts)
                expected[index] += 1
                counts = self._counts(hwnd, tuple(expected), timeout=120)
                self._log(f"Scroll {index + 1}: {counts[index]}/2 confirmado visualmente.")
        return super()._do_screen_flow(home_step(), hwnd)


def run_scrolls(game):
    from .home import home_step
    previous, store = game._runner_factory, game._status_store
    with game._exclusive():
        try:
            cycle = store.cycle_id() if store else None
            def factory(backend, title, foreground, log):
                original = previous(backend, title, foreground, log)
                if not isinstance(original, MacroRunner):
                    raise GameError("Scrolls exigem o executor visual.")
                return ScrollRunner(backend, title, foreground, log, sleep=original._sleep,
                                    clock=original._clock, store=store, cycle=cycle)
            game._runner_factory = factory
            steps = [{"action": "wait_window", "timeout": 5}, {"action": "prepare_window"},
                     {"action": "move_resize", "width": 438, "height": 814},
                     dict(home_step(), daily_scrolls=True), *game.final_steps()]
            game._run_steps(steps, "ativar_scrolls", game._title())
        finally:
            game._runner_factory = previous
    return "Scrolls: quatro limites 2/2 confirmados visualmente."
