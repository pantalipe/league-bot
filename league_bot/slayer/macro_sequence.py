"""Randomized recorded macros, with optional star-based battle completion.

This module intentionally does not recognize screens or claim that a recorded
task succeeded in the game. Completion means only that its macro returned.
"""
from __future__ import annotations

import copy
import json
import math
import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from league_bot.macro import MacroCancelled, MacroError, validate_steps
from .plan import FINISHED_DAILIES, FINISHED_DAILY_DEPENDENCIES, MACRO_CATALOG, REPEATED_MACROS

LOCAL_TZ = timezone(timedelta(hours=-3), "America/Sao_Paulo")
BLOCKED = frozenset({
    "cubo_de_melhora", "cave_treinoxp", "dragao_dormente",
    "floresta_circulacao", "treinador",
})
BATTLES = frozenset({"cubo_de_melhora", "cave_treinoxp"})
ACTIVATIONS = frozenset({"ativar_scrolls", "montar_besta"})
FINISHED_DEPENDENCIES = frozenset(FINISHED_DAILY_DEPENDENCIES)
ALLOWED_ACTIONS = frozenset({
    "wait_window", "wait", "click", "move_resize", "minimize", "prepare_window",
    "wait_for_pixel",
})


class SequenceError(ValueError):
    """The selected sequence cannot be safely preflighted or resumed."""


def _cycle(now: datetime) -> str:
    local = now.astimezone(LOCAL_TZ)
    day = local.date() - timedelta(days=1) if local.hour < 2 else local.date()
    return day.isoformat()


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds")


class MacroSequence:
    """Preflight and run a resumable non-visual macro sequence.

    ``library`` supplies ``names()`` and ``load_steps(name)``; ``runner`` supplies
    ``run(steps, name=...)`` and ``cancel()``. A cancelled MacroRunner is terminal,
    so callers should create a fresh runner before starting another sequence.
    """

    def __init__(
        self, library, runner=None, state_path="sequence-state.json", *, rng=None,
        clock: Callable[[], datetime] = lambda: datetime.now(LOCAL_TZ),
        sleep: Optional[Callable[[float], None]] = None,
        extra_delay: Tuple[float, float] = (0.15, 0.65),
        pixel_wait_seconds: float = 0.5,
        selected_names: Optional[Iterable[str]] = None,
        include_battles: bool = False,
        battle_waiter=None,
    ) -> None:
        self.library = library
        self.runner = runner
        self.include_battles = include_battles
        self.battle_waiter = battle_waiter
        self._battle_splits = {}
        self.state_path = Path(state_path)
        self.rng = rng or random.Random()
        self.clock = clock
        self.sleep = sleep
        self.extra_delay = tuple(float(v) for v in extra_delay)
        self.pixel_wait_seconds = float(pixel_wait_seconds)
        self.selected_names = None if selected_names is None else tuple(dict.fromkeys(selected_names))
        self._cancelled = threading.Event()
        if (len(self.extra_delay) != 2 or not all(math.isfinite(v) for v in self.extra_delay)
                or self.extra_delay[0] < 0
                or self.extra_delay[1] < self.extra_delay[0]):
            raise ValueError("extra_delay must be a non-negative (min, max) pair")
        if not math.isfinite(self.pixel_wait_seconds) or self.pixel_wait_seconds < 0:
            raise ValueError("pixel_wait_seconds must be non-negative")

    def cancel(self) -> None:
        self._cancelled.set()
        if self.runner is not None:
            self.runner.cancel()

    def _pause(self, seconds: float) -> None:
        if self._cancelled.is_set():
            raise MacroCancelled("sequence cancelled")
        if self.sleep is None:
            self._cancelled.wait(seconds)
        else:
            self.sleep(seconds)
        if self._cancelled.is_set():
            raise MacroCancelled("sequence cancelled")

    def _selected(self) -> List[str]:
        selected = list(self.selected_names) if self.selected_names is not None else [
            name for name in MACRO_CATALOG
            if ((name not in BLOCKED and name not in ACTIVATIONS)
                or (self.include_battles and (name in BATTLES or name in ACTIVATIONS)))
        ]
        if not selected:
            raise SequenceError("no macros selected")
        if any(not isinstance(name, str) for name in selected):
            raise SequenceError("macro names must be strings")
        invalid = set(selected) & (BLOCKED - BATTLES if self.include_battles else BLOCKED)
        if invalid:
            raise SequenceError("battle macros are excluded: " + ", ".join(sorted(invalid)))
        # Buff/activation recordings may only be run through an explicit selection.
        if self.selected_names is None and not self.include_battles and set(selected) & ACTIVATIONS:
            raise SequenceError("activations require explicit selection")
        if set(selected) & BATTLES and not ACTIVATIONS.issubset(selected):
            raise SequenceError("cube and XP cave require scrolls and mount")
        available = set(self.library.names())
        missing = sorted(set(selected) - available)
        if missing:
            raise SequenceError("selected macros are missing: " + ", ".join(missing))
        if FINISHED_DAILIES in selected:
            required = FINISHED_DEPENDENCIES & set(MACRO_CATALOG)
            absent = sorted(required - set(selected))
            if absent:
                raise SequenceError("finished quests require: " + ", ".join(absent))
        if "refinamento_skill_completed" in selected and "refinamento_skill" not in selected:
            raise SequenceError("refinamento_skill_completed requires refinamento_skill")
        return selected

    @staticmethod
    def _safe_steps(name: str, steps: Sequence[dict], pixel_wait_seconds: float) -> List[dict]:
        result = copy.deepcopy(list(steps))
        if not result:
            raise SequenceError(f"{name}: macro is empty")
        for index, step in enumerate(result, 1):
            action = step.get("action") if isinstance(step, dict) else None
            if action == "click_if_pixel":
                raise SequenceError(f"{name} step {index}: conditional click is ambiguous without vision")
            if action == "screen_flow":
                raise SequenceError(f"{name} step {index}: screen flows require visual recognition")
            if action not in ALLOWED_ACTIONS:
                raise SequenceError(f"{name} step {index}: unsupported action {action!r}")
            if action == "wait_for_pixel":
                step.clear()
                step.update({"action": "wait", "seconds": pixel_wait_seconds})
        validate_steps(result)
        return result

    def preflight(self) -> Dict[str, List[dict]]:
        """Load and validate every selected recording before the first input."""
        prepared = {}
        self._battle_splits = {}
        for name in self._selected():
            try:
                raw = self.library.load_steps(name)
                prepared[name] = self._safe_steps(name, raw, self.pixel_wait_seconds)
                if name in BATTLES:
                    pauses = [i for i, step in enumerate(raw)
                              if step.get("action") == "wait" and step.get("seconds", 0) >= 120]
                    if (len(pauses) != 1 or pauses[0] == 0 or pauses[0] == len(raw)-1
                            or raw[pauses[0]-1].get("action") != "click"):
                        raise SequenceError("battle recording must have one long wait immediately after entry")
                    self._battle_splits[name] = pauses[0]
            except (MacroError, OSError, ValueError) as exc:
                raise SequenceError(f"{name}: {exc}") from exc
        return prepared

    def _read_state(self, cycle: str) -> dict:
        if not self.state_path.exists():
            return {"version": 1, "cycle": cycle, "executions": {}, "in_progress": None}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SequenceError(f"cannot read sequence state: {exc}") from exc
        if not isinstance(state, dict) or state.get("version") != 1:
            raise SequenceError("unsupported sequence state")
        if state.get("cycle") != cycle:
            return {"version": 1, "cycle": cycle, "executions": {}, "in_progress": None}
        if not isinstance(state.get("executions"), dict):
            raise SequenceError("invalid execution state")
        return state

    def _write_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.state_path)

    def _required(self, name: str) -> Tuple[int, int]:
        return REPEATED_MACROS.get(name, (1, 0))

    def acknowledge_interruption(self) -> str:
        """Mark a manually verified interrupted macro as complete so it is not replayed."""
        state = self._read_state(_cycle(self.clock()))
        name = state.get("in_progress")
        if not name:
            raise SequenceError("there is no interrupted macro to acknowledge")
        state["executions"].setdefault(name, []).append(_stamp(self.clock()))
        state["in_progress"] = None
        self._write_state(state)
        return name

    def run(self, on_event: Optional[Callable[[str], None]] = None) -> dict:
        if self.runner is None:
            raise SequenceError("a MacroRunner is required to run the sequence")
        emit = on_event or (lambda message: None)
        prepared = self.preflight()
        if self._battle_splits and self.battle_waiter is None:
            raise SequenceError("battle star waiter is required before any macro can run")
        state = self._read_state(_cycle(self.clock()))
        if state.get("in_progress"):
            raise SequenceError(
                f"macro {state['in_progress']!r} was interrupted; verify it in the game, then acknowledge it before resuming"
            )
        executions = state["executions"]
        completion: Dict[str, List[datetime]] = {}
        for name, stamps in executions.items():
            if isinstance(stamps, list):
                try:
                    completion[name] = [datetime.fromisoformat(s) for s in stamps]
                except (TypeError, ValueError):
                    raise SequenceError(f"invalid completion timestamps for {name}") from None
        names = list(prepared)
        while True:
            if self._cancelled.is_set():
                raise MacroCancelled("sequence cancelled")
            now = self.clock()
            if _cycle(now) != state["cycle"]:
                return {"cycle": state["cycle"], "executions": copy.deepcopy(executions),
                        "completed": False, "reason": "cycle_changed"}
            candidates = []
            next_due = None
            for name in names:
                count, cooldown = self._required(name)
                done = completion.get(name, [])
                if len(done) >= count:
                    continue
                if name in BATTLES and any(not completion.get(dep) for dep in ACTIVATIONS):
                    continue
                if done and cooldown:
                    due = done[-1] + timedelta(seconds=cooldown)
                    if now < due:
                        next_due = min(next_due, due) if next_due else due
                        continue
                if name == "refinamento_skill_completed":
                    starts = completion.get("refinamento_skill", [])
                    if not starts:
                        continue
                    due = starts[0] + timedelta(seconds=600)
                    if now < due:
                        next_due = min(next_due, due) if next_due else due
                        continue
                if name == FINISHED_DAILIES:
                    if any(len(completion.get(dep, [])) < self._required(dep)[0]
                           for dep in FINISHED_DEPENDENCIES if dep in names):
                        continue
                    if any(n != FINISHED_DAILIES and len(completion.get(n, [])) < self._required(n)[0]
                           for n in names):
                        continue
                candidates.append(name)
            if not candidates:
                unfinished = [n for n in names if len(completion.get(n, [])) < self._required(n)[0]]
                if not unfinished:
                    break
                if next_due is None:
                    raise SequenceError("no eligible macro can run; check dependencies")
                seconds = max(0.01, (next_due - now).total_seconds())
                emit(f"waiting {seconds:.0f}s for the next eligible macro")
                self._pause(seconds)
                continue
            name = self.rng.choice(candidates)
            emit(f"running {name}")
            # Persist intent first: after a crash, the same possibly partial clicks
            # are never replayed automatically.
            state["in_progress"] = name
            self._write_state(state)
            try:
                if name in self._battle_splits:
                    split = self._battle_splits[name]
                    self.runner.run(self._delayed(prepared[name][:split]), name=name + "_entry")
                    emit(f"Aguardando a estrela desaparecer e retornar: {name}")
                    self.battle_waiter.wait()
                    self.runner.run(self._delayed(prepared[name][split+1:]), name=name + "_exit")
                else:
                    self.runner.run(self._delayed(prepared[name]), name=name)
            except BaseException:
                self._write_state(state)
                raise
            timestamp = _stamp(self.clock())
            executions.setdefault(name, []).append(timestamp)
            completion.setdefault(name, []).append(datetime.fromisoformat(timestamp))
            state["in_progress"] = None
            self._write_state(state)
            emit(f"completed {name}")
            if _cycle(self.clock()) != state["cycle"]:
                return {"cycle": state["cycle"], "executions": copy.deepcopy(executions),
                        "completed": False, "reason": "cycle_changed"}
        return {"cycle": state["cycle"], "executions": copy.deepcopy(executions), "completed": True}

    def _delayed(self, recording):
        steps = []
        for step in copy.deepcopy(recording):
            if step.get("action") == "click" and self.extra_delay[1] > 0:
                steps.append({"action": "wait", "seconds": self.rng.uniform(*self.extra_delay)})
            steps.append(step)
        return steps
