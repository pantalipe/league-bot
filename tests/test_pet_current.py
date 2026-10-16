import unittest
from pathlib import Path

from league_bot.slayer.pet import load_screens
from league_bot.slayer.calibration import load_image
from league_bot.screens import matching_screens

FIXTURES = Path(__file__).resolve().parent / 'fixtures/slayer/companion'


class CurrentPetEvidenceTests(unittest.TestCase):
    def test_panel_and_reward_are_distinct_from_each_other(self):
        profiles = {s['name']:s for s in load_screens()}
        panel = load_image(FIXTURES / 'pet_current_0.png')
        reward = load_image(FIXTURES / 'pet_reward_current.png')
        states = [profiles['pet_open_current'],profiles['reward_current']]
        self.assertEqual(matching_screens(panel,states),['pet_open_current'])
        self.assertEqual(matching_screens(reward,states),['reward_current'])
        counters = [s for name,s in profiles.items() if name.startswith('pet_current_')]
        self.assertEqual(matching_screens(panel,counters),['pet_current_0'])
        self.assertEqual(matching_screens(reward,counters),[])
        for path in FIXTURES.glob('pet_current_*.png'):
            with self.subTest(path=path.name):
                self.assertEqual(matching_screens(load_image(path), counters), [path.stem])
