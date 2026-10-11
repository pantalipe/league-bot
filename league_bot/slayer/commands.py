"""Transport-independent named daily status updates."""
import re
import unicodedata
from .status import PRESETS

ALIASES = {"presenca": "attendance", "attendance": "attendance",
           "espada": "summon_sword", "espadas": "summon_sword",
           "acessorio": "summon_accessory", "acessorios": "summon_accessory",
           "habilidade": "summon_skill", "habilidades": "summon_skill"}
ALIASES.update({name: name for name in PRESETS})


def canonical(value):
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold().strip()


def set_progress(store, args):
    if len(args) < 2:
        raise ValueError('Uso: /dailyset "Nome" <progresso> [meta].')
    alias = ALIASES.get(canonical(args[0]))
    if alias:
        if len(args) not in (2, 3):
            raise ValueError("Use tarefa, progresso e meta opcional.")
        task_id = alias
        label, _, default = PRESETS[task_id]
        progress_text = args[1]
        target_text = args[2] if len(args) == 3 else str(default)
    else:
        label = " ".join(args[:-2]) if len(args) >= 3 else args[0]
        slug = re.sub(r"[^a-z0-9]+", "-", canonical(label)).strip("-")[:55].strip("-")
        if not slug:
            raise ValueError("Dê um nome com letras ou números para a missão.")
        task_id = "mission:" + slug
        existing = store.snapshot()["tasks"].get(task_id)
        progress_text = args[-2] if len(args) >= 3 else args[1]
        target_text = args[-1] if len(args) >= 3 else str((existing or {}).get("target", ""))
        label = (existing or {}).get("label") or label
    if not re.fullmatch(r"\d+", progress_text) or not re.fullmatch(r"\d+", target_text):
        raise ValueError("Informe progresso inteiro e uma meta para missões novas.")
    progress, target = int(progress_text), int(target_text)
    store.mark_progress(task_id, progress, target, label=label, source="manual")
    return f"✅ {label}: {progress}/{target}"
