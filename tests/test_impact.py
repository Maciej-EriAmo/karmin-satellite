"""W3: impact_of_cooling — simulate default, density SoT unchanged."""
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


def _mixed_map(n: int = 40):
    from engine.build import build_map
    from engine.tle import build_demo_catalog

    cat = build_demo_catalog(n, fleet="starlink")
    return build_map(
        catalog=cat,
        src="impact-test:mixed",
        limit=0,
        hot_only=True,
        offline_demo=True,
        backend="python",
        satcat=False,
    )


class TestImpactEngine(unittest.TestCase):
    def test_known_bins_empty_on_cool(self):
        from engine.reach_studio import impact_of_cooling

        _, amap, _, _ = _mixed_map(40)
        amap.rebuild_bin_index()
        # pick 3 cells that actually have sats
        cells = sorted(
            amap.cell_to_sats.items(), key=lambda kv: -len(kv[1])
        )[:3]
        self.assertGreaterEqual(len(cells), 1)
        cool = []
        for _key, sats in cells:
            cool.extend(sats)
        self.assertGreater(len(cool), 0)
        v0 = amap.version
        dens0 = dict(amap.density)
        report = impact_of_cooling(amap, cool_sats=cool, simulate=True)
        self.assertTrue(report["simulate"])
        self.assertFalse(report["applied"])
        self.assertEqual(report["cool_n"], len(set(cool)))
        self.assertEqual(report["n_emptied"], len(cells))
        self.assertEqual(len(report["cells_emptied"]), len(cells))
        self.assertEqual(amap.version, v0)
        self.assertEqual(dict(amap.density), dens0)

    def test_shell_scope_and_line(self):
        from engine.reach_studio import impact_of_cooling

        _, amap, _, _ = _mixed_map(40)
        target = min(amap._shells, key=amap._shells.get)
        n = amap._shells[target]
        report = impact_of_cooling(amap, or_shell=target, simulate=True)
        self.assertEqual(report["cool_n"], n)
        self.assertIn("sat →", report["line"])
        self.assertIn("cell empty", report["line"])
        self.assertGreaterEqual(report["n_affected"], 1)

    def test_apply_cools_but_keeps_density(self):
        from engine.reach_studio import impact_of_cooling

        _, amap, _, _ = _mixed_map(24)
        amap.rebuild_bin_index()
        one_cell = next(iter(amap.cell_to_sats.values()))
        cool = list(one_cell)[:3]
        dens0 = dict(amap.density)
        v0 = amap.version
        report = impact_of_cooling(amap, cool_sats=cool, simulate=False)
        self.assertTrue(report["applied"])
        self.assertGreater(amap.version, v0)
        self.assertEqual(dict(amap.density), dens0)


class TestImpactAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from engine.build import build_map
        from engine.tle import build_demo_catalog
        from ui.app import StudioState, create_handler

        cat = build_demo_catalog(40, fleet="starlink")
        store, amap, use, src = build_map(
            catalog=cat,
            src="impact-api",
            limit=0,
            hot_only=True,
            offline_demo=True,
            backend="python",
            satcat=False,
        )
        cls.amap = amap
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

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

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

    def test_post_impact_simulate(self):
        target = max(self.amap._shells, key=self.amap._shells.get)
        v0 = self.amap.version
        dens_n = len(self.amap.density)
        st, j = self._post("/api/impact", {"or_shell": target, "simulate": True})
        self.assertEqual(st, 200)
        d = j["data"]
        self.assertTrue(d["simulate"])
        self.assertFalse(d["applied"])
        self.assertGreater(d["cool_n"], 0)
        self.assertIn("affected_cells", d)
        self.assertNotIn("sat_positions", d)
        self.assertEqual(self.amap.version, v0)
        self.assertEqual(len(self.amap.density), dens_n)

    def test_index_has_impact(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        self.assertIn("btn-impact-wow", html)
        self.assertIn("impact-panel", html)


if __name__ == "__main__":
    unittest.main()
