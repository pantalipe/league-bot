import unittest
from pathlib import Path
from league_bot.macro import load_macro, validate_steps
from league_bot.screens import matching_screens
from league_bot.slayer.battle_navigation import prepare_battle_entry, profiles
from league_bot.slayer.home import home_step
from tests.test_slayer_attendance import png_frame

ROOT=Path(__file__).resolve().parents[1]

class BattleNavigationTests(unittest.TestCase):
    def test_entries_preserve_claims_and_unknown_custom_macros(self):
        for name,prefix in [('floresta_circulacao',13),('treinador',7)]:
            original=load_macro(ROOT/f'league_bot/slayer/macros/{name}.json')
            prepared=prepare_battle_entry(name,original)
            validate_steps(prepared)
            self.assertEqual(prepared[-len(original[prefix:]):],original[prefix:])
            changed=[dict(s) for s in original]
            changed[2]['x']='50%'
            self.assertEqual(prepare_battle_entry(name,changed),changed)

    def test_panels_are_distinct_and_character_recovers_by_navigation(self):
        screens=list(profiles().values())
        for name in ('forest','character'):
            frame=png_frame(ROOT/f'tests/fixtures/slayer/battle_navigation/{name}.png')
            self.assertEqual(matching_screens(frame,screens),[name+'_open'])
        frame=png_frame(ROOT/'tests/fixtures/slayer/battle_navigation/character.png')
        self.assertEqual(matching_screens(frame,home_step()['screens']),['home_close_character'])

    def test_forest_rows_follow_the_observed_120_position_without_enter_click(self):
        data=profiles()
        rows=[data['forest_120_recorded'],data['forest_120_current'],data['forest_popup']]
        for key in ('forest_120_recorded','forest_120_current','forest_popup'):
            frame=png_frame(ROOT/f'tests/fixtures/slayer/battle_navigation/{key}.png')
            self.assertEqual(matching_screens(frame,rows),[data[key]['name']])
        self.assertNotIn('click',data['forest_popup'])

    def test_enhance_recovery_closes_character_instead_of_upgrading(self):
        frame=png_frame(ROOT/'tests/fixtures/slayer/battle_navigation/character_enhance.png')
        self.assertEqual(matching_screens(frame,home_step()['screens']),['home_close_character_enhance'])

    def test_bright_main_artwork_remains_main_without_opening_a_panel(self):
        # Existing fixture and new fixed-artwork colors must stay unambiguous.
        for path in ('home/main.png','battle_navigation/bright_main.png'):
            frame=png_frame(ROOT/f'tests/fixtures/slayer/{path}')
            self.assertEqual(matching_screens(frame,home_step()['screens']),['main'])
