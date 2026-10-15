import unittest
from league_bot.macro import validate_steps
from league_bot.slayer.calibration_tour import routes


class CalibrationTourTests(unittest.TestCase):
    def test_routes_validate_and_only_navigate_to_nonclickable_terminals(self):
        tour = routes()
        self.assertGreaterEqual(len(tour),8)
        for step in tour:
            with self.subTest(terminal=step["terminal"]):
                validate_steps([step])
                self.assertLessEqual(step["timeout"],20)
                terminal = next(s for s in step["screens"] if s["name"]==step["terminal"])
                self.assertNotIn("click",terminal)
                for screen in step["screens"]:
                    if "click" in screen:
                        self.assertEqual(screen["max_clicks"],2)
                        self.assertEqual(screen["retry_after_seconds"],3)


if __name__ == "__main__":
    unittest.main()
