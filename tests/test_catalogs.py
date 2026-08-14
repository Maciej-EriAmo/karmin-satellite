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
        fy = get_fleet("fy1c-debris")
        urls = fy.urls()
        self.assertTrue(any("INTDES=1999-025" in u for u in urls))
        self.assertLess(urls.index(next(u for u in urls if "INTDES=" in u)),
                        urls.index(next(u for u in urls if "GROUP=" in u)))

    def test_debris_alias_not_in_all(self):
        from engine.catalogs import (
            debris_catalog_ids,
            list_fleets,
            parse_fleet_list,
        )

        clouds = debris_catalog_ids()
        self.assertGreaterEqual(len(clouds), 5)
        self.assertEqual(parse_fleet_list("debris"), clouds)
        self.assertEqual(parse_fleet_list("space-debris"), clouds)
        all_ids = parse_fleet_list("all")
        for did in clouds:
            self.assertNotIn(did, all_ids)
        roles = {f["id"]: f.get("role") for f in list_fleets()}
        self.assertEqual(roles.get("fy1c-debris"), "debris")
        self.assertEqual(roles.get("starlink"), "fleet")

    def test_build_map_debris_offline(self):
        from engine.build import build_map

        _, amap, use, src = build_map(
            limit=20,
            hot_only=True,
            offline_demo=True,
            fleet="debris",
            backend="python",
            satcat=False,
        )
        self.assertGreater(len(use), 0)
        fleets = {s.fleet for s in use}
        self.assertTrue(any("debris" in f for f in fleets))
        self.assertTrue("offline-demo" in src)
        summ = amap.summary()
        self.assertTrue(any("debris" in k for k in (summ.get("fleets") or {})))

    def test_load_catalog_skips_failed_member(self):
        from unittest import mock

        from engine.tle import demo_tle_blob, load_catalog

        def fake_load(**kw):
            fid = kw.get("fleet") or "starlink"
            if fid == "fy1c-debris":
                raise RuntimeError("HTTP Error 503: Service Unavailable")
            return demo_tle_blob(6, fleet=fid), f"ok:{fid}"

        with mock.patch("engine.tle.load_tle_text", side_effect=fake_load):
            sats, src = load_catalog(fleet="debris", per_fleet_limit=6)
        self.assertGreater(len(sats), 0)
        self.assertTrue(any(s.fleet != "fy1c-debris" for s in sats))
        self.assertIn("fail:fy1c-debris", src)

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
