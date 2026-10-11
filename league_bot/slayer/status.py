"""Atomic local daily counters; rollover never runs game actions."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

BR_TZ = timezone(timedelta(hours=-3), "America/Sao_Paulo")
PRESETS = {
    "attendance": ("Presença", "presence", 1),
    "summon_sword": ("Espadas", "summons", 3),
    "summon_accessory": ("Acessórios", "summons", 3),
    "summon_skill": ("Habilidades", "summons", 3),
    "mission:cubo-de-melhora": ("Cubo de melhora", "missions", 3),
    "mission:pet-da-guild": ("Pet da guild", "missions", 5),
}


class DailyStatusError(Exception):
    """Invalid or inaccessible tracking state; existing bytes are preserved."""


def _count(value, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0) or value > 10000:
        raise ValueError("Contador inválido; use um inteiro entre 0 e 10000 (meta maior que zero).")
    return value


def _task(label, group, target):
    return dict(label=label, group=group, progress=0, target=target,
                status="not_checked", updated_at=None, source=None, last_error=None)


class DailyStatusStore:
    def __init__(self, path, *, now=None):
        self.path = Path(path)
        self._now = now or (lambda: datetime.now(BR_TZ))
        self._lock = threading.RLock()

    def _time(self):
        value = self._now()
        if value.tzinfo is None:
            raise DailyStatusError("O relógio diário precisa informar o fuso horário.")
        return value.astimezone(BR_TZ)

    def _cycle(self, now):
        return (now - timedelta(hours=2)).date().isoformat()

    def _validate(self, data):
        try:
            if data["schema_version"] != 1 or not isinstance(data["tasks"], dict):
                raise ValueError()
            datetime.strptime(data["cycle_id"], "%Y-%m-%d")
            if not isinstance(data["history"], list):
                raise ValueError()
            for task_id, task in data["tasks"].items():
                if not isinstance(task_id, str) or not task_id or len(task_id) > 150:
                    raise ValueError()
                _count(task["progress"])
                _count(task["target"], positive=True)
                if task["progress"] > task["target"] or task["status"] not in {
                    "not_checked", "pending", "completed", "error"
                }:
                    raise ValueError()
                if not isinstance(task["label"], str) or not isinstance(task["group"], str):
                    raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise DailyStatusError("Arquivo de status diário inválido; os dados foram preservados.") from None

    def _read(self, now):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise DailyStatusError("Não foi possível ler o status diário; os dados foram preservados.") from None
            self._validate(data)
        else:
            data = dict(schema_version=1, cycle_id=self._cycle(now), tasks={}, history=[])
        cycle = self._cycle(now)
        if data["cycle_id"] != cycle:
            data["history"] = (data["history"] + [dict(cycle_id=data["cycle_id"],
                                                       tasks=copy.deepcopy(data["tasks"]))])[-14:]
            for key, task in data["tasks"].items():
                data["tasks"][key] = _task(task["label"], task["group"], task["target"])
            data["cycle_id"] = cycle
        for key, (label, group, target) in PRESETS.items():
            data["tasks"].setdefault(key, _task(label, group, target))
        next_day = datetime.fromisoformat(cycle).date() + timedelta(days=1)
        data["next_reset"] = datetime.combine(next_day, datetime.min.time(), BR_TZ).replace(hour=2).isoformat()
        return data

    def _save(self, data):
        tmp = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             delete=False, suffix=".tmp") as file:
                tmp = file.name
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
        except OSError:
            raise DailyStatusError("Não foi possível salvar o status diário.") from None
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def snapshot(self):
        with self._lock:
            data = self._read(self._time())
            self._save(data)
            return copy.deepcopy(data)

    def cycle_id(self):
        return self.snapshot()["cycle_id"]

    def _update(self, task_id, *, progress=None, target=None, label=None, source=None,
                error=None, expected_cycle=None):
        if not isinstance(task_id, str) or not task_id or len(task_id) > 150:
            raise ValueError("Nome de tarefa inválido.")
        with self._lock:
            now = self._time()
            data = self._read(now)
            if expected_cycle is not None and data["cycle_id"] != expected_cycle:
                self._save(data)
                return copy.deepcopy(data)
            if task_id not in data["tasks"]:
                group = "macros" if task_id.startswith("macro:") else "missions"
                data["tasks"][task_id] = _task(label or task_id.split(":")[-1], group, target or 1)
            task = data["tasks"][task_id]
            quota = _count(target if target is not None else task["target"], positive=True)
            amount = _count(progress if progress is not None else task["progress"])
            if amount > quota:
                raise ValueError("O progresso não pode exceder a meta.")
            if label is not None:
                if not isinstance(label, str) or not label.strip() or len(label) > 150:
                    raise ValueError("Nome de tarefa inválido.")
                task["label"] = label
            task.update(progress=amount, target=quota, updated_at=now.isoformat())
            if error is not None:
                task["last_error"] = str(error)[:1000]
                task["status"] = "completed" if amount == quota else "error"
            else:
                task.update(status="completed" if amount == quota else "pending",
                            source=source, last_error=None)
                if source == "macro":
                    task["last_completed_at"] = now.isoformat()
            self._save(data)
            return copy.deepcopy(data)

    def mark_progress(self, task_id, progress, target=None, *, label=None, source="manual", expected_cycle=None):
        return self._update(task_id, progress=progress, target=target, label=label,
                            source=source, expected_cycle=expected_cycle)

    def mark_error(self, task_id, error, *, expected_cycle=None):
        return self._update(task_id, error=error, expected_cycle=expected_cycle)
