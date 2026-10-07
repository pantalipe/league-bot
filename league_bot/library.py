"""Saved macros: shared ones shipped in ``macros/`` and personal ones in ``macros/local/``.

A local macro with the same name as a shared one takes precedence, which lets
each player recalibrate a shared macro for their own machine without touching git.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .macro import Step, load_macro, validate_steps

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LibraryError(RuntimeError):
    """A macro name is invalid, missing or already taken."""


@dataclass(frozen=True)
class MacroInfo:
    name: str
    source: str  # "local" or "shared"
    path: Path
    steps: int
    description: str = ""
    tags: Tuple[str, ...] = ()
    recorded_at: str = ""
    error: str = ""


def _dump(document: Dict[str, Any]) -> str:
    """Pretty-print the metadata but keep one step per line, which is far easier to edit by hand."""
    steps = document.pop("steps")
    head = json.dumps(document, indent=2, ensure_ascii=False)  # never empty: description is always set
    body = ",\n".join("    " + json.dumps(step, ensure_ascii=False) for step in steps)
    return head[:-2] + ',\n  "steps": [\n' + body + "\n  ]\n}\n"


class MacroLibrary:
    def __init__(self, macros_dir: Path) -> None:
        self._shared = Path(macros_dir)
        self._local = self._shared / "local"

    @staticmethod
    def check_name(name: str) -> None:
        if not NAME_PATTERN.match(name):
            raise LibraryError("Nome de macro invalido (use letras, numeros, '_' e '-').")

    def _file(self, directory: Path, name: str) -> Path:
        return directory / f"{name}.json"

    def find(self, name: str) -> Optional[Path]:
        """Path of the macro file; the local copy wins over the shared one."""
        self.check_name(name)
        for directory in (self._local, self._shared):
            path = self._file(directory, name)
            if path.is_file():
                return path
        return None

    def names(self) -> List[str]:
        found = set()
        for directory in (self._local, self._shared):
            if directory.is_dir():
                found.update(p.stem for p in directory.glob("*.json") if NAME_PATTERN.match(p.stem))
        return sorted(found)

    def list(self) -> List[MacroInfo]:
        infos = []
        for name in self.names():
            path = self.find(name)
            infos.append(self._info(name, "local" if path.parent == self._local else "shared", path))
        return infos

    @staticmethod
    def _info(name: str, source: str, path: Path) -> MacroInfo:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return MacroInfo(name, source, path, 0, error=f"JSON invalido ({exc})")
        meta = data if isinstance(data, dict) else {}
        steps = data.get("steps") if isinstance(data, dict) else data
        tags = meta.get("tags")
        return MacroInfo(
            name=name,
            source=source,
            path=path,
            steps=len(steps) if isinstance(steps, list) else 0,
            description=str(meta.get("description", "")),
            tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
            recorded_at=str(meta.get("recorded_at", "")),
        )

    def load_steps(self, name: str) -> List[Step]:
        path = self.find(name)
        if path is None:
            available = ", ".join(self.names()) or "(nenhuma)"
            raise LibraryError(f"Macro '{name}' nao existe. Disponiveis: {available}")
        return load_macro(path)

    def new_recording_dir(self, name: str) -> Path:
        """Allocate a unique local evidence path without creating files or replacing a session."""
        self.check_name(name)
        session = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex
        return self._local / "recordings" / name / session

    def save(
        self,
        name: str,
        steps: List[Step],
        *,
        description: str = "",
        tags: Sequence[str] = (),
        window: Optional[Tuple[int, int]] = None,
        overwrite: bool = False,
    ) -> Path:
        """Write a validated macro to ``macros/local/``; refuses to clobber unless ``overwrite``."""
        self.check_name(name)
        validate_steps(steps)
        existing = self.find(name)
        if existing is not None and not overwrite:
            where = "local" if existing.parent == self._local else "compartilhada"
            raise LibraryError(f"Ja existe uma macro {where} chamada '{name}'. Escolha outro nome ou use --force.")
        document: Dict[str, Any] = {
            "description": description,
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if tags:
            document["tags"] = list(tags)
        if window:
            document["window"] = {"width": window[0], "height": window[1]}
        document["steps"] = steps
        self._local.mkdir(parents=True, exist_ok=True)
        path = self._file(self._local, name)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(_dump(document), encoding="utf-8")
        os.replace(temp, path)  # atomic: a crash never leaves a half-written macro
        return path

    def _local_file(self, name: str) -> Path:
        self.check_name(name)
        path = self._file(self._local, name)
        if path.is_file():
            return path
        if self._file(self._shared, name).is_file():
            raise LibraryError(f"'{name}' e uma macro compartilhada (vem do repositorio): so macros locais podem ser alteradas.")
        raise LibraryError(f"Macro '{name}' nao existe.")

    def delete(self, name: str) -> None:
        self._local_file(name).unlink()

    def rename(self, old: str, new: str) -> Path:
        path = self._local_file(old)
        self.check_name(new)
        if self.find(new) is not None:
            raise LibraryError(f"Ja existe uma macro chamada '{new}'.")
        target = self._file(self._local, new)
        path.rename(target)
        return target
