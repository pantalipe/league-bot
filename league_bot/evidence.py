"""Local recording evidence, with bounded asynchronous PNG writes (stdlib only)."""
from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .imaging import Frame

# A capture has an interval: a frame completed after a press is not a valid 'before'.
Capture = Tuple[float, float, Frame]


class EvidenceWriter:
    def __init__(self, directory: Path, start: float, post_delay: float) -> None:
        self.directory = Path(directory)
        self.start = start
        self.post_delay = post_delay
        self.started_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.events: List[Dict[str, Any]] = []
        self.image_count = 0
        self._jobs: queue.Queue = queue.Queue(maxsize=8)
        self._thread: Optional[threading.Thread] = None

    def snapshot(self, index: int, phase: str, capture: Optional[Capture], reason: str) -> Dict[str, Any]:
        if capture is None:
            return {"status": reason, "file": None}
        begun, ended, frame = capture
        result = {
            "status": "queued", "file": None,
            "capture_started_seconds": round(begun - self.start, 6),
            "capture_finished_seconds": round(ended - self.start, 6),
            "width": frame.width, "height": frame.height,
        }
        if self._thread is None:
            self._thread = threading.Thread(target=self._write_loop, name="league-evidence", daemon=True)
            self._thread.start()
        try:
            self._jobs.put_nowait((f"{index:04d}_{phase}.png", frame, result))
        except queue.Full:
            result["status"] = "queue_full"
        return result

    def _write_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            filename, frame, result = job
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory / filename).write_bytes(frame.to_png())
                result.update(status="saved", file=filename)
                self.image_count += 1
            except Exception as exc:
                result.update(status="write_failed", error=str(exc))

    def finish(self, duration: float, window_size: Tuple[int, int], warnings: List[str]) -> Optional[Path]:
        if self._thread is not None:
            self._jobs.put(None)
            self._thread.join()
        if not self.events:
            return None
        missing = sum(s["status"] != "saved" for e in self.events for s in (e["before"], e["after"]))
        if missing:
            warnings.append(f"shots: {missing} imagem(ns) indisponivel(is); consulte os motivos no manifest.json.")
        document = {
            "schema_version": 1, "started_at": self.started_at,
            "macro_step_index_base": 0, "click_index_base": 1,
            "time_origin": "recording_start", "duration_seconds": round(duration, 6),
            "window": {"width": window_size[0], "height": window_size[1]},
            "post_delay_seconds": self.post_delay,
            "after_is_stable": False,
            "image_count": self.image_count, "warnings": list(warnings), "clicks": self.events,
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / "manifest.json"
            temp = path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(path)
            return path
        except OSError as exc:
            warnings.append(f"shots: falha ao salvar manifest.json: {exc}")
            return None
