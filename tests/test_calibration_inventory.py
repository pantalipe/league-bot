import json
from pathlib import Path

from league_bot.slayer.calibration_inventory import inventory, screen_signature, step_signature


def test_packaged_inventory_covers_assets_and_daily_macro_actions():
    result = inventory()

    assert result["version"] == 2
    assert result["reference_size"] == [434, 810]
    assert not result["errors"]
    kinds = [entry["kind"] for entry in result["entries"].values()]
    assert kinds.count("screen") > 8
    assert "pixel" in kinds
    assert "click" in kinds
    for name in ("blorb", "free_wpacs", "ativar_scrolls"):
        assert name in result["macros"]
        assert result["macros"][name]["entries"]
    assert "local/blorb" in result["macros"]


def test_runtime_generated_recovery_and_equipment_profiles_are_included():
    result = inventory()
    runtime = [entry for entry in result["entries"].values() if entry.get("runtime_generated")]
    assert runtime
    assert any(entry["name"] == "equipment_open" and entry["source"] == "slayer/equipment.py"
               for entry in runtime)
    assert any(entry["name"] == "equipment_weapon" for entry in runtime)
    assert any(entry["name"] == "equipment_accessories" for entry in runtime)
    assert any(entry["name"] == "orb_accessories_current" and entry["source"] == "slayer/orb.py"
               for entry in runtime)
    assert any(entry["source"] == "slayer/home.py" and entry["pointer"].startswith("home_step()/screens/")
               for entry in runtime)


def test_signatures_ignore_timing_and_comments_but_track_match_data():
    a = {"action": "wait_for_pixel", "x": "50%", "y": 100, "color": [1, 2, 3],
         "timeout": 2, "comment": "first"}
    b = {**a, "timeout": 20, "comment": "changed"}
    assert step_signature(a) == step_signature(b)
    assert step_signature(a) != step_signature({**b, "color": [1, 2, 4]})
    assert screen_signature([{"x": 0.1, "y": 0.2, "color": [1, 2, 3]}]) == screen_signature(
        [{"color": [1, 2, 3], "y": 0.2, "x": 0.1}])


def test_custom_macro_inventory_keeps_percent_and_absolute_coordinates_and_guard_link(tmp_path):
    macro = [{"action": "wait_for_pixel", "x": "25%", "y": 300, "color": [9, 8, 7], "timeout": 1},
             {"action": "click", "x": "25%", "y": 300},
             {"action": "click_if_pixel", "x": 24, "y": 301, "color": [1, 2, 3], "radius": 2},
             {"action": "click", "x": 24, "y": 301}]
    (tmp_path / "sample.json").write_text(json.dumps(macro), encoding="utf-8")

    result = inventory(tmp_path)
    found = [result["entries"][ident] for ident in result["macros"]["sample"]["entries"]]
    assert [(item["kind"], item["base"]["x"]) for item in found] == [
        ("pixel", "25%"), ("click", "25%"), ("pixel", 24), ("click", 24)]
    assert found[1]["previous_guard"] == "/0"
    assert "previous_guard" not in found[3]


def test_malformed_macro_is_reported(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    result = inventory(tmp_path)
    assert any("broken.json" in error for error in result["errors"])
