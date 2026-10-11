from datetime import datetime, timedelta
from typing import Any
from .status import BR_TZ
MESSAGE_LIMIT = 3900
GROUP_LABELS = {"presence": "Presença", "summons": "Invocações", "missions": "Missões", "macros": "Execuções de macros"}


def _format_reset(value: Any) -> str:
    if not value:
        return "não informado"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BR_TZ)
        return dt.astimezone(BR_TZ).strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return str(value)


def _format_snapshot(snapshot: dict[str, Any]) -> str:
    tasks = snapshot.get("tasks") or {}
    groups: dict[str, list[str]] = {key: [] for key in GROUP_LABELS}
    for task_id, task in tasks.items():
        group = str(task.get("group") or "missions")
        groups.setdefault(group, [])
        label = str(task.get("label") or task_id)
        progress = task.get("progress", 0)
        target = task.get("target")
        status = str(task.get("status") or "not_checked")
        if status == "completed":
            mark = "✅"
        elif status == "error":
            mark = "⚠️"
        elif status == "pending":
            mark = "⏳"
        else:
            mark = "⬜"
        quota = f"{progress}/{target}" if target is not None else str(progress)
        line = f"{mark} {label}: {quota}"
        if status == "not_checked":
            line += " · não conferido"
        elif status == "error":
            line += " · erro no acompanhamento"
        source = task.get("source")
        if source == "manual":
            updated = task.get("updated_at")
            when = ""
            if updated:
                try:
                    dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=BR_TZ)
                    when = " " + dt.astimezone(BR_TZ).strftime("%H:%M")
                except (TypeError, ValueError):
                    pass
            line += f" · manual{when}"
        elif source == "visual":
            line += " · visual"
        elif source == "macro":
            line += " · macro"
        interval = {"macro:blorb": 300, "macro:free_wpacs": 600}.get(task_id)
        completed_at = task.get("last_completed_at")
        if interval and completed_at and progress < target:
            try:
                next_time = datetime.fromisoformat(completed_at) + timedelta(seconds=interval)
                line += " · próxima disponível: " + _format_reset(next_time.isoformat())
            except (ValueError, TypeError):
                pass
        groups[group].append(line)

    lines = [f"📅 Status diário · ciclo {snapshot.get('cycle_id') or '?'}",
             f"Próximo reset: {_format_reset(snapshot.get('next_resetISO', snapshot.get('next_reset')))}"]
    for key, label in GROUP_LABELS.items():
        rows = groups.get(key, [])
        if rows:
            lines.extend(["", label, *rows])
    for key in sorted(set(groups) - set(GROUP_LABELS)):
        if groups[key]:
            lines.extend(["", key.capitalize(), *groups[key]])
    return "\n".join(lines)


def _chunks(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
        while len(current) > limit:
            chunks.append(current[:limit])
            current = current[limit:]
    if current:
        chunks.append(current)
    return chunks
