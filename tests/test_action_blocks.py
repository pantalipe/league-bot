import copy
import unittest
from pathlib import Path
from league_bot.macro import load_macro, validate_steps
from league_bot.config import Settings
from league_bot.slayer.game import SlayerDailyGame
from league_bot.slayer.action_blocks import FREE_BLOCKS, action_block, use_action_block

ROOT = Path(__file__).resolve().parents[1]


class FreeActionBlockTests(unittest.TestCase):
    def test_blocks_keep_all_clicks_delays_and_visual_entry_result_flows(self):
        game = SlayerDailyGame(Settings(), object())
        for name in FREE_BLOCKS:
            with self.subTest(name=name):
                raw = load_macro(ROOT / f'league_bot/slayer/macros/{name}.json')
                self.assertTrue(use_action_block(name,raw))
                batch = action_block(raw)
                self.assertEqual([s for s in batch if s['action'] in {'click','wait'}],
                                 [s for s in raw if s['action'] in {'click','wait'}])
                steps = game.load_macro_steps(name)
                self.assertNotIn('wait_for_pixel',[s['action'] for s in steps])
                self.assertEqual(steps[3]['terminal'],'main')
                self.assertEqual(steps[-3]['terminal'],'main')
                validate_steps(steps)

    def test_custom_recordings_and_cost_sensitive_macros_are_excluded(self):
        raw = load_macro(ROOT / 'league_bot/slayer/macros/cobinar_equip.json')
        custom = copy.deepcopy(raw)
        custom[-1]['x'] = '49%'
        self.assertFalse(use_action_block('cobinar_equip',custom))
        for name in ('pet_guild','free_wpacs','blorb','cubo_de_melhora','loja_guild_free',
                     'beast_colletct_free','cave_treinoxp','dragao_dormente'):
            self.assertFalse(use_action_block(name,raw))
