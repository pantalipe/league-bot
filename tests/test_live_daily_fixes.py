"""Regression checks from the supervised 2026-10-12 daily."""
import unittest
from pathlib import Path
import test_daily_plan as daily_plan
from test_slayer_attendance import FakeBackend, FakeTime, png_frame
from league_bot.macro import MacroRunner
from league_bot.screens import matching_screens
from league_bot.slayer.home import home_step
from league_bot.slayer.plan import ordered_macros, DEFAULT_MACROS
from league_bot.slayer.dungeon_navigation import dungeon_entry_step, prepare_dungeon_macro, prepare_summons
from league_bot.macro import load_macro, validate_steps

class LiveDailyFixTests(unittest.TestCase):
    make_runner = daily_plan.DailyPlanTests.make_runner

    def test_refinement_collection_follows_combat(self):
        order = ordered_macros(DEFAULT_MACROS)
        self.assertGreater(order.index('refinamento_skill_completed'), order.index('treinador'))
        self.assertLess(order.index('refinamento_skill_completed'), order.index('collect_finished_dailys'))

    def test_refinement_in_progress_defers_without_click_or_progress(self):
        runner, store, game, clock = self.make_runner(['refinamento_skill_completed'])
        store.mark_progress('macro:refinamento_skill',1,source='macro')
        result = runner.run()
        self.assertEqual(result.status,'partial')
        self.assertIn('refinamento_skill_completed',result.pending)
        self.assertNotIn('refinamento_skill_completed',game.calls)
        self.assertNotIn('macro:refinamento_skill_completed',store.snapshot()['tasks'])
        clock.advance(600)
        result = runner.run()
        self.assertEqual(result.status,'ok')
        self.assertIn('refinamento_skill_completed',game.calls)

    def test_active_refinement_only_closes_the_recognized_panel(self):
        root=Path(__file__).resolve().parents[1]
        active=png_frame(root/'tests/fixtures/slayer/home/refinement_active.png')
        main=png_frame(root/'tests/fixtures/slayer/home/main.png')
        screens=home_step()['screens']
        self.assertEqual(matching_screens(active,screens),['home_close_refinement'])
        skill=png_frame(root/'tests/fixtures/slayer/home/skill_panel.png')
        self.assertEqual(matching_screens(skill,screens),['home_close_skill'])
        backend=FakeBackend([active]*2+[skill]*2+[main]*2)
        time=FakeTime()
        runner=MacroRunner(backend,'Slayer Legend',False,sleep=time.sleep,clock=time.clock)
        runner.run([home_step()])
        self.assertEqual(backend.click_log,[(46,770,False),(112,784,False)])

    def test_recorded_dungeon_entries_select_the_subtab_and_preserve_rewards(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('dragao_dormente','floresta_circulacao','cave_treinoxp'):
            original=load_macro(root/f'league_bot/slayer/macros/{name}.json')
            prepared=prepare_dungeon_macro(name,original)
            self.assertEqual(prepared[1]['terminal'],'dungeon_ready')
            prefix = 7 if name == 'floresta_circulacao' else 4
            if name == 'dragao_dormente':
                self.assertEqual([s for s in prepared[2:] if s['action'] in {'click','wait'}],
                                 [s for s in original[prefix:] if s['action'] in {'click','wait'}])
                self.assertIn('dragon_free_multiplier',[s.get('terminal') for s in prepared])
            else:
                self.assertEqual(prepared[2:],original[prefix:])
            validate_steps(prepared)
            custom=[dict(s) for s in original]
            custom[2]['x']='50%'
            self.assertEqual(prepare_dungeon_macro(name,custom),custom)
            if name == 'floresta_circulacao':
                custom=[dict(s) for s in original]
                custom[5]['x']='50%'
                self.assertEqual(prepare_dungeon_macro(name,custom),custom)

    def test_trainer_keeps_its_character_entry(self):
        root=Path(__file__).resolve().parents[1]
        original=load_macro(root/'league_bot/slayer/macros/treinador.json')
        self.assertEqual(prepare_dungeon_macro('treinador',original),original)
        self.assertEqual(original[2]['x'],'5.41%')

    def test_summon_tab_and_goods_are_not_ambiguous(self):
        root=Path(__file__).resolve().parents[1]
        steps=prepare_summons(load_macro(root/'league_bot/slayer/macros/free_wpacs.json'))
        validate_steps(steps)
        summon=png_frame(root/'tests/fixtures/slayer/home/shop_summon.png')
        goods=png_frame(root/'tests/fixtures/slayer/shop/goods_after_failure.png')
        self.assertEqual(matching_screens(summon,steps[2]['screens']),['shop_summon'])
        self.assertEqual(matching_screens(goods,steps[2]['screens']),['shop_goods'])

    def test_summon_observations_preserve_recorded_clicks_and_custom_steps(self):
        root=Path(__file__).resolve().parents[1]
        original=load_macro(root/'league_bot/slayer/macros/free_wpacs.json')
        prepared=prepare_summons(original)
        markers=[s for s in prepared if s.get('summon_observe') and not s.get('summon_open_popup')]
        self.assertEqual([s['summon_observe'] for s in markers],
                         ['summon_skill','summon_sword','summon_sword',
                          'summon_accessory','summon_accessory','summon_skill'])
        for marker in markers:
            self.assertFalse(any('click' in screen for screen in marker['screens']))
        self.assertEqual(len([s for s in prepared if s.get('summon_open_popup')]),1)
        # The obsolete double navigation click is replaced with one recognized
        # popup entry. Original free claim coordinates remain in the plan.
        self.assertIn({'action':'click','x':'57.26%','y':'56.11%',
                       'summon_task':'summon_sword'}, prepared)
        custom=[dict(s) for s in original]
        custom[8]['x']='40%'
        self.assertEqual(prepare_summons(custom),custom)

    def test_summon_modal_recovery_only_closes_without_claiming(self):
        root=Path(__file__).resolve().parents[1]
        screens=home_step()['screens']
        for kind in ('weapon','accessory'):
            frame=png_frame(root/f'tests/fixtures/slayer/summons/{kind}-3.png')
            matches=matching_screens(frame,screens)
            self.assertEqual(len(matches),1)
            profile=next(s for s in screens if s['name']==matches[0])
            self.assertEqual(profile['click'],{'x':20,'y':340})

    def test_quest_modal_has_only_a_close_action(self):
        root=Path(__file__).resolve().parents[1]
        frame=png_frame(root/'tests/fixtures/slayer/home/adventurers_guild.png')
        matches=matching_screens(frame,home_step()['screens'])
        self.assertEqual(matches,['home_close_adventurers_guild'])

    def test_pet_reward_recovery_confirms_without_cleaning_again(self):
        root=Path(__file__).resolve().parents[1]
        frame=png_frame(root/'tests/fixtures/slayer/pet/reward_confirm_live.png')
        screens=home_step()['screens']
        self.assertEqual(matching_screens(frame,screens),['home_confirm_pet_reward'])
        confirm=next(s for s in screens if s['name']=='home_confirm_pet_reward')
        self.assertEqual(confirm['click'],{'x':216,'y':660})
        self.assertEqual(confirm['max_clicks'],2)
        self.assertEqual(confirm['retry_after_seconds'],3)
