"""H7 multi-fleet catalog unit tests (offline, no network)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestCatalogs(unittest.TestCase):
    def test_list_and_parse(self):
        from engine.catalogs import get_fleet, list_fleets, parse_fleet_list

        fleets = list_fleets()
        self.assertGreaterEqual(len(fleets), 5)
        ids = {f["id"] for f in fleets}
        self.assertIn("starlink", ids)
        self.assertIn("oneweb", ids)
        self.assertEqual(parse_fleet_list("starlink,oneweb"), ["starlink", "oneweb"])
        self.assertEqual(parse_fleet_list("a+b"), ["a", "b"])
        self.assertEqual(get_fleet("oneweb").group, "oneweb")

    def test_offline_load_single_and_merge(self):
        from engine.tle import load_catalog

        sats, src = load_catalog(
            fleet="oneweb",
            offline_demo=True,
            limit_hint=20,
        )
        self.assertEqual(len(sats), 20)
        self.assertTrue(all(s.fleet == "oneweb" for s in sats))
        self.assertIn("oneweb", src)

        merged, src2 = load_catalog(
            fleet="starlink,oneweb",
            offline_demo=True,
            limit_hint=15,
            per_fleet_limit=10,
        )
        # 10+10 with fleet-offset NORADs
        self.assertEqual(len(merged), 20)
        fleets = {s.fleet for s in merged}
        self.assertEqual(fleets, {"starlink", "oneweb"})
        self.assertIn("multi:", src2)

    def test_build_map_fleet_offline(self):
        from engine.build import build_map

        _, amap, use, src = build_map(
            limit=25,
            hot_only=True,
            offline_demo=True,
            fleet="iridium",
            backend="python",
        )
        self.assertEqual(len(use), 25)
        self.assertTrue(all(s.fleet == "iridium" for s in use))
        self.assertIn("iridium", src)
        summ = amap.summary()
        self.assertIn("fleets", summ)
        self.assertIn("iridium", summ["fleets"])


if __name__ == "__main__":
    unittest.main()
