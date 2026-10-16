"""Companion navigation for the current lower-panel layout."""
import copy
import json
from pathlib import Path

from league_bot.macro import load_macro


def companion_screen():
    # Fixed navigation, tab border and panel separator; no moving battle pixels.
    points = [(230, 790, [255, 146, 0]), (260, 798, [255, 210, 149]),
              (15, 461, [44, 34, 28]), (90, 495, [40, 35, 35])]
    return {"name": "companion_open", "anchors": [
        {"x": x / 433, "y": y / 809, "color": color,
         "tolerance": 15, "radius": 0} for x, y, color in points]}


def recovery_screens():
    screen = companion_screen()
    screen.update(name="home_close_companion", click={"x": 255, "y": 784})
    beast = beast_screen()
    beast.update(name="home_close_beast", click={"x": 41, "y": 774})
    active_mount = active_mount_screen()
    active_mount.update(name="home_close_active_mount", click={"x": 41, "y": 774})
    shop = beast_shop_screen()
    shop.update(name='home_close_beast_shop', click={'x':41,'y':774})
    return [screen, beast, active_mount, shop]


def beast_shop_screen(free=False):
    data = json.loads((Path(__file__).parent / 'assets/beast-shop.json').read_text(encoding='utf-8'))
    return data['free' if free else 'shop']


def beast_screen():
    # Stable title plaque and selected Beast navigation pixels; avoid the
    # animated field and characters below the title.
    points = [(107, 88, [176, 109, 41]), (329, 88, [176, 109, 41]),
              (210, 105, [253, 253, 252]), (172, 776, [235, 243, 243]),
              (220, 779, [235, 104, 36]), (15, 741, [132, 87, 17]),
              (410, 741, [132, 87, 17])]
    return {"name": "beast_open", "anchors": [
        {"x": x / 433, "y": y / 809, "color": color,
         "tolerance": 18, "radius": 0} for x, y, color in points]}


def active_mount_screen():
    # Require the selected creature title, Hunting status, quota text, and
    # selected Mount tab before treating this as an already-active mount.
    points = [(180, 124, [255, 255, 255]),
              (191, 651, [255, 255, 255]), (200, 651, [197, 197, 198]),
              (215, 651, [248, 248, 248]), (220, 651, [235, 235, 236]),
              (240, 651, [235, 235, 235]), (211, 779, [255, 255, 255]),
              (217, 782, [255, 255, 255]), (200, 510, [76, 183, 255]),
              (221, 766, [255, 159, 36])]
    return {"name": "active_mount", "anchors": [
        {"x": x / 433, "y": y / 809, "color": color,
         "tolerance": 15, "radius": 0} for x, y, color in points]}


def ready_mount_screen():
    # Recorded inactive Mount panel: full ready message plus the exact 0/1
    # quota glyph. The generic orange button alone is never authorization.
    points = [(180, 124, [171, 185, 201]), (115, 721, [232, 244, 254]),
              (134, 720, [226, 242, 253]), (164, 720, [233, 245, 253]),
              (198, 721, [253, 254, 255]), (260, 717, [246, 251, 254]),
              (302, 721, [245, 250, 254]), (316, 719, [237, 247, 254]),
              (214, 779, [255, 239, 218]), (200, 510, [76, 183, 255]),
              (221, 766, [255, 159, 36])]
    return {"name": "ready_mount", "anchors": [
        {"x": x / 433, "y": y / 809, "color": color,
         "tolerance": 18, "radius": 0} for x, y, color in points]}


def prepare_mount(name, steps):
    """Replace only the shipped pixel-based opening navigation for montar_besta."""
    if name not in {"montar_besta", "beast_colletct_free"}:
        return steps
    prefix = 7
    known = load_macro(Path(__file__).parent / "macros" / f"{name}.json")
    if len(steps) <= prefix or steps[:prefix] != known[:prefix]:
        return steps

    from .home import home_step
    main = copy.deepcopy(next(screen for screen in home_step()["screens"]
                              if screen["name"] == "main"))
    main.update(click={"x": 230, "y": 790}, max_clicks=1)
    companion = companion_screen()
    companion.update(click={"x": 132, "y": 478}, max_clicks=1)
    active_mount = active_mount_screen()
    active_mount.update(click={"x": 41, "y": 774}, max_clicks=1)
    beast = beast_screen()
    navigation = {
        "action": "screen_flow", "terminal": beast["name"],
        "screens": [main, companion, active_mount, beast], "timeout": 35,
        "poll_seconds": 0.3, "stable_frames": 2, "frame_size": [434, 810],
    }
    tail = copy.deepcopy(steps[prefix:])
    if name == 'beast_colletct_free' and steps == known:
        # Verify the free offer once, then execute the recorded collection and
        # return block. The caller verifies main after the block finishes.
        shop = beast_shop_screen(free=True)
        beast_entry = beast_screen()
        beast_entry.update(click={'x':341,'y':775})
        open_shop = dict(action='screen_flow', terminal='beast_shop_free',
                         screens=[beast_entry,shop],timeout=15,poll_seconds=.3,
                         stable_frames=2,frame_size=[434,810])
        tail = [open_shop, *[copy.deepcopy(s) for s in steps[11:]
                             if s['action'] != 'wait_for_pixel']]
    return [copy.deepcopy(steps[0]), navigation, *tail]


def run_mount(game, name, steps=None):
    """Preflight an existing mount before any recorded activation click."""
    from league_bot.macro import MacroError

    steps = game.load_macro_steps(name) if steps is None else steps
    title = game._title()
    flow_index = next((index for index, step in enumerate(steps)
                       if step.get("action") == "screen_flow"
                       and step.get("terminal") == "beast_open"), None)
    if flow_index is None:
        raise MacroError("Entrada reconhecida da montaria nao disponivel.")
    # Execute only the wrapper, recognized entry, and shipped Mount-tab
    # navigation through original[7:10]. The next recorded click activates.
    preflight_end = flow_index + 4
    with game._exclusive():
        game._run_steps(steps[:preflight_end], name, title)
        hwnd = game._backend.find_window(title)
        if hwnd is None:
            raise MacroError("Janela do jogo nao encontrada durante a verificacao da montaria.")

        def observe(profile):
            flow = {"action": "screen_flow", "terminal": profile["name"],
                    "screens": [profile], "timeout": 8, "poll_seconds": 0.3,
                    "stable_frames": 2, "frame_size": [434, 810]}
            try:
                game._run_steps([flow], name, title)
                return True
            except MacroError as exc:
                if "timed out" in str(exc).lower():
                    return False
                raise

        if observe(active_mount_screen()):
            already_active = True
        elif observe(ready_mount_screen()):
            already_active = False
        else:
            raise MacroError("Estado da montaria nao reconhecido; ativacao ignorada por seguranca.")

        from .home import home_step
        close_active = active_mount_screen()
        close_active.update(name="mount_return_to_beast", click={"x": 41, "y": 774})
        close_beast = beast_screen()
        close_beast.update(name="mount_return_home", click={"x": 41, "y": 774})
        close_companion = companion_screen()
        close_companion.update(name="mount_close_companion", click={"x": 255, "y": 784})
        main = copy.deepcopy(next(screen for screen in home_step()["screens"]
                                  if screen["name"] == "main"))
        recovery = {"action": "screen_flow", "terminal": "main",
                    "screens": [close_active, close_beast, close_companion, main], "timeout": 20,
                    "poll_seconds": 0.3, "stable_frames": 2, "frame_size": [434, 810]}
        if not already_active:
            # Continue only after an exact ready 0/1 match. Stop after the
            # recorded Hunt Start click; replace stale exit pixels with the
            # recognized active→Beast→Companion→main recovery.
            activation_end = flow_index + 1 + (15 - 7)
            game._run_steps(steps[preflight_end:activation_end], name, title)
        game._run_steps([recovery, *game.final_steps()], name, title)
    if already_active:
        return "Montaria ja ativa; navegacao encerrada sem repetir a ativacao."
    return "Montaria ativada e confirmada; retorno reconhecido a tela principal."
