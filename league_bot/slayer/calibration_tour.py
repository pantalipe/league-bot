"""Bounded navigation tour collecting evidence, without reward actions."""
from __future__ import annotations

import copy
import time
from pathlib import Path

from league_bot.macro import MacroError
from .calibration import _write
from .calibration_inventory import screen_signature


def routes():
    from .home import load_screens
    from .equipment import equipment_entry_step
    from .dungeon_navigation import dungeon_entry_step
    from .guild_navigation import guild_entry_step, load_profiles
    from .shop import profiles as shop_profiles
    from .scrolls import profiles as scroll_profiles
    from .battle_navigation import profiles as battle_profiles
    from .quest_navigation import load_profiles as quest_profiles
    main = next(s for s in load_screens() if s["name"] == "main")

    def entry(terminal, x, y):
        source = copy.deepcopy(main)
        source.update(click={"x": x, "y": y}, max_clicks=1)
        return dict(action="screen_flow", screens=[source, copy.deepcopy(terminal)],
                    terminal=terminal["name"], frame_size=[434,810], stable_frames=2,
                    timeout=12, poll_seconds=.3)

    shops = {s["name"]: s for s in shop_profiles()["screens"]}
    maps = copy.deepcopy(load_profiles()["maps"])
    map_route = entry(maps[0],331,784)
    map_route["screens"].extend(maps[1:])
    map_route["terminal_aliases"] = [s["name"] for s in maps[1:]]
    goods = entry(shops["shop_goods"], 404, 784)
    import json
    intermediate = json.loads((Path(__file__).parent / "assets/summon-navigation.json").read_text(encoding="utf-8"))
    intermediate.update(click={"x":219,"y":281},max_clicks=1)
    goods["screens"].insert(1, intermediate)
    guild_shop = copy.deepcopy(guild_entry_step())
    guild_shop["terminal"] = "guild_shop"
    lobby = next(s for s in guild_shop["screens"] if s["name"] == "guild_lobby")
    lobby["click"] = {"x":234,"y":775}
    guild_shop["screens"].append(copy.deepcopy(load_profiles()["guild_shop"]))
    quest = quest_profiles()
    daily = entry(quest["quest_daily"],412,109)
    repeat = copy.deepcopy(quest["quest_repeat"])
    repeat["click"] = {"x":95,"y":246}
    daily["screens"].insert(1,repeat)
    characters = battle_profiles()
    character_route = entry(characters["character"],33,784)
    character_variants = [copy.deepcopy(characters[key]) for key in ("character_enhance","character_promotion")]
    character_route["screens"].extend(character_variants)
    character_route["terminal_aliases"] = [s["name"] for s in character_variants]
    result = [entry(scroll_profiles()["screen"],409,175), equipment_entry_step(),
              map_route, dungeon_entry_step(),
              guild_entry_step(), entry(shops["shop_open"],404,784), goods,
              character_route,guild_shop,daily]
    for step in result:
        step["timeout"] = min(step["timeout"], 20)
        for screen in step["screens"]:
            if "click" in screen:
                screen["max_clicks"] = 2
                screen["retry_after_seconds"] = 3
    return result


def run_tour(game, session: Path, inv: dict, *, count=3, interval=.3, resume=False):
    from . import calibration_global as engine
    from .home import home_step
    session = Path(session)
    folder = session / "tour"
    folder.mkdir(parents=True, exist_ok=True)
    engine.coverage(session, inv)
    previous = {}
    if resume and (session / "tour.json").exists():
        import json
        previous = {item["terminal"]:item for item in json.loads((session/"tour.json").read_text(encoding="utf-8"))}
    recovery = home_step()
    recovery["screens"] = [s for s in recovery["screens"] if s["name"] != "home_confirm_pet_reward"]
    recovery["timeout"] = 12
    report = []

    def captures(label):
        hwnd = game._backend.find_window(game._title())
        paths = []
        for i in range(count):
            frame = game._backend.capture(hwnd)
            if frame is None:
                raise MacroError("Captura indisponivel durante o tour")
            path = folder / f"{label}-{time.time_ns()}-{i}.png"
            path.write_bytes(frame.to_png())
            paths.append(path)
            time.sleep(interval)
        return paths

    with game._exclusive():
        game._run_steps([{"action":"wait_window","timeout":5},
                         {"action":"prepare_window"},recovery],"calibration_tour_main",game._title())
        for step in routes():
            name = step["terminal"]
            if previous.get(name,{}).get("status") == "captured" and not previous[name].get("recovery_error"):
                report.append(previous[name])
                continue
            print(f"Calibracao: navegando ate {name}.", flush=True)
            negatives = captures("main")
            item = {"terminal":name,"status":"pending"}
            try:
                game._run_steps([step],f"calibration_tour_{name}",game._title())
                positives = captures(name)
                from league_bot.screens import matching_screens
                from .calibration import load_image
                calibrated = game._calibrate_screen(step)
                observed = matching_screens(load_image(positives[0]), calibrated["screens"])
                if len(observed) != 1 or observed[0] not in {name,*step.get("terminal_aliases",[])}:
                    raise MacroError("Tela mudou durante a captura; amostras permanecem sem rotulo")
                terminal = next(s for s in step["screens"] if s["name"] == observed[0])
                signature = screen_signature(terminal["anchors"])
                ids = [ident for ident, entry in inv["entries"].items()
                       if entry["kind"] == "screen" and entry["signature"] == signature]
                for ident in ids:
                    engine.add(session,ident,"positive",positives,inv)
                    engine.add(session,ident,"negative",negatives,inv)
                item.update(status="captured",observed=observed[0],entries=ids,images=[str(p) for p in positives])
            except (MacroError,OSError) as exc:
                item.update(error=str(exc),images=[str(p) for p in captures("unknown-"+name)])
            report.append(item)
            _write(session / "tour.json",report)
            try:
                game._run_steps([recovery],"calibration_tour_return",game._title())
            except (MacroError,OSError) as exc:
                item["recovery_error"] = str(exc)
                item["status"] = "recovery_failed"
                _write(session / "tour.json",report)
                print("Tour interrompido: retorno ao menu nao reconhecido.",flush=True)
                break
    return report
