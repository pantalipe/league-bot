"""Evidence-based, local screen calibration. No game input or asset mutation."""
from __future__ import annotations

import copy
import hashlib
import html
import json
import os
from pathlib import Path
from uuid import uuid4

from league_bot.imaging import Frame
from league_bot.screens import ScreenError, matching_screens, _validate_screens

SIZE = (434, 810)
STATES = ("main", "menu_open", "settings_open", "attendance_claim_ready",
          "attendance_claimed", "attendance_claimed_settings", "unknown")
ASSETS = Path(__file__).resolve().parent / "assets"


class CalibrationError(ValueError):
    """Calibration cannot be justified by the supplied evidence."""


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CalibrationError(f"Nao foi possivel ler {path}: {exc}") from exc


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def catalog():
    """Canonical profiles; aliases with other clicks share the same anchor lists."""
    attendance = _json(ASSETS / "attendance.json")
    navigation = _json(ASSETS / "daily-navigation.json")
    main = next(s for s in _json(ASSETS / "home-recovery.json") if s["name"] == "main")
    result = {s["name"]: s for s in attendance}
    result.update({key: navigation[key] for key in
                   ("menu_open", "settings_open", "attendance_open", "attendance_claimed_settings")})
    result["main"] = main
    result["main_entry"] = copy.deepcopy(main)
    result["main_entry"]["name"] = "main_entry"
    result["main_entry"]["anchors"].extend(navigation["main_closed_anchors"])
    _validate_screens(list(result.values()))
    return result


def load_image(path):
    try:
        from PIL import Image
    except ImportError as exc:
        raise CalibrationError('Instale o suporte de imagens: pip install -e ".[calibration]"') from exc
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            width, height = image.size
            stride = ((width * 3 + 3) // 4) * 4
            rgb = image.tobytes()
            raw = bytearray()
            for y in range(height - 1, -1, -1):
                row = rgb[y * width * 3:(y + 1) * width * 3]
                bgr = bytearray(width * 3)
                bgr[0::3], bgr[1::3], bgr[2::3] = row[2::3], row[1::3], row[0::3]
                raw.extend(bgr)
                raw.extend(b"\0" * (stride - width * 3))
            return Frame(width, height, bytes(raw))
    except (OSError, ValueError) as exc:
        raise CalibrationError(f"Imagem invalida: {path}: {exc}") from exc


def diagnose(frame, screen):
    _validate_screens([screen])
    points = []
    for index, anchor in enumerate(screen["anchors"]):
        x, y = round(anchor["x"] * (frame.width - 1)), round(anchor["y"] * (frame.height - 1))
        actual = frame.average(x, y, anchor.get("radius", 0))
        delta = [abs(a - b) for a, b in zip(actual, anchor["color"])]
        points.append(dict(index=index, x=x, y=y, expected=anchor["color"], actual=list(actual),
                           delta=delta, matched=max(delta) <= anchor.get("tolerance", 20)))
    return {"matched": all(p["matched"] for p in points), "anchors": points,
            "size": [frame.width, frame.height], "expected_size": list(SIZE)}


def propose(screen, positives, negatives, search_radius=12):
    """Find nearby samples stable across every positive, without widening tolerance."""
    _validate_screens([screen])
    if isinstance(search_radius, bool) or not isinstance(search_radius, int) or not 0 <= search_radius <= 30:
        raise CalibrationError("search_radius deve estar entre 0 e 30 pixels")
    if len(positives) < 2 or not negatives:
        raise CalibrationError("Sao necessarias pelo menos duas capturas positivas e uma negativa")
    width, height = positives[0].width, positives[0].height
    if any((f.width, f.height) != (width, height) for f in [*positives, *negatives]):
        raise CalibrationError("As capturas precisam ter a mesma geometria; nao ha redimensionamento automatico")
    result = copy.deepcopy(screen)
    for index, anchor in enumerate(screen["anchors"]):
        if all(diagnose(f, {**screen, "anchors": [anchor, anchor]})["matched"] for f in positives):
            continue
        ox, oy = round(anchor["x"] * (width - 1)), round(anchor["y"] * (height - 1))
        tolerance, radius = anchor.get("tolerance", 20), anchor.get("radius", 0)
        choices = []
        for y in range(max(radius, oy - search_radius), min(height - radius, oy + search_radius + 1)):
            for x in range(max(radius, ox - search_radius), min(width - radius, ox + search_radius + 1)):
                colors = [f.average(x, y, radius) for f in positives]
                low = [min(c[k] for c in colors) for k in range(3)]
                high = [max(c[k] for c in colors) for k in range(3)]
                if max(h - l for h, l in zip(high, low)) > 2 * tolerance:
                    continue
                color = [round((h + l) / 2) for h, l in zip(high, low)]
                # Prefer the original feature's color over an unrelated nearby background.
                drift = max(abs(a - b) for a, b in zip(color, anchor["color"]))
                if drift > max(30, tolerance * 2):
                    continue
                contrast = sum(any(abs(a - b) > tolerance for a, b in zip(f.average(x, y, radius), color))
                               for f in negatives)
                distance = (x - ox) ** 2 + (y - oy) ** 2
                choices.append(((drift, -contrast, distance, y, x), x, y, color))
        if not choices:
            raise CalibrationError(f"{screen['name']}: ponto {index} sem regiao estavel proxima; exige revisao manual")
        _, x, y, color = min(choices)
        result["anchors"][index] = {**anchor, "x": x / max(1, width - 1),
                                     "y": y / max(1, height - 1), "color": color}
    if any(not matching_screens(f, [result]) for f in positives):
        raise CalibrationError(f"{screen['name']}: candidato nao reconhece todas as capturas positivas")
    if any(matching_screens(f, [result]) for f in negatives):
        raise CalibrationError(f"{screen['name']}: candidato confunde uma tela negativa")
    return result


def _labels(state):
    if state not in STATES:
        raise CalibrationError(f"Tela desconhecida: {state}")
    if state == "unknown":
        return []
    if state == "main":
        return ["main", "main_entry"]
    if state.startswith("attendance_"):
        return [state, "attendance_open"]
    return [state]


def _inside(session, name):
    path = (Path(session) / name).resolve()
    if not path.is_relative_to(Path(session).resolve()):
        raise CalibrationError("Caminho de captura fora da sessao")
    return path


def capture_sample(session, state, frames):
    labels = _labels(state)
    session = Path(session)
    session.mkdir(parents=True, exist_ok=True)
    manifest = _json(session / "session.json") if (session / "session.json").exists() else {"version": 1, "samples": []}
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("samples"), list):
        raise CalibrationError("Manifesto da sessao invalido")
    if not frames or any((f.width, f.height) != SIZE for f in frames):
        raise CalibrationError("Capture em 434 x 810; ajuste a janela antes de calibrar")
    paths = []
    for frame in frames:
        path = session / f"{state}-{uuid4().hex}.png"
        path.write_bytes(frame.to_png())
        manifest["samples"].append({"image": path.name, "states": labels})
        paths.append(path)
    _write(session / "session.json", manifest)
    return paths


def add_sample(session, state, paths):
    return capture_sample(session, state, [load_image(path) for path in paths])


def _samples(session):
    manifest = _json(Path(session) / "session.json")
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("samples"), list):
        raise CalibrationError("Manifesto da sessao invalido")
    if not manifest["samples"]:
        raise CalibrationError("Sessao sem capturas do usuario; referencias historicas nao substituem a coleta")
    samples = []
    for item in manifest["samples"]:
        if not isinstance(item, dict) or not isinstance(item.get("image"), str):
            raise CalibrationError("Captura do manifesto invalida")
        labels = item.get("states")
        if not isinstance(labels, list) or any(s not in catalog() for s in labels):
            raise CalibrationError("Rotulos da captura invalidos")
        path = _inside(session, item["image"])
        frame = load_image(path)
        if (frame.width, frame.height) != SIZE:
            raise CalibrationError(f"Geometria incorreta em {path.name}")
        samples.append((frame, set(labels), path))
    references = ASSETS / "calibration-samples" / "samples.json"
    for item in _json(references):
        path = references.parent / item["image"]
        samples.append((load_image(path), set(_labels(item["state"])), path))
    return samples


def _evidence(samples):
    return [{"image": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "states": sorted(labels)} for _, labels, path in samples]


def build_candidate(session, search_radius=12):
    base = catalog()
    samples = _samples(session)
    profiles = copy.deepcopy(base)
    for name, screen in base.items():
        positives = [frame for frame, labels, _ in samples if name in labels]
        negatives = [frame for frame, labels, _ in samples if name not in labels]
        if positives and any(not matching_screens(f, [screen]) for f in positives):
            profiles[name] = propose(screen, positives, negatives, search_radius)
    candidate = {"version": 1, "frame_size": list(SIZE), "base": base,
                 "profiles": profiles, "evidence": _evidence(samples)}
    path = Path(session) / "candidate.json"
    _write(path, candidate)
    write_report(session)
    report = validate_candidate(session)
    if not report["ok"]:
        raise CalibrationError("Candidato salvo para revisao, mas rejeitado: " + "; ".join(report["errors"]))
    return path


def _check_candidate(candidate):
    base = catalog()
    if not isinstance(candidate, dict) or candidate.get("version") != 1 or candidate.get("frame_size") != list(SIZE):
        raise CalibrationError("Formato ou geometria do perfil invalido")
    if candidate.get("base") != base:
        raise CalibrationError("Perfis compartilhados mudaram; gere um candidato novo")
    profiles = candidate.get("profiles")
    if not isinstance(profiles, dict) or profiles.keys() != base.keys():
        raise CalibrationError("Conjunto de telas do candidato invalido")
    try:
        _validate_screens(list(profiles.values()))
    except ScreenError as exc:
        raise CalibrationError(f"Perfil de tela invalido: {exc}") from exc
    for name, screen in profiles.items():
        original = base[name]
        if {k: v for k, v in screen.items() if k != "anchors"} != {k: v for k, v in original.items() if k != "anchors"}:
            raise CalibrationError("A calibragem altera apenas anchors; cliques e limites devem ser preservados")
        if len(screen["anchors"]) != len(original["anchors"]):
            raise CalibrationError("Quantidade de pontos alterada")
        for anchor, old in zip(screen["anchors"], original["anchors"]):
            if anchor.get("tolerance", 20) != old.get("tolerance", 20) or anchor.get("radius", 0) != old.get("radius", 0):
                raise CalibrationError("Tolerancia e raio devem ser preservados")
    return profiles


def validate_candidate(session):
    errors, samples = [], []
    try:
        candidate = _json(Path(session) / "candidate.json")
        profiles = _check_candidate(candidate)
        samples = _samples(session)
        if candidate.get("evidence") != _evidence(samples):
            raise CalibrationError("Capturas ou rotulos mudaram; gere outro candidato")
        for frame, labels, path in samples:
            actual = set(matching_screens(frame, list(profiles.values())))
            if actual != labels:
                errors.append(f"{path.name}: esperado {sorted(labels)}, observado {sorted(actual)}")
        # Also replay the full recovery detector set: a local fix must not collide
        # with an unrelated popup or navigation screen that shares the flow.
        from .home import home_step
        recovery = home_step()
        calibrated = _replace_steps([recovery], candidate)[0]
        aliases = {"main": "main", "menu_open": "menu_return", "settings_open": "settings_return",
                   "attendance_claim_ready": "home_close_attendance_claim_ready",
                   "attendance_claimed": "home_close_attendance_claimed",
                   "attendance_claimed_settings": "home_close_attendance_claimed_settings"}
        for frame, labels, path in samples:
            expected = {aliases[label] for label in labels if label in aliases}
            if not labels:
                expected = set(matching_screens(frame, recovery["screens"]))
            actual = set(matching_screens(frame, calibrated["screens"]))
            if actual != expected:
                errors.append(f"Recuperacao {path.name}: esperado {sorted(expected)}, observado {sorted(actual)}")
        for name, profile in profiles.items():
            if profile != candidate["base"][name]:
                positives = [f for f, labels, _ in samples if name in labels]
                negatives = [f for f, labels, _ in samples if name not in labels]
                if len(positives) < 2 or not negatives:
                    errors.append(f"{name}: faltam duas capturas positivas e uma negativa")
    except (CalibrationError, ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": errors, "samples": len(samples)}


def write_report(session):
    """Local HTML preview with point overlays and exact before/after RGB evidence."""
    import base64
    session = Path(session)
    candidate = _json(session / "candidate.json")
    profiles = _check_candidate(candidate)
    parts = ['<!doctype html><meta charset="utf-8"><title>Calibragem de telas</title>',
             '<style>body{font:16px system-ui;background:#15191e;color:#eee;margin:32px}'
             'table{border-collapse:collapse}td,th{padding:8px;border:1px solid #556}'
             '.frame{position:relative;width:434px}.frame img{width:100%}'
             '.point{position:absolute;width:14px;height:14px;border:2px solid;border-radius:50%;'
             'transform:translate(-50%,-50%);font-size:10px;background:#15191e}'
             '.ok{color:#60df99}.fail{color:#ff7b7b}summary{cursor:pointer;margin:20px 0}</style>',
             '<h1>Revisao da calibragem</h1><p>Verde: corresponde. Vermelho: falhou. '
             'Os pontos exibidos sao do perfil original. Cliques nao foram alterados.</p>']
    for frame, labels, path in _samples(session):
        parts.append(f'<details><summary>{html.escape(path.name)} — {html.escape(", ".join(sorted(labels)) or "negativa")}</summary>')
        for name in sorted(labels - {"main_entry", "attendance_open"}):
            old = diagnose(frame, candidate["base"][name])
            new = diagnose(frame, profiles[name])
            encoded = base64.b64encode(frame.to_png()).decode("ascii")
            parts.append(f'<h3>{html.escape(name)}</h3><div class="frame"><img alt="Captura" src="data:image/png;base64,{encoded}">')
            for point in old["anchors"]:
                style = f'left:{point["x"]}px;top:{point["y"]}px'
                parts.append(f'<span class="point {"ok" if point["matched"] else "fail"}" style="{style}">{point["index"]}</span>')
            parts.append('</div><table><tr><th>Ponto</th><th>Esperado</th><th>Atual</th><th>Diferenca</th><th>Candidato</th></tr>')
            for before, after in zip(old["anchors"], new["anchors"]):
                values = [before["index"], before["expected"], before["actual"], before["delta"],
                          f'({after["x"]}, {after["y"]}) {after["expected"]} — {"OK" if after["matched"] else "FALHOU"}']
                parts.append('<tr>' + ''.join('<td>' + html.escape(str(value)) + '</td>' for value in values) + '</tr>')
            parts.append('</table>')
        parts.append('</details>')
    path = session / "report.html"
    path.write_text('\n'.join(parts), encoding="utf-8")
    return path


def apply_candidate(session, data_dir):
    candidate = _json(Path(session) / "candidate.json")
    report = validate_candidate(session)
    if not report["ok"]:
        raise CalibrationError("Perfil nao ativado: " + "; ".join(report["errors"]))
    if candidate != _json(Path(session) / "candidate.json"):
        raise CalibrationError("O candidato mudou durante a validacao; tente novamente")
    active = Path(data_dir) / "calibration" / "active.json"
    backup = active.with_name("previous.json")
    previous = _json(active) if active.exists() else None
    _write(backup, {"previous": previous})
    # Evidence is rechecked before activation, and never needed in the game process.
    _write(active, {k: candidate[k] for k in ("version", "frame_size", "base", "profiles")})
    return active


def rollback(data_dir):
    active = Path(data_dir) / "calibration" / "active.json"
    backup = active.with_name("previous.json")
    previous = _json(backup)
    if not isinstance(previous, dict) or "previous" not in previous:
        raise CalibrationError("Backup de calibragem invalido")
    if previous["previous"] is None:
        active.unlink(missing_ok=True)
    else:
        _check_candidate(previous["previous"])
        _write(active, previous["previous"])
    backup.unlink()
    return active


def apply_overrides(steps, data_dir):
    """Reload local calibration for each operation; preserve every click and guard."""
    active = Path(data_dir) / "calibration" / "active.json"
    if not active.exists():
        return steps
    candidate = _json(active)
    _check_candidate(candidate)
    return _replace_steps(steps, candidate)


def _replace_steps(steps, candidate):
    profiles = candidate["profiles"]
    replacements = {}
    for name, screen in candidate["base"].items():
        key = _digest(screen["anchors"])
        anchors = profiles[name]["anchors"]
        if key in replacements and replacements[key] != anchors:
            raise CalibrationError("Perfis equivalentes receberam calibragens conflitantes")
        replacements[key] = anchors
    result = copy.deepcopy(steps)
    for step in result:
        if step.get("action") != "screen_flow":
            continue
        for screen in step["screens"]:
            anchors = replacements.get(_digest(screen["anchors"]))
            if anchors is not None and anchors != screen["anchors"]:
                if step.get("frame_size") != list(SIZE):
                    raise CalibrationError("Calibragem exige frame_size 434 x 810")
                screen["anchors"] = copy.deepcopy(anchors)
    return result
