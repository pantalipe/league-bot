import json
import tempfile
import unittest
from pathlib import Path

from league_bot.library import LibraryError, MacroLibrary
from league_bot.macro import MacroError

STEPS = [{"action": "wait_window"}, {"action": "wait", "seconds": 1}, {"action": "click", "x": "50%", "y": "50%"}]


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = MacroLibrary(self.root)

    def write_shared(self, name, payload):
        (self.root / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_save_load_roundtrip_with_metadata(self):
        path = self.lib.save("quest_1", STEPS, description="Daily 1", tags=["daily", "easy"], window=(438, 814))
        self.assertEqual(path, self.root / "local" / "quest_1.json")
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["description"], "Daily 1")
        self.assertEqual(document["tags"], ["daily", "easy"])
        self.assertEqual(document["window"], {"width": 438, "height": 814})
        self.assertIn("recorded_at", document)
        self.assertEqual(self.lib.load_steps("quest_1"), STEPS)

    def test_saved_file_has_one_step_per_line_and_no_temp_leftovers(self):
        path = self.lib.save("quest_1", STEPS)
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(1 for line in lines if '"action"' in line), len(STEPS))
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_save_refuses_to_clobber_unless_forced(self):
        self.lib.save("quest_1", STEPS)
        with self.assertRaisesRegex(LibraryError, "Ja existe"):
            self.lib.save("quest_1", STEPS)
        self.lib.save("quest_1", STEPS[:1], overwrite=True)
        self.assertEqual(len(self.lib.load_steps("quest_1")), 1)

    def test_save_refuses_to_shadow_a_shared_macro_unless_forced(self):
        self.write_shared("start_game", {"steps": STEPS})
        with self.assertRaisesRegex(LibraryError, "compartilhada"):
            self.lib.save("start_game", STEPS)

    def test_save_validates_steps_and_names(self):
        with self.assertRaises(MacroError):
            self.lib.save("bad", [{"action": "teleport"}])
        for name in ["../evil", "a b", "", "x" * 65, "dot.name"]:
            with self.subTest(name=name), self.assertRaises(LibraryError):
                self.lib.save(name, STEPS)

    def test_local_macros_override_shared_ones(self):
        self.write_shared("mini", {"description": "shared", "steps": STEPS})
        self.lib.save("mini", STEPS[:1], description="mine", overwrite=True)
        info = [i for i in self.lib.list() if i.name == "mini"]
        self.assertEqual([(i.source, i.description, i.steps) for i in info], [("local", "mine", 1)])
        self.assertEqual(self.lib.names(), ["mini"])

    def test_list_reports_source_metadata_and_broken_files(self):
        self.write_shared("shared_one", STEPS)  # plain list format
        self.lib.save("zeta", STEPS, description="d", tags=["t"])
        (self.root / "local" / "broken.json").write_text("{nope", encoding="utf-8")
        by_name = {i.name: i for i in self.lib.list()}
        self.assertEqual((by_name["shared_one"].source, by_name["shared_one"].steps), ("shared", 3))
        self.assertEqual((by_name["zeta"].source, by_name["zeta"].tags), ("local", ("t",)))
        self.assertIn("JSON invalido", by_name["broken"].error)
        self.assertEqual(self.lib.names(), ["broken", "shared_one", "zeta"])

    def test_unknown_macro_lists_the_available_ones(self):
        self.lib.save("alpha", STEPS)
        with self.assertRaisesRegex(LibraryError, "alpha"):
            self.lib.load_steps("nope")

    def test_delete_and_rename_only_touch_local_macros(self):
        self.write_shared("shared_one", STEPS)
        self.lib.save("mine", STEPS)
        self.assertEqual(self.lib.rename("mine", "renamed"), self.root / "local" / "renamed.json")
        self.assertEqual(self.lib.names(), ["renamed", "shared_one"])
        self.lib.delete("renamed")
        self.assertEqual(self.lib.names(), ["shared_one"])
        for action in (lambda: self.lib.delete("shared_one"), lambda: self.lib.rename("shared_one", "x")):
            with self.assertRaisesRegex(LibraryError, "compartilhada"):
                action()
        with self.assertRaisesRegex(LibraryError, "nao existe"):
            self.lib.delete("ghost")

    def test_rename_refuses_existing_target(self):
        self.lib.save("a", STEPS)
        self.lib.save("b", STEPS)
        with self.assertRaisesRegex(LibraryError, "Ja existe"):
            self.lib.rename("a", "b")


if __name__ == "__main__":
    unittest.main()
