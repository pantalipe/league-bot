import copy
import unittest
from pathlib import Path

from league_bot.macro import load_macro, validate_steps
from league_bot.slayer.skill_navigation import prepare_refinement
from league_bot.slayer.home import home_step
from league_bot.slayer.calibration import load_image
from league_bot.screens import matching_screens

ROOT = Path(__file__).resolve().parents[1]


class RefinementCheckpointTests(unittest.TestCase):
    def test_current_grounds_has_one_recognized_navigation_exit(self):
        frame = load_image(ROOT / 'tests/fixtures/slayer/companion/refinement_current.png')
        self.assertEqual(matching_screens(frame, home_step()['screens']),
                         ['home_close_refinement_current'])

    def test_known_recording_uses_panel_checkpoints_and_one_action_block(self):
        original = load_macro(ROOT / 'league_bot/slayer/macros/refinamento_skill.json')
        result = prepare_refinement('refinamento_skill', original)
        self.assertEqual([s.get('terminal') for s in result if s['action'] == 'screen_flow'],
                         ['skill_current', 'refinement_ground'])
        self.assertEqual(result[3:], [s for s in original[7:] if s['action'] != 'wait_for_pixel'])
        validate_steps(result)

    def test_custom_actions_are_not_rewritten(self):
        original = load_macro(ROOT / 'league_bot/slayer/macros/refinamento_skill.json')
        custom = copy.deepcopy(original)
        custom[8]['x'] = '49%'
        self.assertEqual(prepare_refinement('refinamento_skill', custom), custom)
