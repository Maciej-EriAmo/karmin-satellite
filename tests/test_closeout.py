"""Close-out tests: SATCAT country (A), timeline analytics (B)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestSatcatCountry(unittest.TestCase):
    def test_fleet_heuristic_and_filter(self):
        from engine.satcat import (
            FLEET_COUNTRY,
            SatcatIndex,
            country_counts,
            filter_by_country,
            parse_satcat_csv,
        )
        from engine.tle import build_demo_catalog

        self.assertEqual(FLEET_COUNTRY["starlink"], "US")
        csv = "NORAD_CAT_ID,COUNTRY\n25544,US\n43013,UK\n"
        m = parse_satcat_csv(csv)
        self.assertEqual(m[25544], "US")
        self.assertEqual(m[43013], "UK")

        sats = build_demo_catalog(10, fleet="oneweb")
        idx = SatcatIndex(allow_network=False)
        idx._map = {}
        idx.annotate_sats(sats)
        self.assertTrue(all(s.country == "UK" for s in sats))
        us_only = filter_by_country(sats, "US")
        self.assertEqual(len(us_only), 0)
        uk = filter_by_country(sats, "uk")
        self.assertEqual(len(uk), 10)
        self.assertIn("UK", country_counts(sats))

    def test_build_map_country_offline(self):
        from engine.build import build_map

        _, amap, use, src = build_map(
            limit=20,
            offline_demo=True,
            fleet="starlink",
            country="US",
            hot_only=True,
            backend="python",
        )
        self.assertGreater(len(use), 0)
        self.assertTrue(all((s.country or "").upper() == "US" for s in use))
        self.assertIn("country=US", src)
        self.assertIn("US", amap.summary().get("countries") or {})


class TestTimelineAnalytics(unittest.TestCase):
    def test_metrics_and_compare(self):
        from engine.analytics import compare_density, snapshot_metrics

        a = {
            "snapshot_id": "a",
            "created_at": "t0",
            "density": [
                {"ilat": 1, "ilon": 2, "count": 3},
                {"ilat": 2, "ilon": 2, "count": 1},
            ],
            "shells": {"shell:53": 4},
        }
        b = {
            "snapshot_id": "b",
            "created_at": "t1",
            "density": [
                {"ilat": 1, "ilon": 2, "count": 5},
                {"ilat": 3, "ilon": 3, "count": 2},
            ],
            "shells": {},
            "solar": {"hazard": {"global_score": 30, "severity": "INFO"}},
        }
        ma = snapshot_metrics(a)
        self.assertEqual(ma["cells"], 2)
        self.assertEqual(ma["sum_count"], 4)
        d = compare_density(a, b)
        self.assertEqual(d["delta_sum_count"], 3)  # 5+2 - 3-1
        self.assertGreaterEqual(d["appeared"], 1)
        self.assertGreaterEqual(d["vanished"], 1)

    def test_timeline_store(self):
        from adapters.snapshot_store import SnapshotStore
        from engine.analytics import timeline_from_store
        from engine.build import build_map

        _, amap, use, src = build_map(
            limit=15,
            offline_demo=True,
            hot_only=True,
            backend="python",
        )
        with tempfile.TemporaryDirectory() as td:
            store = SnapshotStore(Path(td), retention_days=0)
            store.save(amap, snapshot_id="t1", src=src, using=len(use), prune=False)
            store.save(amap, snapshot_id="t2", src=src, using=len(use), prune=False)
            frames = timeline_from_store(store, limit=10)
            self.assertEqual(len(frames), 2)
            self.assertIn("sum_count", frames[0])


if __name__ == "__main__":
    unittest.main()
