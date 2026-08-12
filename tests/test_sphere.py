"""Faza 4: sphere export from density."""
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


class TestSphere(unittest.TestCase):
    def test_export_sphere_shape(self):
        from engine.build import build_map
        from transform.sphere import export_sphere_data

        _, amap, use, _ = build_map(
            limit=20,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        data = export_sphere_data(amap)
        self.assertEqual(data["projection"], "sphere")
        self.assertEqual(data["layer"], "density")
        self.assertGreater(len(data["cells"]), 0)
        c0 = data["cells"][0]
        self.assertEqual(len(c0["quad"]), 4)
        self.assertEqual(len(c0["quad"][0]), 3)
        self.assertIn("color", c0)
        self.assertEqual(data["meta"]["count_cells"], len(data["cells"]))
        # density SoT
        self.assertEqual(len(data["cells"]), len(amap.density))

    def test_export_radiation_layer(self):
        from engine.build import build_map
        from engine.solar import assess_hazard
        from transform.sphere import export_sphere_data, radiation_to_rgb

        r, g, b = radiation_to_rgb(80.0, 100.0)
        self.assertGreater(r, 100)
        self.assertIsInstance(b, int)

        _, amap, _, _ = build_map(
            limit=20,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        weather = {
            "as_of": "t",
            "flare_letter": "M",
            "flare_mag": 2.0,
            "flare_class": "M2.0",
            "f107": 150.0,
            "kp": 5.0,
            "mode": "stub",
            "source": "test",
        }
        haz = assess_hazard(
            weather,
            shells=dict(amap.summary().get("shells") or {}),
            total_sats=int(amap.summary().get("sats") or 20),
        )
        data = export_sphere_data(amap, layer="radiation", assessment=haz)
        self.assertEqual(data["layer"], "radiation")
        self.assertGreater(len(data["cells"]), 0)
        c0 = data["cells"][0]
        self.assertIn("exposure", c0)
        self.assertIn("opacity", c0)
        self.assertGreaterEqual(c0["exposure"], 0)
        self.assertIsNotNone(data["solar"]["base_score"])
        self.assertGreater(data["solar"]["max_exposure"], 0)

        blend = export_sphere_data(amap, layer="blend", assessment=haz)
        self.assertEqual(blend["layer"], "blend")
        self.assertIn("exposure", blend["cells"][0])

    def test_api_sphere(self):
        from engine.build import build_map
        from ui.app import StudioState, create_handler

        _, amap, use, src = build_map(
            limit=16,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            limit=16,
            offline_demo=True,
            studio_mode="3d",
        )
        handler = create_handler(state)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/sphere", timeout=5
            ) as r:
                j = json.loads(r.read().decode("utf-8"))
            self.assertEqual(j["status"], "ok")
            self.assertEqual(j["data"]["projection"], "sphere")
            self.assertGreater(len(j["data"]["cells"]), 0)

            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/sphere?layer=radiation&offline=1",
                timeout=8,
            ) as r:
                j2 = json.loads(r.read().decode("utf-8"))
            self.assertEqual(j2["status"], "ok")
            self.assertEqual(j2["data"]["layer"], "radiation")
            self.assertIn("exposure", j2["data"]["cells"][0])
            self.assertIn("solar", j2["data"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
