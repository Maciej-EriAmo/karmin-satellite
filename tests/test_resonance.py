"""W4: resonance browse — HRR when present, enabled:false without, no 500."""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


def _map(n: int = 24):
    from engine.build import build_map
    from engine.tle import build_demo_catalog

    cat = build_demo_catalog(n, fleet="starlink")
    return build_map(
        catalog=cat,
        src="reso-test",
        limit=0,
        hot_only=True,
        offline_demo=True,
        backend="python",
        satcat=False,
    )


class TestResonanceEngine(unittest.TestCase):
    def test_known_e_in_topk_when_hrr(self):
        from engine.reach_studio import hrr_available, studio_resonance

        _, amap, use, _ = _map(20)
        sat = next(amap.iter_sats())
        e = str(sat.E or "")
        self.assertTrue(e)
        out = studio_resonance(amap, e, k=10)
        ids = [h["id"] for h in out["hits"]]
        if hrr_available(amap.store):
            self.assertTrue(out["enabled"])
            self.assertIn(str(sat.id), ids)
        else:
            self.assertFalse(out["enabled"])
            self.assertGreaterEqual(out["n_hits"], 1)

    def test_disabled_shape_without_hrr(self):
        from engine.reach_studio import studio_resonance

        _, amap, _, _ = _map(16)
        with mock.patch("engine.reach_studio.hrr_available", return_value=False):
            out = studio_resonance(amap, "shell:53", k=8)
        self.assertFalse(out["enabled"])
        self.assertIn(out["mode"], ("lexical", "scope", "off"))
        self.assertIn("hits", out)
        self.assertIn("cells", out)

    def test_shell_query_is_scope_not_fake_hrr(self):
        from engine.reach_studio import studio_resonance

        _, amap, _, _ = _map(20)
        out = studio_resonance(amap, "shell:53", k=8)
        self.assertEqual(out["mode"], "scope")
        self.assertEqual(out.get("hrr_hits", 0), 0)
        self.assertGreater(out["n_hits"], 0)

    def test_empty_query(self):
        from engine.reach_studio import studio_resonance

        _, amap, _, _ = _map(12)
        out = studio_resonance(amap, "", k=5)
        self.assertEqual(out["hits"], [])
        self.assertEqual(out["cells"], [])


class TestResonanceAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.app import StudioState, create_handler

        _store, amap, use, src = _map(16)
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

    def test_resonance_ok(self):
        q = urllib.parse.quote("shell:53")
        with urllib.request.urlopen(
            self.base + f"/api/resonance?q={q}&k=8", timeout=8
        ) as r:
            self.assertEqual(r.status, 200)
            j = json.loads(r.read().decode("utf-8"))
        self.assertEqual(j["status"], "ok")
        self.assertIn("enabled", j["data"])
        self.assertIn("hits", j["data"])
        self.assertIn("cells", j["data"])


if __name__ == "__main__":
    unittest.main()
