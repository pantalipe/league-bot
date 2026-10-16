"""Fixture-backed tests for read-only free-summon quota observation."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import slayer_compat as la
from tests.fakes import FakeBackend, FakeTime

try:
    from test_slayer_attendance import png_frame
    _HAS_IMAGES = True
except ModuleNotFoundError:
    _HAS_IMAGES = False

if la.available():
    from league_bot.imaging import Frame
    from league_bot.macro import MacroCancelled, MacroError, MacroRunner
    from league_bot.screens import matching_screens
    from league_bot.slayer.status import DailyStatusStore
    from league_bot.slayer.shop import profiles as shop_profiles
    from league_bot.slayer.summons import (
        SummonRunner, observation_step, profiles, read_summon_menu, read_summons,
        record_summons, run_summons,
        current_cooldown, _SummonCooldown,
    )


FIXTURES = ROOT / "tests" / "fixtures" / "slayer" / "summons"
COUNTS = {"weapon": "summon_sword", "accessory": "summon_accessory", "skill": "summon_skill"}


def summon_frame(kind: str, used: int):
    return png_frame(FIXTURES / f"{kind}-{used}.png")


def current_summon_menu_frame():
    return png_frame(ROOT / "tests/fixtures/slayer/summons-current.png")


class FrameBackend(FakeBackend):
    def __init__(self, frames, *, size=(434, 810)):
        super().__init__(size=size)
        self.scripted_frames = list(frames)

    def capture(self, hwnd):
        self.calls.append(("capture",))
        if len(self.scripted_frames) > 1:
            return self.scripted_frames.pop(0)
        return self.scripted_frames[0]


class FakeStatus:
    def __init__(self, cycle="2026-10-13"):
        self.cycle = cycle
        self.tasks = {}
        self.records = []

    def cycle_id(self):
        return self.cycle

    def snapshot(self):
        return {"tasks": copy.deepcopy(self.tasks)}

    def mark_progress(self, task_id, progress, target, **kwargs):
        self.records.append((task_id, progress, target, kwargs))
        task = self.tasks.setdefault(task_id, {"progress": 0})
        task.update(progress=progress, target=target, source=kwargs.get("source"), last_error=None)


@unittest.skipUnless(la.available() and _HAS_IMAGES, "Slayer image dependencies unavailable")
class SummonReaderTests(unittest.TestCase):
    def test_current_cooldown_reads_two_used_with_different_timer_alignment(self):
        for clock in ('0918','0837'):
            frame = png_frame(FIXTURES/f'weapon-current-cooldown-{clock}.png')
            self.assertEqual(read_summons(frame),{'summon_sword':2})
            self.assertTrue(current_cooldown(frame))
        self.assertFalse(current_cooldown(summon_frame('weapon',0)))
        ready=png_frame(FIXTURES/'weapon-current-ready-2.png')
        self.assertEqual(read_summons(ready),{'summon_sword':2})
        self.assertFalse(current_cooldown(ready))

    def test_current_sword_popup_reads_three_of_three_exactly(self):
        frame = png_frame(FIXTURES/'weapon-current-cooldown-3of3.png')
        self.assertEqual(read_summons(frame), {'summon_sword': 3})

    def test_current_skill_panel_reads_one_of_three_exactly(self):
        frame=png_frame(FIXTURES/'skill-current-1of3.png')
        self.assertEqual(read_summons(frame),{'summon_skill':1})
        self.assertEqual(read_summons(png_frame(FIXTURES/'skill-current-2of3.png')),{'summon_skill':2})

    def test_current_accessory_popup_tracks_ready_and_cooldown_quotas(self):
        for used, cooldown in ((1,False),(2,True)):
            frame = png_frame(FIXTURES/f'accessory-current-{used}of3.png')
            self.assertEqual(read_summons(frame), {'summon_accessory':used})
            self.assertEqual(current_cooldown(frame), cooldown)

    def test_current_popup_can_recover_without_touching_summon_controls(self):
        from league_bot.slayer.home import home_step
        popup=png_frame(FIXTURES/'weapon-current-cooldown-0918.png')
        menu=current_summon_menu_frame()
        main=png_frame(ROOT/'tests/fixtures/slayer/home/main.png')
        backend=FrameBackend([popup]*2+[menu]*2+[main]*2)
        clock=FakeTime()
        MacroRunner(backend,'Slayer Legend',sleep=clock.sleep,clock=clock.clock).run([home_step()])
        self.assertEqual(backend.clicks(),[(20,340,False),(404,784,False)])

    def test_current_equipment_menu_is_recognized_without_inventing_a_quota(self):
        frame = current_summon_menu_frame()
        self.assertEqual(read_summon_menu(frame), "summon_equipment")
        self.assertEqual(read_summons(frame), {})
        self.assertIsNone(read_summon_menu(png_frame(ROOT / "tests/fixtures/slayer/home/main.png")))

    def test_shop_summon_navigation_profile_matches_old_and_current_renderings(self):
        profile = json.loads((ROOT / "league_bot/slayer/assets/summon-navigation.json").read_text())
        goods = next(screen for screen in shop_profiles()["screens"] if screen["name"] == "shop_goods")
        for frame in (current_summon_menu_frame(), png_frame(ROOT / "tests/fixtures/slayer/home/shop_summon.png")):
            with self.subTest(frame=frame):
                self.assertEqual(matching_screens(frame, [goods, profile]), ["shop_summon"])

    def test_all_labelled_counter_fixtures_read_as_used_counts(self):
        for kind, task in COUNTS.items():
            for used in (0, 1, 3):
                with self.subTest(kind=kind, used=used):
                    self.assertEqual(read_summons(summon_frame(kind, used)), {task: used})

    def test_wrong_panel_geometry_unfamiliar_bitmap_and_conflicting_templates_are_unknown(self):
        self.assertEqual(read_summons(png_frame(ROOT / "tests/fixtures/slayer/home/main.png")), {})
        original = summon_frame("skill", 1)
        self.assertEqual(read_summons(Frame(original.width - 1, original.height, original.bgr)), {})

        data = profiles()
        row = copy.deepcopy(data["counter_templates"]["panel"][1])
        row["used"] = 2
        data["counter_templates"]["panel"].append(row)
        self.assertEqual(read_summons(summon_frame("skill", 1), data), {})

        # A pixel change inside the calibrated counter must not be rounded to
        # the nearest supported digit mask.
        pixels = bytearray(original.bgr)
        stride = ((original.width * 3 + 3) // 4) * 4
        x, y = 400, 661
        offset = (original.height - 1 - y) * stride + x * 3
        pixels[offset:offset + 3] = bytes((0, 0, 0))
        self.assertEqual(read_summons(Frame(original.width, original.height, bytes(pixels))), {})


@unittest.skipUnless(la.available() and _HAS_IMAGES, "Slayer image dependencies unavailable")
class SummonRecordingTests(unittest.TestCase):
    def test_visual_progress_never_reduces_a_higher_manual_count(self):
        status = FakeStatus()
        status.tasks["summon_sword"] = {"progress": 2, "source": "manual"}
        record_summons(status, {"summon_sword": 1}, status.cycle_id())
        self.assertEqual(status.records, [])

    def test_equal_visual_progress_is_not_written_again(self):
        status = FakeStatus()
        status.tasks["summon_skill"] = {"progress": 1, "source": "visual", "last_error": None}
        record_summons(status, {"summon_skill": 1}, status.cycle_id())
        self.assertEqual(status.records, [])

    def test_cycle_change_refuses_to_record_stale_observation(self):
        status = FakeStatus()
        expected = status.cycle_id()
        status.cycle = "2026-10-14"
        with self.assertRaises(MacroCancelled):
            record_summons(status, {"summon_accessory": 1}, expected)
        self.assertEqual(status.records, [])

    def test_real_store_manual_higher_progress_survives_visual_observation(self):
        now = [datetime(2026, 10, 13, 12, tzinfo=timezone(timedelta(hours=-3)))]
        with tempfile.TemporaryDirectory() as tmp:
            store = DailyStatusStore(Path(tmp) / "daily.json", now=lambda: now[0])
            cycle = store.cycle_id()
            store.mark_progress("summon_sword", 2, 3, source="manual")
            record_summons(store, {"summon_sword": 1}, cycle)
            self.assertEqual(store.snapshot()["tasks"]["summon_sword"]["progress"], 2)
            self.assertEqual(store.snapshot()["tasks"]["summon_sword"]["source"], "manual")


@unittest.skipUnless(la.available() and _HAS_IMAGES, "Slayer image dependencies unavailable")
class SummonObserverTests(unittest.TestCase):
    def make_runner(self, frames, *, status=None, time=None):
        self.time = time or FakeTime()
        self.backend = FrameBackend(frames)
        self.runner = SummonRunner(
            self.backend, "Slayer Legend", foreground=True,
            sleep=self.time.sleep, clock=self.time.clock,
            store=status, cycle=status.cycle_id() if status else None,
        )
        return self.runner

    def test_stable_known_observation_records_used_count_without_clicking(self):
        status = FakeStatus()
        runner = self.make_runner([summon_frame("skill", 1)], status=status)
        runner.run([observation_step("summon_skill")])
        self.assertEqual(status.records[0][0:3], ("summon_skill", 1, 3))
        self.assertEqual(self.backend.clicks(), [])

    def test_skill_video_without_confirmed_increment_is_never_repeated(self):
        frame=png_frame(FIXTURES/'skill-current-1of3.png')
        runner=self.make_runner([frame])
        step=dict(observation_step('summon_skill'),summon_claim_skill=True)
        with self.assertRaisesRegex(MacroError,'nao repetir anuncio'):
            runner.run([step])
        self.assertEqual(self.backend.clicks(),[(378,646,False)])

    def test_exhausted_skill_does_not_click_video(self):
        runner=self.make_runner([summon_frame('skill',3)])
        runner.run([dict(observation_step('summon_skill'),summon_claim_skill=True)])
        self.assertEqual(self.backend.clicks(),[])

    def test_skill_reward_confirms_once_and_records_only_the_observed_increment(self):
        before=png_frame(FIXTURES/'skill-current-1of3.png')
        reward=png_frame(FIXTURES/'skill_reward_current.png')
        after=png_frame(FIXTURES/'skill-current-2of3.png')
        status=FakeStatus()
        runner=self.make_runner([before]*2+[reward]*2+[after]*2,status=status)
        with self.assertRaises(_SummonCooldown):
            runner.run([dict(observation_step('summon_skill'),summon_claim_skill=True)])
        self.assertEqual(self.backend.clicks(),[(378,646,False),(218,765,False)])
        self.assertEqual(status.tasks['summon_skill']['progress'],2)

    def test_cooldown_on_an_exhausted_quota_does_not_defer_other_summons(self):
        from unittest.mock import patch
        runner=self.make_runner([summon_frame('accessory',3)])
        with patch('league_bot.slayer.summons.current_cooldown',return_value=True):
            runner._cooldown(summon_frame('accessory',3))

    def test_exhausted_task_closes_popup_skips_only_its_claims_and_continues(self):
        sword = png_frame(FIXTURES/'weapon-current-cooldown-3of3.png')
        menu = current_summon_menu_frame()
        frames = [sword]*2 + [menu]*4 + [summon_frame('accessory',0)]*2 + [summon_frame('skill',1)]*2
        runner = self.make_runner(frames)
        runner.run([
            observation_step('summon_sword', exhausted_branch=True),
            {'action':'click','x':10,'y':20,'summon_task':'summon_sword'},
            observation_step('summon_sword', exhausted_branch=True),
            {'action':'click','x':30,'y':40,'summon_task':'summon_sword'},
            observation_step('summon_accessory', exhausted_branch=True),
            {'action':'click','x':50,'y':60,'summon_task':'summon_accessory'},
            observation_step('summon_skill', exhausted_branch=True),
            {'action':'click','x':70,'y':80,'summon_task':'summon_skill'},
            {'action':'click','x':90,'y':100},
        ])
        self.assertEqual(self.backend.clicks(),[(20,340,False),(50,60,True),(70,80,True),(90,100,True)])

    def test_quotas_below_three_keep_the_recorded_claim_path(self):
        frames={0:summon_frame('weapon',0),1:summon_frame('weapon',1),
                2:png_frame(FIXTURES/'weapon-current-ready-2.png')}
        for used,frame in frames.items():
            with self.subTest(used=used):
                runner=self.make_runner([frame]*2)
                runner.run([observation_step('summon_sword',exhausted_branch=True),
                            {'action':'click','x':12,'y':34,'summon_task':'summon_sword'}])
                self.assertEqual(self.backend.clicks(),[(12,34,True)])

    def test_known_recording_tags_only_task_claim_segments(self):
        from league_bot.macro import load_macro
        from league_bot.slayer.dungeon_navigation import prepare_summons
        known=load_macro(ROOT/'league_bot/slayer/macros/free_wpacs.json')
        steps=prepare_summons(known)
        by_click={(step.get('x'),step.get('y')):step for step in steps if step['action']=='click'}
        self.assertEqual(by_click[('57.26%','56.11%')].get('summon_task'),'summon_sword')
        self.assertEqual(by_click[('51.04%','57.47%')].get('summon_task'),'summon_accessory')
        self.assertNotIn(('87.21%','79.81%'),by_click)
        self.assertEqual(len([s for s in steps if s.get('summon_claim_skill')]),1)
        self.assertNotIn('summon_task',by_click[('92.05%','96.85%')])
        # Opening the next popup belongs to navigation, never to the exhausted
        # task's claim block. Otherwise sword 3/3 would also skip Accessories.
        accessory_entry = [s for s in steps if s['action'] == 'click'
                           and s.get('x') == '91.13%']
        self.assertEqual(accessory_entry, [])
        self.assertEqual(len([s for s in steps if s.get('summon_open_popup') == 'summon_accessory']), 1)
        markers=[s for s in steps if s.get('summon_observe') and not s.get('summon_allow_menu')
                 and not s.get('summon_open_popup') and not s.get('summon_claim_skill')]
        self.assertTrue(all(m.get('summon_exhausted_branch') for m in markers))

    def test_accessory_entry_opens_once_only_from_recognized_menu(self):
        from league_bot.slayer.summons import popup_entry_step
        runner = self.make_runner([current_summon_menu_frame()]*2)
        runner.run([popup_entry_step('summon_accessory')])
        self.assertEqual(self.backend.clicks(), [(385,512,False)])
        from league_bot.imaging import solid_frame
        runner = self.make_runner([solid_frame(434,810,(0,0,0))])
        with self.assertRaisesRegex(MacroError, 'desconhecido'):
            runner.run([popup_entry_step('summon_accessory')])
        self.assertEqual(self.backend.clicks(), [])

    def test_unfamiliar_screen_times_out_unknown_without_false_completion_or_click(self):
        status = FakeStatus()
        unknown = png_frame(ROOT / "tests/fixtures/slayer/home/main.png")
        runner = self.make_runner([unknown], status=status)
        with self.assertRaisesRegex(MacroError,'sem leitura visual segura'):
            runner.run([observation_step("summon_skill"),{'action':'click','x':248,'y':454}])
        self.assertEqual(status.records, [])
        self.assertEqual(self.backend.clicks(), [])

    def test_cooldown_during_a_pixel_wait_defers_before_any_claim(self):
        popup=png_frame(FIXTURES/'weapon-current-cooldown-0918.png')
        from league_bot.imaging import solid_frame
        unknown=solid_frame(434,810,(0,0,0))
        status=FakeStatus()
        runner=self.make_runner([unknown,popup,popup],status=status)
        with self.assertRaises(_SummonCooldown):
            runner.run([{'action':'wait_for_pixel','x':395,'y':516,'color':[67,67,67],
                         'timeout':30,'poll_seconds':.3}, {'action':'click','x':248,'y':454}])
        self.assertEqual(status.records[0][0:3],('summon_sword',2,3))
        self.assertEqual(self.backend.clicks(),[])
        self.assertLess(self.time.clock(),2)

    def test_run_summons_recovers_cooldown_and_returns_pending_without_completing_macro(self):
        from league_bot.config import Settings
        from league_bot.slayer.game import SlayerDailyGame
        popup=png_frame(FIXTURES/'weapon-current-cooldown-0918.png')
        menu=current_summon_menu_frame()
        main=png_frame(ROOT/'tests/fixtures/slayer/home/main.png')
        backend=FrameBackend([popup]*4+[menu]*2+[main]*2)
        clock,status=FakeTime(),FakeStatus()
        with tempfile.TemporaryDirectory() as tmp:
            game=SlayerDailyGame(Settings(window_title='Slayer Legend',data_dir=Path(tmp)),backend,
                status_store=status,runner_factory=lambda b,t,f,l:MacroRunner(b,t,f,l,
                    sleep=clock.sleep,clock=clock.clock))
            original=game._runner_factory
            game.load_macro_steps=lambda name:[dict(action='wait_for_pixel',x=395,y=516,
                color=[67,67,67],timeout=30,poll_seconds=.3)]
            result=run_summons(game)
            self.assertTrue(result.skipped)
            self.assertIn('intervalo',str(result))
            self.assertIn('2/3',str(result))
            self.assertIs(game._runner_factory,original)
        self.assertEqual(backend.clicks(),[(20,340,False),(404,784,False)])
        self.assertEqual([r[:3] for r in status.records],[('summon_sword',2,3)])

    def test_equipment_menu_stops_before_recorded_paid_summon_click(self):
        runner = self.make_runner([current_summon_menu_frame()])
        paid_summon = {"action": "click", "x": "57.26%", "y": "56.11%"}
        with self.assertRaisesRegex(MacroError, "clique registrado nao autorizado"):
            runner.run([observation_step("summon_sword"), paid_summon])
        self.assertEqual(self.backend.clicks(), [])

    def test_unknown_current_popup_quota_stops_before_recorded_claim(self):
        frame=png_frame(FIXTURES/'weapon-current-ready-2.png')
        pixels=bytearray(frame.bgr)
        offset=(frame.height-1-410)*frame.row_size+171*3
        pixels[offset:offset+3]=bytes((255,255,255))
        unknown=Frame(frame.width,frame.height,bytes(pixels))
        self.assertEqual(read_summons(unknown),{})
        self.assertFalse(current_cooldown(unknown))
        runner=self.make_runner([unknown])
        with self.assertRaisesRegex(MacroError,'sem leitura visual segura'):
            runner.run([observation_step('summon_sword'),dict(action='click',x=248,y=454)])
        self.assertEqual(self.backend.clicks(),[])

    def test_initial_menu_observation_allows_the_free_video_branch(self):
        runner = self.make_runner([current_summon_menu_frame()])
        runner.run([observation_step("summon_skill", allow_menu=True)])
        self.assertEqual(self.backend.clicks(), [])

    def test_cancellation_and_cycle_rollover_stop_observation_without_clicks(self):
        runner = self.make_runner([summon_frame("skill", 1)])
        runner.cancel()
        with self.assertRaises(MacroCancelled):
            runner.run([observation_step("summon_skill")])
        self.assertEqual(self.backend.clicks(), [])

        status = FakeStatus()
        clock = FakeTime()
        class RolloverTime(FakeTime):
            def sleep(inner, seconds):
                super(RolloverTime, inner).sleep(seconds)
                status.cycle = "2026-10-14"
        clock = RolloverTime()
        runner = self.make_runner([summon_frame("skill", 1)], status=status, time=clock)
        with self.assertRaises(MacroCancelled):
            runner.run([observation_step("summon_skill")])
        self.assertEqual(status.records, [])
        self.assertEqual(self.backend.clicks(), [])

    def test_run_factory_is_restored_after_macro_failure(self):
        class GameStub:
            def __init__(self):
                self._runner_factory = lambda *args: MacroRunner(*args)
                self.original_factory = self._runner_factory
                self._status_store = FakeStatus()
                self.entered = False
            @contextmanager
            def _exclusive(self):
                yield
            def load_macro_steps(self, name):
                self.asserted_name = name
                return []
            def _title(self):
                return "Slayer Legend"
            def _run_steps(self, *args):
                self.entered = True
                raise RuntimeError("macro failed")
        game = GameStub()
        with self.assertRaisesRegex(RuntimeError, "macro failed"):
            run_summons(game)
        self.assertTrue(game.entered)
        self.assertIs(game._runner_factory, game.original_factory)
