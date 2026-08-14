"""Storm thresholds + crowding counts (no Pc, no extra equation)."""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestStormAlert(unittest.TestCase):
    def test_quiet_no_alert(self):
        from engine.event_alert import assess_storm

        out = assess_storm(
            {"kp": 1.2, "flare_letter": "A", "global_score": 18},
            {"horizons": [{"label": "6h", "kp": 1.0, "flare_letter": "A", "global_score": 16}]},
        )
        self.assertFalse(out["alert"])
        self.assertEqual(out["kind"], "quiet")

    def test_kp_now_watch(self):
        from engine.event_alert import assess_storm

        out = assess_storm({"kp": 5.4, "flare_letter": "C", "global_score": 40})
        self.assertTrue(out["alert"])
        self.assertIn(out["kind"], ("now", "forecast"))

    def test_6h_kp_watch(self):
        from engine.event_alert import assess_storm

        out = assess_storm(
            {"kp": 3.0, "flare_letter": "B", "global_score": 30},
            {"horizons": [{"label": "6h", "kp": 6.0, "flare_letter": "C", "global_score": 60}]},
        )
        self.assertTrue(out["alert"])
        self.assertEqual(out["kind"], "rising")
        self.assertEqual(out["kp_6h"], 6.0)

    def test_mix_does_not_fire_storm(self):
        from engine.build import build_map
        from engine.event_alert import assess_event_alert
        from engine.tle import TleSat, build_demo_catalog

        ops = build_demo_catalog(6, fleet="starlink")
        raw = build_demo_catalog(6, fleet="fy1c-debris")
        deb = [
            TleSat(
                name=s.name,
                line1=s.line1,
                line2=s.line2,
                norad=s.norad + 50_000,
                inclination_deg=s.inclination_deg,
                raan_deg=s.raan_deg,
                mean_anomaly_deg=s.mean_anomaly_deg,
                mean_motion_rev_per_day=s.mean_motion_rev_per_day,
                ecc=s.ecc,
                fleet="fy1c-debris",
            )
            for s in raw
        ]
        _, amap, _, _ = build_map(
            catalog=ops + deb,
            src="mix-only",
            limit=0,
            hot_only=True,
            offline_demo=True,
            backend="python",
            satcat=False,
        )
        amap.cell_to_sats = {(1, 1): {f"sat:{ops[0].norad}", f"sat:{deb[0].norad}"}}
        out = assess_event_alert(
            amap,
            weather={"kp": 1.0, "flare_letter": "A", "global_score": 15},
        )
        self.assertEqual(out["crowding"]["mixed"], 1)
        self.assertFalse(out["alert"])


class TestEventAlertAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from engine.build import build_map
        from ui.app import StudioState, create_handler

        _, amap, use, src = build_map(
            limit=12,
            offline_demo=True,
            hot_only=True,
            backend="python",
            satcat=False,
        )
        cls.state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            offline_demo=True,
        )
        handler = create_handler(cls.state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_alert_endpoint_and_chrome(self):
        with urllib.request.urlopen(self.base + "/api/alert?offline=1", timeout=8) as r:
            j = json.loads(r.read().decode("utf-8"))
        self.assertEqual(j["status"], "ok")
        self.assertIn("alert", j["data"])
        self.assertIn("kp", j["data"])
        self.assertIn("crowding", j["data"])
        blob = json.dumps(j["data"]).lower()
        self.assertNotIn("anticipation", blob)
        self.assertNotIn("collision", blob)
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        self.assertIn("event-alert", html)


if __name__ == "__main__":
    unittest.main()
