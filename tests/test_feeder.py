"""Faza 3: LiveFeeder start/stop + version bumps."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestLiveFeeder(unittest.TestCase):
    def test_start_stop_and_cycles(self):
        from engine.live_feeder import LiveFeeder

        n = {"i": 0}
        lock = threading.Lock()

        def refresh():
            with lock:
                n["i"] += 1
                return {"version": n["i"], "prop_ms": 0.1}

        feeder = LiveFeeder(
            refresh,
            interval_sec=1.0,
            max_fails=3,
            refresh_first=True,
            name="test-feeder",
        )
        feeder.start()
        self.assertTrue(feeder.running)
        # wait for refresh_first + at least one interval cycle
        deadline = time.time() + 4.0
        while time.time() < deadline and n["i"] < 2:
            time.sleep(0.1)
        feeder.stop(timeout=3.0)
        self.assertFalse(feeder.running)
        self.assertGreaterEqual(n["i"], 2)
        st = feeder.status()
        self.assertGreaterEqual(st["stats"]["successes"], 2)
        self.assertGreaterEqual(st["stats"]["last_version"], 2)

    def test_max_fails_stops(self):
        from engine.live_feeder import LiveFeeder

        def boom():
            raise RuntimeError("nope")

        feeder = LiveFeeder(
            boom,
            interval_sec=1.0,
            max_fails=2,
            refresh_first=True,
            name="fail-feeder",
        )
        feeder.start()
        deadline = time.time() + 5.0
        while time.time() < deadline and feeder.running:
            time.sleep(0.1)
        # should self-stop after fail streak
        time.sleep(0.3)
        self.assertFalse(feeder.running)
        self.assertGreaterEqual(feeder.stats.failures, 2)
        feeder.stop(timeout=1.0)

    def test_studio_state_feeder_bumps_version(self):
        from engine.starlink_atoms import build_map
        from ui.app import StudioState

        _, amap, use, src = build_map(
            limit=15,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        v0 = amap.version
        state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            limit=15,
            offline_demo=True,
            cache="out/starlink_tle_cache.txt",
        )
        state.attach_feeder(
            interval_sec=1.0,
            reload_tle=False,
            refresh_first=True,
        )
        deadline = time.time() + 4.0
        while time.time() < deadline and amap.version <= v0:
            time.sleep(0.1)
        self.assertGreater(amap.version, v0)
        st = state.stop_feeder()
        self.assertFalse(st.get("running", True))
        # limit preserved
        self.assertEqual(state.limit, 15)
        self.assertEqual(state.using, 15)


if __name__ == "__main__":
    unittest.main()
