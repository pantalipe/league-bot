import json
import unittest
from pathlib import Path

from league_bot.imaging import Frame
from league_bot.macro import MacroRunner, MacroError
from league_bot.slayer.calibration import load_image
from league_bot.screens import matching_screens
from tests.test_slayer_attendance import FakeBackend, FakeTime

ROOT=Path(__file__).resolve().parents[1]


class CurrentEntryCheckpointTests(unittest.TestCase):
    def test_forest_current_popup_and_multiplier_recover_without_entering(self):
        from league_bot.slayer.home import home_step
        from league_bot.slayer.battle_navigation import forest_checkpoint
        cases=[('forest_popup_current.png','forest-popup-current'),('forest_multiplier.png','forest-multiplier')]
        for filename,asset in cases:
            with self.subTest(filename=filename):
                frame=load_image(ROOT/'tests/fixtures/slayer/battle_navigation'/filename)
                gate=forest_checkpoint(asset)
                self.assertEqual(matching_screens(frame,[gate]),[gate['name']])
                self.assertEqual(matching_screens(frame,home_step()['screens']),['home_close_'+gate['name']])

    def test_dragon_back_navigation_recognizes_each_overlay_level(self):
        from league_bot.slayer.home import home_step
        screens=home_step()['screens']
        for filename,name in [('dragon_difficulty.png','home_close_dragon_difficulty_current'),
                              ('dragon_reward_select.png','home_close_dragon_reward_current')]:
            with self.subTest(filename=filename):
                frame=load_image(ROOT/'tests/fixtures/slayer/companion'/filename)
                self.assertEqual(matching_screens(frame,screens),[name])

    def test_dragon_free_quota_must_match_before_multiplier_click(self):
        gate=json.loads((ROOT/'league_bot/slayer/assets/dragon-multiplier.json').read_text())
        frame=load_image(ROOT/'tests/fixtures/slayer/companion/dragon_multiplier.png')
        flow=dict(action='screen_flow',terminal=gate['name'],screens=[gate],
                  timeout=1,poll_seconds=.3,stable_frames=2,frame_size=[434,810])
        time=FakeTime();backend=FakeBackend([frame]*2)
        runner=MacroRunner(backend,'Slayer Legend',False,sleep=time.sleep,clock=time.clock)
        runner.run([flow,dict(action='click',x=344,y=596)])
        self.assertEqual(backend.click_log,[(344,596,False)])
        pixels=bytearray(frame.bgr)
        for y in range(643,663):
            for x in range(199,239):
                offset=(809-y)*frame.row_size+x*3
                pixels[offset:offset+3]=bytes((0,0,0))
        unknown=Frame(434,810,bytes(pixels))
        time=FakeTime();backend=FakeBackend([unknown])
        runner=MacroRunner(backend,'Slayer Legend',False,sleep=time.sleep,clock=time.clock)
        with self.assertRaisesRegex(MacroError,'timed out'):
            runner.run([flow,dict(action='click',x=344,y=596)])
        self.assertEqual(backend.click_log,[])

    def test_guild_free_offer_is_observed_in_current_layout(self):
        gate=json.loads((ROOT/'league_bot/slayer/assets/guild-shop-free.json').read_text())
        frame=load_image(ROOT/'tests/fixtures/slayer/companion/guild_shop_free.png')
        self.assertEqual(matching_screens(frame,[gate]),['guild_shop_free'])
