import copy
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_slayer_attendance import FakeBackend, FakeTime, png_frame
from league_bot.macro import MacroError, MacroCancelled, MacroRunner
from league_bot.screens import matching_screens
from league_bot.slayer.home import home_step
from league_bot.slayer.scrolls import ScrollRunner, profiles, read_counts

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/slayer/scrolls-current.png"


def panel(counts):
    data = profiles()
    image = Image.open(FIXTURE).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box, used in zip(data["counter_boxes"], counts):
        draw.rectangle((box[0], box[1], box[2]-1, box[3]-1), fill=(0,0,0))
        mask = next(s["mask"] for s in data["counter_templates"] if s["used"] == used)
        for y, row in enumerate(mask):
            for x, value in enumerate(row):
                if value == "1":
                    image.putpixel((box[0]+2+x, box[1]+2+y), (255,255,255))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "panel.png"
        image.save(path)
        return png_frame(path)


class ScrollTests(unittest.TestCase):
    def test_counter_raster_after_window_resize(self):
        frame = png_frame(ROOT / "tests/fixtures/slayer/scrolls-window-resized-back.png")
        self.assertEqual(read_counts(frame),(2,1,1,0))

    def test_real_failure_has_exact_quotas_and_safe_close_recovery(self):
        frame = png_frame(FIXTURE)
        self.assertEqual(read_counts(frame), (2,1,1,0))
        self.assertEqual(matching_screens(frame, home_step()["screens"]), ["home_close_scrolls"])
        backend = FakeBackend([frame]*2 + [png_frame(ROOT / "tests/fixtures/slayer/home/main.png")]*2)
        clock = FakeTime()
        MacroRunner(backend, "Slayer Legend", sleep=clock.sleep, clock=clock.clock).run([home_step()])
        self.assertEqual(backend.click_log, [(217,621,False)])

    def test_no_quota_guess_for_unrecognized_frame(self):
        from league_bot.imaging import solid_frame
        self.assertIsNone(read_counts(solid_frame(434,810,(0,0,0))))
        self.assertIsNone(read_counts(solid_frame(435,810,(255,255,255))))

    def test_complete_activation_skips_exhausted_and_observes_each_increment(self):
        main = png_frame(ROOT / "tests/fixtures/slayer/home/main.png")
        # Each state supplies two frames for observation, and two before a claim.
        counts = [(2,1,1,0), (2,2,1,0), (2,2,2,0), (2,2,2,1), (2,2,2,2)]
        frames = [main]*4 + [panel(counts[0])]*4
        for i, values in enumerate(counts):
            frames += [panel(values)] * (4 if i < len(counts)-1 else 2)
        frames += [panel(counts[-1])]*2 + [main]*2
        backend, clock = FakeBackend(frames), FakeTime()
        runner = ScrollRunner(backend, "Slayer Legend", sleep=clock.sleep, clock=clock.clock)
        runner.run([dict(home_step(), daily_scrolls=True)])
        self.assertEqual(backend.click_log, [(409,175,False),(167,439,False),
            (270,439,False),(372,439,False),(372,439,False),(217,621,False)])

    def test_ad_transitions_wait_for_counter_and_do_not_repeat_reward_click(self):
        from league_bot.imaging import solid_frame
        old, new = panel((2,1,1,0)), panel((2,2,1,0))
        unknown = solid_frame(434,810,(0,0,0))
        backend = FakeBackend([unknown]*110 + [old]*2 + [new]*2)
        clock = FakeTime()
        runner = ScrollRunner(backend,"Slayer Legend",sleep=clock.sleep,clock=clock.clock)
        self.assertEqual(runner._counts(7, (2,2,1,0), timeout=120), (2,2,1,0))
        self.assertGreater(clock.now, 30)
        self.assertEqual(backend.click_log, [])

    def test_unknown_counter_timeout_never_retries_activation(self):
        backend, clock = FakeBackend([panel((2,1,1,0))]), FakeTime()
        runner = ScrollRunner(backend,"Slayer Legend",sleep=clock.sleep,clock=clock.clock)
        with self.assertRaisesRegex(MacroError,"nao repetir"):
            runner._counts(7, (2,2,1,0), timeout=1)
        self.assertEqual(backend.click_log, [])

    def test_cancellation_interrupts_ad_wait(self):
        backend, clock = FakeBackend([panel((2,1,1,0))]), FakeTime()
        runner = ScrollRunner(backend,"Slayer Legend",sleep=clock.sleep,clock=clock.clock)
        def cancel(seconds):
            runner.cancel()
            clock.sleep(seconds)
        runner._sleep = cancel
        with self.assertRaises(MacroCancelled):
            runner._counts(7, (2,2,1,0), timeout=120)


if __name__ == "__main__":
    unittest.main()
