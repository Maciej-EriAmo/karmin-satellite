"""Delta View — compare_density cells + sats + hazard helpers."""
from __future__ import annotations

import unittest

from engine.analytics import compare_density, compare_hazard, compare_sats


class TestDeltaCompare(unittest.TestCase):
    def test_cells_changed_kinds(self):
        a = {
            "density": [
                {"ilat": 1, "ilon": 2, "count": 3},
                {"ilat": 5, "ilon": 5, "count": 2},
            ],
            "nlat": 36,
            "nlon": 72,
        }
        b = {
            "density": [
                {"ilat": 1, "ilon": 2, "count": 5},  # grew
                {"ilat": 9, "ilon": 9, "count": 1},  # appeared
            ],
            "nlat": 36,
            "nlon": 72,
        }
        d = compare_density(a, b)
        self.assertEqual(d["appeared"], 1)
        self.assertEqual(d["vanished"], 1)
        self.assertEqual(d["grew"], 1)
        kinds = {c["kind"] for c in d["cells_changed"]}
        self.assertIn("appeared", kinds)
        self.assertIn("vanished", kinds)
        self.assertIn("grew", kinds)
        self.assertTrue(d["cells_changed"])

    def test_sats_lost(self):
        a = {"sats": [{"norad": 1}, {"norad": 2}, {"norad": 3}]}
        b = {"sats": [{"norad": 2}, {"norad": 9}]}
        s = compare_sats(a, b)
        self.assertTrue(s["available"])
        self.assertEqual(s["lost_n"], 2)
        self.assertEqual(s["gained_n"], 1)
        self.assertIn(1, s["lost"])
        self.assertIn(3, s["lost"])
        self.assertIn(9, s["gained"])

    def test_hazard_delta(self):
        a = {"solar": {"hazard": {"global_score": 10, "severity": "low"}}}
        b = {"solar": {"hazard": {"global_score": 40, "severity": "elevated"}}}
        h = compare_hazard(a, b)
        self.assertTrue(h["available"])
        self.assertAlmostEqual(h["delta_score"], 30.0)


if __name__ == "__main__":
    unittest.main()
