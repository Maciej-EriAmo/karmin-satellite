"""Faza 0–1: consistency, snapshot, filter, GC, concurrent refresh."""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestEnginePhase01(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from engine.starlink_atoms import build_map

        cls.build_map = staticmethod(build_map)

    def _map(self, limit: int = 20):
        store, amap, use, src = self.build_map(
            limit=limit,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        return store, amap, use, src

    def test_density_cell_consistency(self):
        _, amap, use, _ = self._map(24)
        check = amap.density_cell_consistency()
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["missing_atoms"], 0)
        self.assertEqual(check["ghost_atoms"], 0)
        self.assertGreater(len(use), 0)
        self.assertGreater(amap.version, 0)

    def test_snapshot_shape(self):
        _, amap, _, _ = self._map(16)
        snap = amap.snapshot()
        self.assertIn("version", snap)
        self.assertIn("density", snap)
        self.assertIn("cells", snap)
        self.assertIn("summary", snap)
        self.assertEqual(len(snap["density"]), len(amap.density))
        self.assertEqual(snap["version"], amap.version)
        self.assertEqual(snap["policy"], "hot-only")

    def test_filter_min_count_and_shell(self):
        _, amap, use, _ = self._map(30)
        all_f = amap.filter_density(shell="all", min_count=1)
        self.assertGreaterEqual(all_f["count_cells"], 1)
        self.assertEqual(all_f["version"], amap.version)

        # Offline demo sats are shell:53
        sh = amap.filter_density(shell="53", min_count=1)
        self.assertEqual(sh["shell"], "shell:53")
        self.assertGreaterEqual(sh["count_sats"], 1)

        empty = amap.filter_density(shell="99", min_count=1)
        self.assertEqual(empty["count_cells"], 0)
        self.assertEqual(empty["count_sats"], 0)

        hi = amap.filter_density(shell="all", min_count=10_000)
        self.assertEqual(hi["count_cells"], 0)

    def test_sat_gc_on_refresh(self):
        _, amap, use, _ = self._map(20)
        self.assertEqual(amap.summary()["sats"], len(use))
        half = list(use[:10])
        stats = amap.refresh(half, ensure=True)
        self.assertEqual(amap.summary()["sats"], 10)
        self.assertGreaterEqual(stats.get("gc_sats", 0), 1)
        # shells rebuilt
        self.assertEqual(sum(amap._shells.values()), 10)

    def test_sgp4_failure_is_error_not_silent_approx(self):
        from engine.prop import position_of
        from engine.tle import build_demo_catalog

        sat = build_demo_catalog(1)[0]
        sat.line1 = "1 00000U junk"
        sat.line2 = "2 00000 junk"
        sat._satrec = None
        with self.assertRaises(Exception):
            position_of(sat, mode="sgp4")

    def test_reingest_preserves_shell_counts(self):
        _, amap, use, _ = self._map(12)
        s1 = dict(amap._shells)
        amap.ingest_sats(use, gc_missing=False)
        s2 = dict(amap._shells)
        self.assertEqual(s1, s2)

    def test_concurrent_snapshot_vs_refresh(self):
        _, amap, use, _ = self._map(25)
        errors: list = []
        stop = threading.Event()

        def refresher():
            try:
                for _ in range(40):
                    if stop.is_set():
                        break
                    amap.refresh(use, ensure=True)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(80):
                    if stop.is_set():
                        break
                    snap = amap.snapshot()
                    assert "version" in snap
                    amap.filter_density(shell="all", min_count=1)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=refresher),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        stop.set()
        self.assertEqual(errors, [], errors)
        self.assertGreater(amap.version, 0)


if __name__ == "__main__":
    unittest.main()
