"""Faza 2: Studio HTTP API smoke (stdlib server in thread)."""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestStudioAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
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

    def test_health_and_version(self):
        st, j = self._get("/api/health")
        self.assertEqual(st, 200)
        self.assertEqual(j["status"], "ok")
        st, j = self._get("/api/version")
        self.assertEqual(st, 200)
        self.assertIn("version", j)
        self.assertGreaterEqual(j["version"], 1)

    def test_data_snapshot(self):
        st, j = self._get("/api/data")
        self.assertEqual(st, 200)
        self.assertEqual(j["status"], "ok")
        d = j["data"]
        self.assertIn("density", d)
        self.assertIn("summary", d)
        self.assertIn("nlat", d)
        self.assertIn("nlon", d)
        self.assertGreater(len(d["density"]), 0)

    def test_filter(self):
        st, j = self._get("/api/filter?shell=53&min_count=1")
        self.assertEqual(st, 200)
        self.assertEqual(j["data"]["shell"], "shell:53")
        self.assertGreaterEqual(j["data"]["count_sats"], 1)
        st, j = self._get("/api/filter?shell=99&min_count=1")
        self.assertEqual(j["data"]["count_cells"], 0)

    def test_refresh_bumps_version(self):
        _, v0 = self._get("/api/version")
        st, j = self._post("/api/refresh", {"minutes": 0})
        self.assertEqual(st, 200)
        self.assertEqual(j["status"], "ok")
        self.assertGreater(j["data"]["version"], v0["version"])

    def test_weather_offline_and_hazard(self):
        st, j = self._get("/api/weather?offline=1")
        self.assertEqual(st, 200)
        self.assertEqual(j["status"], "ok")
        self.assertIn("flare_class", j["data"])
        self.assertIn(j["data"]["mode"], ("stub", "cache", "live"))
        st, j = self._get("/api/hazard?offline=1")
        self.assertEqual(st, 200)
        d = j["data"]
        self.assertIn("global_score", d)
        self.assertIn("groups", d)
        self.assertIn("badge", d)
        self.assertGreaterEqual(len(d["groups"]), 1)

    def test_hazard_grid_overlay(self):
        st, j = self._get("/api/hazard?offline=1&grid=1")
        self.assertEqual(st, 200)
        d = j["data"]
        self.assertIn("overlay", d)
        ov = d["overlay"]
        self.assertIn("cells", ov)
        self.assertIn("base_score", ov)
        self.assertGreaterEqual(ov["n_cells"], 1)
        cell0 = ov["cells"][0]
        self.assertIn("exposure", cell0)
        self.assertIn("ilat", cell0)

    def test_index_and_static(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            self.assertEqual(r.status, 200)
            html = r.read().decode("utf-8")
            self.assertIn("Cynober", html)
        with urllib.request.urlopen(self.base + "/static/heatmap.js", timeout=5) as r:
            self.assertEqual(r.status, 200)
            js = r.read().decode("utf-8")
            self.assertIn("fetchJSON", js)


if __name__ == "__main__":
    unittest.main()
