"""Seed the editable daily selection while preserving caller-owned state."""
import json
import os
from pathlib import Path
from league_bot.daily import DailyError, DailyList
from .plan import DEFAULT_MACROS


def open_home_daily(settings, library, *, path=None):
    path = Path(path) if path else Path(settings.data_dir) / "daily.json"
    if not path.exists():
        previous = DailyList(Path(settings.data_dir) / "daily.json", library).macros()
        names = list(dict.fromkeys([*DEFAULT_MACROS, *previous]))
        names = [name for name in names if name != "attendance_check"]
        missing = [name for name in names if library.find(name) is None]
        if missing:
            raise DailyError("Gravacoes ausentes para configurar a daily: " + ", ".join(missing))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"macros": names,"plan_version":2}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data,dict) or not isinstance(data.get("macros"),list):
                raise ValueError()
            if data.get("plan_version",1) < 2:
                if library.find("pet_guild") is None:
                    raise DailyError("Gravacao pet_guild ausente.")
                data["macros"] = list(dict.fromkeys([*data["macros"],"pet_guild"]))
                data["plan_version"] = 2
                temp = path.with_suffix(".json.tmp")
                temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
                os.replace(temp,path)
        except (ValueError,OSError,TypeError):
            raise DailyError("Selecao da daily invalida; dados preservados.") from None
    return DailyList(path, library)
