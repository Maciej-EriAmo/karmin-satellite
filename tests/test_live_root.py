"""Live root + depends_on — vacuum vs retained; Impact reads the graph."""
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


def _mixed(n: int = 40):
    from engine.build import build_map
    from engine.tle import build_demo_catalog

    cat = build_demo_catalog(n, fleet="starlink")
    return build_map(
        catalog=cat,
        src="live-root-test",
        limit=0,
        hot_only=True,
        offline_demo=True,
        backend="python",
        satcat=False,
    )


class TestDependsOnGraph(unittest.TestCase):
    def test_cells_carry_depends_on_after_build(self):
        from engine.reach_studio import graph_edge_count, occupants_from_graph

        _, amap, _, _ = _mixed(24)
        self.assertGreater(graph_edge_count(amap), 0)
        key = next(iter(amap.cell_to_sats))
        occ = occupants_from_graph(amap, key)
        self.assertIsNotNone(occ)
        self.assertEqual(occ, set(amap.cell_to_sats[key]))

    def test_impact_source_is_graph(self):
        from engine.reach_studio import impact_of_cooling

        _, amap, _, _ = _mixed(24)
        target = min(amap._shells, key=amap._shells.get)
        report = impact_of_cooling(amap, or_shell=target, simulate=True)
        self.assertEqual(report["source"], "graph")
        self.assertIn("graph", report["line"])


class TestLiveRootVacuum(unittest.TestCase):
    def test_commit_vacuums_outside_session_keeps_inside(self):
        from engine.reach_studio import (
            apply_live_scope,
            restore_catalog,
            session_reach,
        )

        store, amap, catalog, _ = _mixed(40)
        shells = dict(amap._shells)
        self.assertGreater(len(shells), 1)
        keep = max(shells, key=shells.get)
        drop = min(shells, key=shells.get)
        self.assertNotEqual(keep, drop)
        outsider = next(iter(amap._shell_index[drop]))
        self.assertTrue(store.has_atom(outsider))
        n0 = sum(1 for _ in amap.iter_sats())
        apply_live_scope(amap, catalog, shell=keep)
        self.assertTrue(getattr(amap, "_live_root"))
        self.assertFalse(store.has_atom(outsider))
        n1 = sum(1 for _ in amap.iter_sats())
        self.assertLess(n1, n0)
        reach = {a for a in session_reach(amap) if a.startswith("sat:")}
        self.assertEqual(len(reach), n1)
        # catalog TLE still lets us restore
        restore_catalog(amap, catalog)
        self.assertTrue(store.has_atom(outsider))
        self.assertFalse(getattr(amap, "_live_root"))
        self.assertGreaterEqual(sum(1 for _ in amap.iter_sats()), n0)

    def test_catalog_root_tick_does_not_vacuum(self):
        from engine.grid import _set_T
        from engine.reach_studio import set_session_scope
        from karmazyn_kernel import T_TOMB

        store, amap, _, _ = _mixed(30)
        shells = dict(amap._shells)
        keep = max(shells, key=shells.get)
        drop = min(shells, key=shells.get)
        if keep == drop:
            self.skipTest("need two shells")
        outsider = next(iter(amap._shell_index[drop]))
        set_session_scope(amap, shell=keep)
        atom = store.get_atom(outsider)
        _set_T(atom, T_TOMB * 0.4)
        store.tick()
        # starlink is still a root → retained, not vacuumed
        self.assertTrue(store.has_atom(outsider))


class TestLiveRootAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.app import StudioState, create_handler

        store, amap, use, src = _mixed(32)
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

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=8) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_attention_and_index_chrome(self):
        st, j = self._get("/api/attention")
        self.assertEqual(st, 200)
        self.assertFalse(j["data"]["live"])
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        self.assertIn("btn-live-wow", html)
        self.assertIn("btn-commit-wow", html)

    def test_live_commit_then_restore(self):
        n0 = sum(1 for _ in self.amap.iter_sats())
        self._post("/api/attention", {"live": True})
        keep = max(self.amap._shells, key=self.amap._shells.get)
        st, j = self._post("/api/session", {"shell": keep, "min_count": 1})
        self.assertEqual(st, 200)
        self.assertTrue(j["data"].get("live") or j["data"].get("attention"))
        n1 = sum(1 for _ in self.amap.iter_sats())
        self.assertLess(n1, n0)
        self._post("/api/attention", {"restore": True})
        n2 = sum(1 for _ in self.amap.iter_sats())
        self.assertGreaterEqual(n2, n0)


if __name__ == "__main__":
    unittest.main()
