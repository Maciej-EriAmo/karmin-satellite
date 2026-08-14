"""W5: mini system_tick + decisions — density SoT intact."""
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


def _two_fleets():
    from engine.build import build_map
    from engine.tle import TleSat, build_demo_catalog

    a = build_demo_catalog(12, fleet="starlink")
    b = build_demo_catalog(12, fleet="oneweb")
    b2 = [
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
            fleet="oneweb",
        )
        for s in b
    ]
    return build_map(
        catalog=a + b2,
        src="tick-test:2f",
        limit=0,
        hot_only=True,
        offline_demo=True,
        backend="python",
        satcat=False,
    )


class TestSystemTickStudio(unittest.TestCase):
    def test_empty_fleet_note_and_density_sot(self):
        from engine.reach_studio import set_session_scope, studio_system_tick

        _, amap, _, _ = _two_fleets()
        set_session_scope(amap, fleet="starlink")
        dens0 = dict(amap.density)
        v0 = amap.version
        out = studio_system_tick(amap, settle_local=0)
        self.assertEqual(dict(amap.density), dens0)
        self.assertEqual(out["ticked"], 0)
        self.assertTrue(out["advisory"])
        self.assertEqual(amap.version, v0)
        notes = [
            d
            for d in out["decisions"]
            if d.get("action") == "note" and "empty" in (d.get("reason") or "")
        ]
        self.assertGreaterEqual(len(notes), 1)
        self.assertTrue(any("oneweb" in str(d.get("node")) for d in notes))
        self.assertLessEqual(len(out["log"]), 10)
        self.assertIn("session:default", out["nodes"])

    def test_settle_does_not_rewrite_density(self):
        from engine.reach_studio import studio_system_tick

        _, amap, _, _ = _two_fleets()
        dens0 = dict(amap.density)
        v0 = amap.version
        out = studio_system_tick(amap, settle_local=1)
        self.assertEqual(dict(amap.density), dens0)
        self.assertGreater(out["version"], v0)


class TestSystemTickAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.app import StudioState, create_handler

        _store, amap, use, src = _two_fleets()
        cls.amap = amap
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

    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _post(self, path: str, body: dict):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_tick_and_decisions(self):
        dens_n = len(self.amap.density)
        st, j = self._post("/api/system_tick", {"settle_local": 0})
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(j["data"]["decisions"]), 3)
        self.assertEqual(len(self.amap.density), dens_n)
        st, j2 = self._get("/api/decisions")
        self.assertEqual(st, 200)
        self.assertGreaterEqual(len(j2["data"]["log"]), 1)

    def test_index_has_tick_and_resonance(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        self.assertIn("btn-tick-wow", html)
        self.assertIn("resonance-q", html)
        self.assertIn("decisions-panel", html)


if __name__ == "__main__":
    unittest.main()
