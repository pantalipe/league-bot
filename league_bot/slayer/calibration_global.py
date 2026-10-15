"""Offline evidence catalog and local runtime overrides for all inventory matchers."""
from __future__ import annotations

import copy
import html
import hashlib
import json
import math
import shutil
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4

from league_bot.macro import resolve_coord
from . import calibration as v1
from .calibration_inventory import inventory as build_inventory
from .calibration_inventory import screen_signature, step_signature

VERSION = 1


class GlobalCalibrationError(ValueError):
    """Evidence or a global calibration candidate is invalid."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GlobalCalibrationError(f"Cannot read {path}: {exc}") from exc


def _safe_child(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise GlobalCalibrationError("Sample path escapes the calibration session")
    return path


def _entry_catalog(inv: dict | None = None) -> dict:
    inv = build_inventory() if inv is None else inv
    if inv.get("version") != 2 or not isinstance(inv.get("entries"), dict):
        raise GlobalCalibrationError("Unsupported inventory format")
    if inv.get("errors"):
        raise GlobalCalibrationError("Inventory contains malformed files: " + "; ".join(inv["errors"]))
    return inv


def create_session(session: Path, inv: dict | None = None) -> Path:
    """Create an evidence manifest containing every inventory matcher as pending."""
    session = Path(session)
    session.mkdir(parents=True, exist_ok=True)
    catalog = _entry_catalog(inv)
    manifest = {"version": VERSION, "inventory_version": catalog["version"],
                "entries": {ident: {"signature": entry["signature"], "kind": entry["kind"],
                                    "source": entry["source"], "pointer": entry["pointer"],
                                    "base_sha256": _digest(entry["base"]),
                                    "samples": []}
                            for ident, entry in catalog["entries"].items()}}
    path = session / "session.json"
    _write_json(path, manifest)
    return path


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest(session: Path, inv: dict | None = None) -> tuple[dict, dict]:
    catalog = _entry_catalog(inv)
    session = Path(session)
    if not (session / "session.json").exists():
        create_session(session, catalog)
    manifest = _read(Path(session) / "session.json")
    if manifest.get("version") != VERSION or manifest.get("inventory_version") != catalog["version"]:
        raise GlobalCalibrationError("Session format is unsupported")
    if set(manifest.get("entries", {})) != set(catalog["entries"]):
        raise GlobalCalibrationError("Inventory changed; start a new calibration session")
    for ident, entry in catalog["entries"].items():
        recorded = manifest["entries"][ident]
        if (any(recorded.get(key) != entry[key] for key in ("signature", "kind", "source", "pointer")) or
                recorded.get("base_sha256") != _digest(entry["base"])):
            raise GlobalCalibrationError(f"Source matcher changed since session creation: {ident}")
    return manifest, catalog


def coverage(session: Path, inv: dict | None = None) -> dict:
    """Return positive/negative counts for every matcher and macro coverage."""
    manifest, catalog = _manifest(session, inv)
    per_macro: dict[str, dict[str, int]] = {}
    statuses = {}
    for ident, entry in catalog["entries"].items():
        samples = manifest["entries"][ident]["samples"]
        positive = sum(item["label"] == "positive" for item in samples)
        negative = sum(item["label"] == "negative" for item in samples)
        calibratable = entry["kind"] in ("screen", "pixel")
        statuses[ident] = {"positive": positive, "negative": negative,
                           "calibratable": calibratable,
                           "evidence_ready": (positive >= 2 and negative >= 1) if calibratable else None,
                           # Compatibility alias: this means evidence is present, not that a profile passed validation.
                           "ready": (positive >= 2 and negative >= 1) if calibratable else None}
        if entry["source"].endswith(".json") and not entry["source"].startswith("slayer/assets/"):
            name = entry["source"].removesuffix(".json")
            group = per_macro.setdefault(name, {"total": 0, "ready": 0, "positive": 0, "negative": 0})
            if calibratable:
                group["total"] += 1
                group["evidence_ready"] = group.get("evidence_ready", 0) + int(statuses[ident]["evidence_ready"])
                group["ready"] = group["evidence_ready"]
                group["positive"] += positive
                group["negative"] += negative
            else:
                group["click_actions"] = group.get("click_actions", 0) + 1
    return {"entries": statuses, "macros": per_macro,
            "evidence_ready": sum(value["evidence_ready"] for value in statuses.values() if value["calibratable"]),
            "ready": sum(value["evidence_ready"] for value in statuses.values() if value["calibratable"]),
            "total": sum(value["calibratable"] for value in statuses.values())}


def add(session: Path, entry_id: str, label: str, images: list[Path] | Path,
        inv: dict | None = None) -> dict:
    """Attach evidence screenshots to one inventory matcher under a clear label."""
    if label not in ("positive", "negative"):
        raise GlobalCalibrationError("label must be 'positive' or 'negative'")
    paths = [images] if isinstance(images, (str, Path)) else list(images)
    if not paths:
        raise GlobalCalibrationError("At least one screenshot is required")
    session = Path(session)
    session.mkdir(parents=True, exist_ok=True)
    if not (session / "session.json").exists():
        create_session(session, inv)
    manifest, catalog = _manifest(session, inv)
    if entry_id not in catalog["entries"]:
        raise GlobalCalibrationError(f"Unknown inventory entry: {entry_id}")
    entry = catalog["entries"][entry_id]
    added = []
    for source in paths:
        source = Path(source)
        try:
            frame = v1.load_image(source)
        except v1.CalibrationError as exc:
            raise GlobalCalibrationError(str(exc)) from exc
        expected = entry.get("reference_size", [434, 810])
        if [frame.width, frame.height] != expected:
            raise GlobalCalibrationError(f"{source.name}: expected screenshot size {expected}, got {[frame.width, frame.height]}")
        filename = f"{entry_id.replace(':', '_')}-{label}-{uuid4().hex}.png"
        destination = session / "samples" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        record = {"label": label, "image": f"samples/{filename}", "sha256": _file_hash(destination)}
        manifest["entries"][entry_id]["samples"].append(record)
        added.append(record)
    _write_json(session / "session.json", manifest)
    return {"entry": entry_id, "added": len(added), "coverage": coverage(session, inv)["entries"][entry_id]}


def _frames(session: Path, sample_records: list[dict]) -> list[tuple[str, Any, Path]]:
    session = Path(session).resolve()
    result = []
    for item in sample_records:
        path = _safe_child(Path(session), item["image"])
        if _file_hash(path) != item.get("sha256"):
            raise GlobalCalibrationError(f"Screenshot changed after labeling: {path.name}")
        try:
            frame = v1.load_image(path)
        except v1.CalibrationError as exc:
            raise GlobalCalibrationError(str(exc)) from exc
        result.append((item["label"], frame, path))
    return result


def _screen_base(entry: dict) -> dict:
    base = entry["base"]
    if isinstance(base, dict) and isinstance(base.get("anchors"), list):
        screen = copy.deepcopy(base)
        screen.setdefault("name", entry["name"])
    elif isinstance(base, list):
        screen = {"name": entry["name"], "anchors": copy.deepcopy(base)}
    else:
        raise GlobalCalibrationError(f"Invalid screen base for {entry['id']}")
    return screen


def _pixel_point(step: dict, frame) -> tuple[int, int, tuple[int, int, int] | None]:
    try:
        def coordinate(value, dimension):
            if isinstance(value, dict) and set(value) == {"relative"}:
                fraction = value["relative"]
                if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0 <= fraction <= 1:
                    raise ValueError("relative coordinate must be between 0 and 1")
                return round(fraction * (dimension - 1))
            return resolve_coord(value, dimension)
        x = coordinate(step["x"], frame.width)
        y = coordinate(step["y"], frame.height)
    except (KeyError, ValueError, TypeError) as exc:
        raise GlobalCalibrationError(f"Invalid pixel coordinates: {exc}") from exc
    radius = step.get("radius", 0)
    if isinstance(radius, bool) or not isinstance(radius, int) or not 0 <= radius <= 20:
        raise GlobalCalibrationError("Pixel radius must be an integer from 0 to 20")
    if not (0 <= x < frame.width and 0 <= y < frame.height):
        raise GlobalCalibrationError("Pixel matcher coordinate is outside screenshot")
    return x, y, frame.average(x, y, radius)


def _matches_pixel(step: dict, frame) -> bool:
    x, y, sample = _pixel_point(step, frame)
    expected = step.get("color")
    tolerance = step.get("tolerance", 20)
    if sample is None or not isinstance(expected, list) or len(expected) != 3:
        return False
    return max(abs(actual - target) for actual, target in zip(sample, expected)) <= tolerance


def _propose_pixel(entry: dict, frames: list[tuple[str, Any, Path]]) -> dict:
    base = entry["base"]
    positives = [frame for label, frame, _ in frames if label == "positive"]
    negatives = [frame for label, frame, _ in frames if label == "negative"]
    if len(positives) < 2 or not negatives:
        raise GlobalCalibrationError(f"{entry['id']}: requires at least two positive and one negative screenshot")
    samples = [_pixel_point(base, frame)[2] for frame in positives]
    if any(sample is None for sample in samples):
        raise GlobalCalibrationError(f"{entry['id']}: positive screenshot has no pixel sample")
    colors = [round(median(sample[channel] for sample in samples)) for channel in range(3)]
    drift_limit = max(30, 2 * base.get("tolerance", 20))
    if max(abs(a - b) for a, b in zip(colors, base["color"])) > drift_limit:
        raise GlobalCalibrationError(f"{entry['id']}: sampled color drift exceeds {drift_limit}")
    proposed = copy.deepcopy(base)
    proposed["color"] = colors
    if any(not _matches_pixel(proposed, frame) for frame in positives):
        raise GlobalCalibrationError(f"{entry['id']}: one positive screenshot falls outside preserved tolerance")
    if any(_matches_pixel(proposed, frame) for frame in negatives):
        raise GlobalCalibrationError(f"{entry['id']}: proposed color also matches an explicit negative")
    return proposed


def propose(session: Path, inv: dict | None = None) -> Path:
    """Write candidate overrides only for matchers whose positive evidence fails baseline."""
    session = Path(session)
    manifest, catalog = _manifest(session, inv)
    profiles: dict[str, dict] = {}
    evidence: dict[str, list[dict]] = {}
    errors: list[str] = []
    # Reuse a previous profile only when both the full source entry and its
    # exact ordered evidence labels/files/digests are unchanged. Final validate
    # always replays every reused profile against the screenshots.
    cached = {}
    try:
        previous = _read(session / "candidate.json")
        current_entries = {ident: _entry_metadata(entry) for ident, entry in catalog["entries"].items()}
        previous_entries = previous.get("entries", {})
        prior_profiles = previous.get("profiles", {})
        if (previous.get("version") == VERSION and previous.get("inventory_version") == catalog["version"]
                and previous_entries == current_entries and isinstance(prior_profiles, dict)):
            for ident, profile in prior_profiles.items():
                if ident not in catalog["entries"] or not isinstance(profile, dict):
                    continue
                entry = catalog["entries"][ident]
                expected_evidence = [{key: record[key] for key in ("label", "image", "sha256")}
                                      for record in manifest["entries"][ident]["samples"]]
                evidence_files_intact = all(
                    _file_hash(_safe_child(session, record["image"])) == record["sha256"]
                    for record in manifest["entries"][ident]["samples"])
                if (profile.get("entry_sha256") == _digest(entry) and
                        profile.get("signature") == entry["signature"] and
                        profile.get("kind") == entry["kind"] and
                        profile.get("source") == entry["source"] and
                        profile.get("pointer") == entry["pointer"] and
                        profile.get("base") == entry["base"] and evidence_files_intact and
                        profile.get("evidence") == expected_evidence):
                    cached[ident] = copy.deepcopy(profile)
    except (GlobalCalibrationError, OSError, TypeError, AttributeError, KeyError):
        cached = {}
    for ident, entry in catalog["entries"].items():
        records = manifest["entries"][ident]["samples"]
        if not records:
            continue
        if ident in cached:
            profiles[ident] = cached[ident]
            evidence[ident] = cached[ident]["evidence"]
            continue
        try:
            frames = _frames(session, records)
            positives = [frame for label, frame, _ in frames if label == "positive"]
            negatives = [frame for label, frame, _ in frames if label == "negative"]
            if entry["kind"] == "screen":
                baseline = _screen_base(entry)
                baseline_positive = all(v1.diagnose(frame, baseline)["matched"] for frame in positives)
                baseline_negative = any(v1.diagnose(frame, baseline)["matched"] for frame in negatives)
                if baseline_positive and not baseline_negative:
                    if len(positives) < 2 or not negatives:
                        continue
                    value = baseline
                else:
                    if len(positives) < 2 or not negatives:
                        raise GlobalCalibrationError(f"{ident}: requires at least two positive and one negative screenshot")
                    value = v1.propose(baseline, positives, negatives)
            elif entry["kind"] == "pixel":
                baseline = entry["base"]
                baseline_positive = all(_matches_pixel(baseline, frame) for frame in positives)
                baseline_negative = any(_matches_pixel(baseline, frame) for frame in negatives)
                if baseline_positive and not baseline_negative:
                    if len(positives) < 2 or not negatives:
                        continue
                    value = copy.deepcopy(baseline)
                else:
                    if len(positives) < 2 or not negatives:
                        raise GlobalCalibrationError(f"{ident}: requires at least two positive and one negative screenshot")
                    value = _propose_pixel(entry, frames)
            else:
                # Click destinations are recorded for review but never derived from image evidence.
                continue
            profiles[ident] = {"kind": entry["kind"], "signature": entry["signature"],
                               "source": entry["source"], "pointer": entry["pointer"],
                               "entry_sha256": _digest(entry),
                               "name": entry.get("name"),
                               "base": copy.deepcopy(entry["base"]), "value": value,
                               "evidence": [{"label": label, "image": path.relative_to(session.resolve()).as_posix(),
                                             "sha256": _file_hash(path)}
                                            for label, _, path in frames]}
            evidence[ident] = profiles[ident]["evidence"]
        except (GlobalCalibrationError, v1.CalibrationError, ValueError, TypeError, KeyError) as exc:
            errors.append(str(exc))
    candidate = {"version": VERSION, "inventory_version": catalog["version"],
                 "entries": {ident: _entry_metadata(item)
                             for ident, item in catalog["entries"].items()},
                 "profiles": profiles, "errors": errors}
    path = session / "candidate.json"
    _write_json(path, candidate)
    write_report(session, inv)
    return path


def write_report(session: Path, inv: dict | None = None) -> Path:
    """Write a self-contained local HTML review of evidence and candidate changes."""
    session = Path(session)
    manifest, catalog = _manifest(session, inv)
    candidate_path = session / "candidate.json"
    candidate = _read(candidate_path) if candidate_path.exists() else {"profiles": {}, "errors": []}
    profiles = candidate.get("profiles", {}) if isinstance(candidate, dict) else {}
    candidate_errors = candidate.get("errors", []) if isinstance(candidate, dict) else ["Malformed candidate"]
    summary = coverage(session, inv)
    parts = [
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Revisão da calibração global</title>',
        '<style>body{font:15px system-ui,sans-serif;background:#15191e;color:#eee;margin:2rem;max-width:1100px}'
        'table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border:1px solid #52606d;padding:.5rem;text-align:left;vertical-align:top}'
        'th{background:#242c34}code{overflow-wrap:anywhere}.pending{color:#f2c66d}.evidence{color:#81c7f3}'
        '.proposed{color:#86df9b}.error{color:#ff8888}details{border-top:1px solid #52606d;padding:.6rem 0}'
        'a{color:#8dcaff}</style>',
        '<h1>Revisão da calibração global</h1>',
        '<p>Este relatório é offline. “Evidência pronta” significa que há duas capturas positivas e uma negativa; '
        '“proposta” indica que o candidato inclui um perfil e não contém erros. Isso não confirma que o perfil foi ativado.</p>',
        f'<p>Perfis no candidato: {len(profiles)}. Correspondências com evidência pronta: '
        f'{summary["evidence_ready"]} de {summary["total"]}.</p>',
    ]
    if candidate_errors:
        parts.append('<h2 class="error">Erros do candidato</h2><ul>')
        parts.extend(f'<li>{html.escape(str(error))}</li>' for error in candidate_errors)
        parts.append('</ul>')
    parts.append('<h2>Cobertura por macro</h2><table><tr><th>Macro</th><th>Correspondências prontas</th><th>Correspondências</th><th>Ações de clique catalogadas</th></tr>')
    for name, row in sorted(summary["macros"].items()):
        parts.append('<tr>' + ''.join((f'<td>{html.escape(str(value))}</td>' for value in
                        (name, row.get("evidence_ready", 0), row.get("total", 0), row.get("click_actions", 0)))) + '</tr>')
    parts.append('</table><p>Ações de clique são catalogadas para contexto; não são verificadas nem alteradas por esta calibração.</p>')
    parts.append('<h2>Correspondências e evidências</h2>')
    for ident, entry in catalog["entries"].items():
        recorded = manifest["entries"][ident]
        samples = recorded["samples"]
        profile = profiles.get(ident) if isinstance(profiles, dict) else None
        ready = summary["entries"][ident]["evidence_ready"]
        if entry["kind"] == "click":
            status, css = "pendente", "pending"
        elif profile and not candidate_errors:
            status, css = "proposta", "proposed"
        elif ready:
            status, css = "evidência pronta", "evidence"
        else:
            status, css = "pendente", "pending"
        parts.append(f'<details><summary><strong>{html.escape(entry["name"])}</strong> — '
                     f'<code>{html.escape(ident)}</code> — <span class="{css}">{status}</span></summary>')
        parts.append('<p>' + html.escape(f"Tipo: {entry['kind']} · Origem: {entry['source']} · JSON pointer: {entry['pointer']}") + '</p>')
        if entry["kind"] == "click":
            parts.append('<p class="pending">Ação de clique catalogada; destino e resultado não foram verificados nem calibrados.</p>')
        parts.append('<ul>')
        for sample in samples:
            try:
                safe_path = _safe_child(session, sample["image"])
                relative = safe_path.relative_to(session.resolve()).as_posix()
                href = html.escape(relative, quote=True)
                label = html.escape(str(sample["label"]))
                parts.append(f'<li>{label}: <a href="{href}">{html.escape(relative)}</a> '
                             f'(SHA-256 {html.escape(sample["sha256"])})</li>')
            except (GlobalCalibrationError, KeyError, ValueError):
                parts.append('<li class="error">Evidência inválida ou fora da sessão</li>')
        parts.append('</ul>')
        if entry["kind"] == "screen":
            base = _screen_base(entry)
            value = profile.get("value") if isinstance(profile, dict) else base
            if isinstance(value, list):
                value = {"anchors": value}
            old_anchors = base.get("anchors", [])
            new_anchors = value.get("anchors", []) if isinstance(value, dict) else []
            parts.append('<table><tr><th>Ponto</th><th>Coordenada antiga</th><th>Cor antiga</th><th>Coordenada proposta</th><th>Cor proposta</th></tr>')
            for index, old in enumerate(old_anchors):
                new = new_anchors[index] if index < len(new_anchors) else old
                parts.append('<tr>' + ''.join(f'<td>{html.escape(str(item))}</td>' for item in (
                    index, [old.get("x"), old.get("y")], old.get("color"), [new.get("x"), new.get("y")], new.get("color"))) + '</tr>')
            parts.append('</table>')
        elif entry["kind"] == "pixel":
            old = entry["base"]
            new = profile.get("value", old) if isinstance(profile, dict) else old
            parts.append('<table><tr><th>Coordenada antiga</th><th>Cor antiga</th><th>Coordenada proposta</th><th>Cor proposta</th><th>Raio / tolerância</th></tr><tr>' +
                         ''.join(f'<td>{html.escape(str(item))}</td>' for item in (
                             [old.get("x"), old.get("y")], old.get("color"), [new.get("x"), new.get("y")],
                             new.get("color"), [new.get("radius", 0), new.get("tolerance", 20)])) + '</tr></table>')
        parts.append('</details>')
    parts.append('</html>')
    report_path = session / "report.html"
    report_path.write_text('\n'.join(parts), encoding="utf-8")
    return report_path


def _entry_metadata(entry: dict) -> dict:
    """Compact exact baseline commitment for every current inventory field."""
    return {"signature": entry["signature"], "kind": entry["kind"],
            "source": entry["source"], "pointer": entry["pointer"],
            "base": copy.deepcopy(entry["base"]), "entry_sha256": _digest(entry)}


def _current_signature(entry: dict) -> str:
    return entry["signature"]


def validate(session: Path, inv: dict | None = None) -> dict:
    """Validate source freshness, evidence integrity, coverage, and matcher outcomes."""
    errors: list[str] = []
    candidate = None
    try:
        manifest, catalog = _manifest(session, inv)
        candidate = _read(Path(session) / "candidate.json")
        if candidate.get("version") != VERSION or candidate.get("inventory_version") != catalog["version"]:
            raise GlobalCalibrationError("Unsupported candidate version")
        current = candidate.get("entries", {})
        if set(current) != set(catalog["entries"]):
            raise GlobalCalibrationError("Candidate inventory does not match current source")
        for ident, entry in catalog["entries"].items():
            saved = current[ident]
            if saved != _entry_metadata(entry):
                raise GlobalCalibrationError(f"Source matcher changed since proposal: {ident}")
        if candidate.get("errors"):
            errors.extend(candidate["errors"])
        profiles = candidate.get("profiles", {})
        if not isinstance(profiles, dict):
            raise GlobalCalibrationError("Candidate profiles must be an object")
        for ident, entry in catalog["entries"].items():
            if entry["kind"] not in ("screen", "pixel"):
                continue
            counts = coverage(session, inv)["entries"][ident]
            if counts["positive"] >= 2 and counts["negative"] >= 1 and ident not in profiles:
                errors.append(f"{ident}: evidence-ready matcher is missing from candidate")
        for ident, profile in profiles.items():
            if ident not in catalog["entries"]:
                errors.append(f"Unknown profile {ident}")
                continue
            entry = catalog["entries"][ident]
            counts = coverage(session, inv)["entries"][ident]
            if counts["positive"] < 2 or counts["negative"] < 1:
                errors.append(f"{ident}: requires two positives and one negative")
            if profile.get("signature") != entry["signature"] or profile.get("kind") != entry["kind"]:
                errors.append(f"{ident}: profile signature or kind changed")
            records = manifest["entries"][ident]["samples"]
            frames = _frames(Path(session), records)
            by_label = [(label, frame) for label, frame, _ in frames]
            if profile.get("evidence") != [{"label": label, "image": path.relative_to(Path(session).resolve()).as_posix(),
                                             "sha256": _file_hash(path)} for label, _, path in frames]:
                errors.append(f"{ident}: candidate evidence differs from labeled samples")
            if entry["kind"] == "screen":
                screen = profile.get("value")
                if not isinstance(screen, dict) or len(screen.get("anchors", [])) != len(_screen_base(entry)["anchors"]):
                    errors.append(f"{ident}: malformed screen profile")
                    continue
                original = _screen_base(entry)
                for anchor, old in zip(screen["anchors"], original["anchors"]):
                    if anchor.get("tolerance", 20) != old.get("tolerance", 20) or anchor.get("radius", 0) != old.get("radius", 0):
                        errors.append(f"{ident}: tolerance and radius must be preserved")
                if {k: v for k, v in screen.items() if k != "anchors"} != {k: v for k, v in original.items() if k != "anchors"}:
                    errors.append(f"{ident}: screen clicks and metadata must be preserved")
                for label, frame in by_label:
                    if v1.diagnose(frame, screen)["matched"] != (label == "positive"):
                        errors.append(f"{ident}: screenshot label mismatch for {label}")
            elif entry["kind"] == "pixel":
                value = profile.get("value")
                if not isinstance(value, dict) or any(value.get(k) != entry["base"].get(k) for k in ("x", "y", "radius", "tolerance", "action")):
                    errors.append(f"{ident}: pixel coordinates, radius, tolerance, and action must be preserved")
                    continue
                for label, frame in by_label:
                    if _matches_pixel(value, frame) != (label == "positive"):
                        errors.append(f"{ident}: screenshot label mismatch for {label}")
        return {"ok": not errors, "errors": errors, "profiles": len(candidate.get("profiles", {})),
                "coverage": coverage(session, inv)}
    except (GlobalCalibrationError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(str(exc))
        return {"ok": False, "errors": errors, "profiles": 0}


def apply(session: Path, data_dir: Path, inv: dict | None = None) -> Path:
    """Activate a validated local override catalog without touching packaged assets."""
    result = validate(session, inv)
    if not result["ok"]:
        raise GlobalCalibrationError("Calibration was not activated: " + "; ".join(result["errors"]))
    candidate = _read(Path(session) / "candidate.json")
    active = Path(data_dir) / "calibration" / "global-active.json"
    previous = active.with_name("global-previous.json")
    _write_json(previous, {"previous": _read(active) if active.exists() else None})
    _write_json(active, {"version": VERSION, "inventory_version": candidate["inventory_version"],
                         "entries": candidate["entries"], "profiles": candidate["profiles"]})
    return active


def rollback(data_dir: Path) -> Path:
    """Restore the previous local global-calibration catalog."""
    active = Path(data_dir) / "calibration" / "global-active.json"
    previous = active.with_name("global-previous.json")
    snapshot = _read(previous)
    if not isinstance(snapshot, dict) or "previous" not in snapshot:
        raise GlobalCalibrationError("Previous global calibration backup is invalid")
    old = snapshot["previous"]
    if old is None:
        active.unlink(missing_ok=True)
    else:
        if not isinstance(old, dict) or old.get("version") != VERSION or not isinstance(old.get("profiles"), dict):
            raise GlobalCalibrationError("Previous global calibration backup is invalid")
        _write_json(active, old)
    previous.unlink(missing_ok=True)
    return active


def _transform(step: dict, data_dir: Path, source: str | None = None) -> dict:
    """Return a step with source-signature matched screen/pixel overrides applied."""
    active = Path(data_dir) / "calibration" / "global-active.json"
    if not active.exists():
        return copy.deepcopy(step)
    data = _read(active)
    if data.get("version") != VERSION:
        raise GlobalCalibrationError("Unsupported active global calibration")
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise GlobalCalibrationError("Active calibration profiles must be an object")
    result = copy.deepcopy(step)
    action = result.get("action")
    matches = []
    if action == "screen_flow":
        for screen in result.get("screens", []):
            if not isinstance(screen, dict) or not isinstance(screen.get("anchors"), list):
                continue
            signature = screen_signature(screen["anchors"])
            try:
                candidates = [p for p in profiles.values() if isinstance(p, dict) and p.get("kind") == "screen" and p.get("signature") == signature
                              and (source is None or p.get("source") == source)]
            except (AttributeError, TypeError) as exc:
                raise GlobalCalibrationError(f"Malformed active screen profile: {exc}") from exc
            values = { _digest(p["value"]["anchors"]): p["value"]["anchors"] for p in candidates }
            if len(values) > 1:
                raise GlobalCalibrationError("Conflicting active profiles share this screen signature")
            if values:
                anchors = copy.deepcopy(next(iter(values.values())))
                profile = candidates[0]
                raw_base = profile.get("base")
                value = profile.get("value")
                if isinstance(raw_base, list):
                    base = _screen_base({"base": raw_base, "name": profile.get("name") or
                                         (value.get("name") if isinstance(value, dict) else "screen")})
                elif isinstance(raw_base, dict):
                    base = raw_base
                else:
                    base = None
                if (not isinstance(base, dict) or not isinstance(value, dict) or
                        {k: v for k, v in value.items() if k != "anchors"} !=
                        {k: v for k, v in base.items() if k != "anchors"} or
                        len(anchors) != len(base.get("anchors", [])) or any(
                            new.get("radius", 0) != old.get("radius", 0) or
                            new.get("tolerance", 20) != old.get("tolerance", 20)
                            for new, old in zip(anchors, base.get("anchors", [])))):
                    raise GlobalCalibrationError("Malformed active screen profile changes click metadata, radius, or tolerance")
                screen["anchors"] = anchors
    elif action in ("wait_for_pixel", "click_if_pixel"):
        signature = step_signature(result)
        candidates = [p for p in profiles.values() if isinstance(p, dict) and p.get("kind") == "pixel" and p.get("signature") == signature
                      and (source is None or p.get("source") == source)]
        values = {_digest(p["value"]): p["value"] for p in candidates}
        if len(values) > 1:
            raise GlobalCalibrationError("Conflicting active profiles share this pixel signature")
        if values:
            calibrated = next(iter(values.values()))
            candidate = candidates[0]
            base = candidate.get("base")
            if (not isinstance(base, dict) or
                    any(calibrated.get(key) != base.get(key) for key in ("x", "y", "radius", "tolerance", "action"))):
                raise GlobalCalibrationError("Malformed active pixel profile changes coordinates, radius, tolerance, or action")
            for key in ("color", "radius", "tolerance"):
                if key in calibrated:
                    result[key] = copy.deepcopy(calibrated[key])
    return result


def transform(step: dict, data_dir: Path, source: str | None = None) -> dict:
    """Safe public wrapper that turns malformed local state into a clear error."""
    try:
        return _transform(step, data_dir, source)
    except GlobalCalibrationError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise GlobalCalibrationError(f"Malformed active calibration: {exc}") from exc
