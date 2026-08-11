"""Unit tests for 50k SLA contract (fast — no capacity suite)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestSlaModule(unittest.TestCase):
    def test_public_dict_shape(self):
        from engine.sla import SLA_USABLE_SATS, SLA_VERSION, sla_public_dict

        d = sla_public_dict()
        self.assertEqual(d["version"], SLA_VERSION)
        self.assertEqual(d["design_sats"], 50_000)
        self.assertEqual(d["design_sats"], SLA_USABLE_SATS)
        self.assertEqual(d["ceiling_sats"], 100_000)
        self.assertLess(d["cold_e2e_usable_s"]["target"], d["cold_e2e_usable_s"]["hard"])
        self.assertIn("api", d)
        self.assertFalse(d["api"]["include_full_sat_positions"])

    def test_live_interval_levels(self):
        from engine.sla import evaluate_live_interval

        self.assertEqual(evaluate_live_interval(900)["level"], "ok")
        self.assertEqual(evaluate_live_interval(120)["level"], "ok_tight")
        self.assertEqual(evaluate_live_interval(30)["level"], "warn")
        bad = evaluate_live_interval(3)
        self.assertEqual(bad["level"], "forbidden")
        self.assertFalse(bad["ok"])

    def test_capacity_row_usable_pass(self):
        from engine.sla import evaluate_capacity_row

        row = {
            "n": 50_000,
            "sats": 50_000,
            "prop_errors": 0,
            "consistency_ok": True,
            "elapsed_s": 5.7,
            "peak_tracemalloc_mb": 148.0,
            "prop_ms": 2120.0,
            "export_json_bytes": 77_000,
            "cells": 1846,
        }
        ev = evaluate_capacity_row(row)
        self.assertTrue(ev["ok"], ev)
        self.assertEqual(ev["warnings"], [])

    def test_capacity_row_usable_fail_hard(self):
        from engine.sla import evaluate_capacity_row

        row = {
            "n": 50_000,
            "sats": 50_000,
            "prop_errors": 0,
            "consistency_ok": True,
            "elapsed_s": 45.0,
            "peak_tracemalloc_mb": 148.0,
            "export_json_bytes": 77_000,
            "cells": 1846,
        }
        ev = evaluate_capacity_row(row)
        self.assertFalse(ev["ok"])
        self.assertTrue(any("elapsed_s" in f for f in ev["failures"]))

    def test_capacity_row_warn_target(self):
        from engine.sla import evaluate_capacity_row

        row = {
            "n": 50_000,
            "sats": 50_000,
            "prop_errors": 0,
            "consistency_ok": True,
            "elapsed_s": 12.0,  # above target 10, below hard 30
            "peak_tracemalloc_mb": 148.0,
            "export_json_bytes": 77_000,
            "cells": 1846,
        }
        ev = evaluate_capacity_row(row)
        self.assertTrue(ev["ok"])
        self.assertTrue(any("elapsed_s" in w for w in ev["warnings"]))

    def test_api_payload_shape(self):
        from engine.sla import assert_api_payload_shape

        good = {
            "status": "ok",
            "data": {
                "density": [{"ilat": 0, "ilon": 0, "count": 3}],
                "version": 1,
            },
        }
        self.assertEqual(assert_api_payload_shape(good), [])

        bad = {
            "status": "ok",
            "data": {
                "density": [{"ilat": 0, "ilon": 0, "count": 1}],
                "sat_positions": [{"norad": 1, "lat": 0, "lon": 0}],
            },
        }
        issues = assert_api_payload_shape(bad)
        self.assertTrue(any("sat_positions" in i for i in issues))

        per_sat_density = {
            "data": {"density": [{"norad": 1, "lat": 1.0}]},
        }
        issues2 = assert_api_payload_shape(per_sat_density)
        self.assertTrue(any("norad" in i for i in issues2))

    def test_baseline_file_meets_hard_sla(self):
        """Tracked baseline must still satisfy hard SLA (regression of numbers)."""
        import json

        from engine.sla import SLA_USABLE_SATS, evaluate_capacity_row

        bas = ROOT / "docs" / "capacity_baseline.json"
        if not bas.is_file():
            self.skipTest("no capacity_baseline.json")
        report = json.loads(bas.read_text(encoding="utf-8"))
        row = next((r for r in report["rows"] if r["n"] == SLA_USABLE_SATS), None)
        self.assertIsNotNone(row, "baseline missing 50k row")
        ev = evaluate_capacity_row(row)
        self.assertTrue(ev["ok"], ev)


class TestStudioSlaEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer

        from engine.starlink_atoms import build_map
        from ui.app import StudioState, create_handler

        store, amap, use, src = build_map(
            limit=20,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        cls.state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            offline_demo=True,
            cache="out/starlink_tle_cache.txt",
        )
        handler = create_handler(cls.state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.json = json
        cls.urllib = urllib.request

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str):
        with self.urllib.urlopen(self.base + path, timeout=5) as r:
            return r.status, self.json.loads(r.read().decode("utf-8"))

    def test_api_sla_and_version(self):
        st, j = self._get("/api/sla")
        self.assertEqual(st, 200)
        self.assertEqual(j["status"], "ok")
        self.assertEqual(j["data"]["design_sats"], 50_000)
        st, v = self._get("/api/version")
        self.assertEqual(v["design_sats"], 50_000)
        self.assertIn("sla_version", v)

    def test_api_data_sla_shape(self):
        st, j = self._get("/api/data")
        self.assertEqual(st, 200)
        self.assertTrue(j.get("sla_shape_ok"), j)
        self.assertNotIn("sat_positions", j.get("data") or {})


if __name__ == "__main__":
    unittest.main()
