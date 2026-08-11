"""Minimal smoke: substrate import + offline map."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestSmoke(unittest.TestCase):
    def test_open_store(self):
        from karmazyn_kernel import T_INIT, open_store

        store = open_store(thermal=True, backend="python")
        self.assertIsNotNone(store)
        store.create_atom("smoke:1", S="test", E="x", T=T_INIT)
        self.assertTrue(store.has_atom("smoke:1"))

    def test_offline_map(self):
        from engine.starlink_atoms import build_map

        store, amap, use, src = build_map(
            limit=12,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        self.assertGreater(len(use), 0)
        summ = amap.summary()
        self.assertGreater(summ.get("sats", 0), 0)
        self.assertIn("offline", src)
        self.assertGreaterEqual(amap.version, 1)


if __name__ == "__main__":
    unittest.main()
