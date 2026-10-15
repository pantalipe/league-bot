"""Read-only inventory of packaged screen matchers and macro input guards.

The inventory deliberately uses JSON pointers into source files so a calibration
review can address an exact matcher or action without loading a game backend.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

REFERENCE_SIZE = [434, 810]
ASSETS = Path(__file__).resolve().parent / "assets"
DEFAULT_MACROS = Path(__file__).resolve().parents[2] / "macros"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_anchor(anchor: Any) -> bool:
    return (isinstance(anchor, dict) and isinstance(anchor.get("x"), (int, float)) and
            not isinstance(anchor.get("x"), bool) and math.isfinite(anchor["x"]) and
            isinstance(anchor.get("y"), (int, float)) and not isinstance(anchor.get("y"), bool) and
            math.isfinite(anchor["y"]) and isinstance(anchor.get("color"), list) and
            len(anchor["color"]) == 3 and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255
                                               for c in anchor["color"]))


def screen_signature(anchors: list[dict]) -> str:
    """Hash only matching data; names and incidental screen metadata are excluded."""
    return _hash(anchors)


def step_signature(step: dict) -> str:
    """Hash matcher/action semantics while ignoring timing and comments."""
    action = step.get("action")
    if action == "screen_flow":
        payload = {"action": action, "screens": [
            {k: copy.deepcopy(s[k]) for k in ("name", "anchors", "click") if k in s}
            for s in step.get("screens", []) if isinstance(s, dict)]}
    elif action in ("wait_for_pixel", "click_if_pixel"):
        payload = {k: copy.deepcopy(step[k]) for k in ("action", "x", "y", "color", "radius", "tolerance") if k in step}
    elif action == "click":
        payload = {k: copy.deepcopy(step[k]) for k in ("action", "x", "y") if k in step}
    else:
        payload = {"action": action}
    return _hash(payload)


def _pointer(parts: tuple[Any, ...]) -> str:
    def escape(part: Any) -> str:
        return str(part).replace("~", "~0").replace("/", "~1")
    return "" if not parts else "/" + "/".join(escape(p) for p in parts)


def _walk(value: Any, path: tuple[Any, ...] = ()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path + (index,))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _size_for(obj: dict) -> list[int]:
    size = obj.get("frame_size") or obj.get("reference_size")
    if isinstance(size, list) and len(size) == 2 and all(isinstance(n, int) and n > 0 for n in size):
        return list(size)
    return list(REFERENCE_SIZE)


def _stable_id(kind: str, source: str, pointer: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9]+", "_", Path(source).stem).strip("_").lower()
    return f"{kind}:{stem}:{_hash([source, pointer])[:12]}"


def _name(value: dict, fallback: str) -> str:
    name = value.get("name")
    return name if isinstance(name, str) and name else fallback


def inventory(macros_dir: Path | None = None) -> dict:
    """Inventory all packaged asset anchor groups and macro guards/clicks.

    ``macros_dir`` can point to a root or local override directory; when it is
    ``None``, packaged root macros and the corresponding local overrides are
    both included. Malformed JSON files are reported in ``errors``.
    """
    entries: dict[str, dict] = {}
    macros: dict[str, dict] = {}
    errors: list[str] = []

    def add(kind: str, source: str, pointer: str, base: Any, signature: str,
            size: list[int], name: str):
        ident = _stable_id(kind, source, pointer)
        entries[ident] = {"id": ident, "kind": kind, "source": source,
                          "pointer": pointer, "base": copy.deepcopy(base),
                          "signature": signature, "reference_size": list(size), "name": name}
        return ident

    for path in sorted(ASSETS.rglob("*.json")):
        source = path.relative_to(ASSETS.parent.parent).as_posix()
        try:
            data = _read_json(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        for parts, obj in _walk(data):
            if not isinstance(obj, dict):
                continue
            anchors = obj.get("anchors")
            if isinstance(anchors, list) and len(anchors) >= 2 and all(_valid_anchor(a) for a in anchors):
                add("screen", source, _pointer(parts + ("anchors",)), obj,
                    screen_signature(anchors), _size_for(obj), _name(obj, ".".join(map(str, parts)) or path.stem))
            # Standalone anchor lists (for example navigation variants) are
            # recognized by their contents, not by a broad key-name heuristic.
            for key, value in obj.items():
                if key == "anchors" or not isinstance(value, list) or len(value) < 2:
                    continue
                if all(_valid_anchor(a) for a in value):
                    label = ".".join(map(str, parts + (key,))) or key
                    add("screen", source, _pointer(parts + (key,)), value,
                        screen_signature(value), _size_for(obj), label)

    def add_runtime_screen(source: str, pointer: str, screen: Any) -> None:
        if not isinstance(screen, dict):
            errors.append(f"{source}#{pointer}: expected a screen object")
            return
        anchors = screen.get("anchors")
        if not isinstance(anchors, list) or len(anchors) < 2 or not all(_valid_anchor(anchor) for anchor in anchors):
            errors.append(f"{source}#{pointer}: invalid runtime screen anchors")
            return
        ident = add("screen", source, pointer, screen, screen_signature(anchors),
                    list(REFERENCE_SIZE), _name(screen, pointer))
        entries[ident]["runtime_generated"] = True

    # These functions construct matcher profiles from code rather than JSON.
    # They are pure profile builders/loaders; inventory never starts a game or backend.
    try:
        from .home import home_step
        home = home_step()
        if isinstance(home, dict) and isinstance(home.get("screens"), list):
            for index, screen in enumerate(home["screens"]):
                add_runtime_screen("slayer/home.py", f"home_step()/screens/{index}/anchors", screen)
        else:
            errors.append("slayer/home.py#home_step(): expected a screen_flow step")
    except Exception as exc:
        errors.append(f"slayer/home.py#home_step(): {exc}")
    try:
        from .equipment import equipment_accessories_screen, equipment_screen, equipment_weapon_screen
        for function, screen in (("equipment_screen", equipment_screen()),
                                 ("equipment_weapon_screen", equipment_weapon_screen()),
                                 ("equipment_accessories_screen", equipment_accessories_screen())):
            add_runtime_screen("slayer/equipment.py", f"{function}()/anchors", screen)
    except Exception as exc:
        errors.append(f"slayer/equipment.py#screen builders: {exc}")
    try:
        from .orb import _current_accessories_screen
        add_runtime_screen("slayer/orb.py", "_current_accessories_screen()/anchors", _current_accessories_screen())
    except Exception as exc:
        errors.append(f"slayer/orb.py#_current_accessories_screen(): {exc}")

    macro_root = Path(macros_dir) if macros_dir is not None else DEFAULT_MACROS
    if macros_dir is None and not macro_root.is_dir():
        packaged = Path(__file__).resolve().parent / "macros"
        if packaged.is_dir():
            macro_root = packaged
    if macros_dir is None:
        candidates = [(p, p.relative_to(macro_root).as_posix()) for p in sorted(macro_root.glob("*.json"))]
        local = macro_root / "local"
        if local.is_dir():
            # The local tree is an intentional override library; recordings are
            # evidence and are never parsed as executable macro definitions.
            candidates.extend((p, p.relative_to(macro_root).as_posix()) for p in sorted(local.glob("*.json")))
    elif macro_root.is_dir():
        candidates = [(p, p.relative_to(macro_root).as_posix()) for p in sorted(macro_root.glob("*.json"))]
        local = macro_root / "local"
        if local.is_dir():
            candidates.extend((p, p.relative_to(macro_root).as_posix()) for p in sorted(local.glob("*.json")))
    else:
        candidates = []
        errors.append(f"{macro_root}: macros directory does not exist")

    for path, source in candidates:
        try:
            data = _read_json(path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        steps = data.get("steps") if isinstance(data, dict) else data
        if not isinstance(steps, list):
            errors.append(f"{path}: expected a list of steps")
            continue
        macro_name = path.stem if source.startswith("local/") is False else "local/" + path.stem
        macro_entries: list[str] = []
        previous_guard: tuple[str, str] | None = None
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            ptr = _pointer(("steps", i)) if isinstance(data, dict) else _pointer((i,))
            if action == "screen_flow":
                screens = step.get("screens", [])
                if not isinstance(screens, list):
                    errors.append(f"{path}: {ptr}/screens must be a list")
                    continue
                for si, screen in enumerate(screens):
                    if not isinstance(screen, dict) or not isinstance(screen.get("anchors"), list):
                        continue
                    anchors = screen["anchors"]
                    if len(anchors) < 2 or not all(_valid_anchor(a) for a in anchors):
                        continue
                    p = f"{ptr}/screens/{si}/anchors"
                    ident = add("screen", source, p, screen, screen_signature(anchors), _size_for(step),
                                _name(screen, f"{macro_name}:{step.get('name', 'flow')}:{si}"))
                    macro_entries.append(ident)
                previous_guard = None
            elif action in ("wait_for_pixel", "click_if_pixel"):
                sig = step_signature(step)
                ident = add("pixel", source, ptr, step, sig, _size_for(step),
                            str(step.get("name") or f"{macro_name} step {i + 1} {action}"))
                macro_entries.append(ident)
                previous_guard = (sig, ptr) if action == "wait_for_pixel" else None
            elif action == "click":
                ident = add("click", source, ptr, step, step_signature(step), _size_for(step),
                            str(step.get("name") or f"{macro_name} step {i + 1} click"))
                if previous_guard and step.get("x") == _read_step(path, data, previous_guard[1]).get("x") and step.get("y") == _read_step(path, data, previous_guard[1]).get("y"):
                    entries[ident]["previous_guard"] = previous_guard[1]
                macro_entries.append(ident)
                previous_guard = None
            else:
                previous_guard = None
        macros[macro_name] = {"entries": macro_entries, "source": source}
    return {"version": 2, "reference_size": list(REFERENCE_SIZE), "entries": entries,
            "macros": macros, "errors": errors}


def _read_step(path: Path, data: Any, pointer: str) -> dict:
    """Resolve an internal JSON pointer (used only for same-file guard linkage)."""
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:]]
    value = data
    for part in parts:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value if isinstance(value, dict) else {}
