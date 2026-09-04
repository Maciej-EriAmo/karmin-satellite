"""F0 + W1: session root, reach view, regression of default /api/data."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))

# Frozen /api/data.data keys (W1: no extras without ?reach=1)
_DATA_KEYS = frozenset(
    {
        "version",
        "grid_deg",
        "hot_only",
        "policy",
        "density",
        "cells",
        "shells",
        "summary",
        "prop_errors_sample",
        "nlat",
        "nlon",
        "tle_source",
        "using",
        "limit",
        "fleet",
        "country",
        "countries",
        "fleets",
        "project",
        "feeder",
        "design_sats",
    }
)
_SNAP_KEYS = frozenset(
    {
        "version",
        "grid_deg",
        "hot_only",
        "policy",
        "density",
        "cells",
        "shells",
        "summary",
        "prop_errors_sample",
    }
)


def _mixed_map(n: int = 40):
    from engine.build import build_map
    from engine.tle import build_demo_catalog

    cat = build_demo_catalog(n, fleet="starlink")
    return build_map(
        catalog=cat,
        src="reach-test:mixed",
        limit=0,
        hot_only=True,
        offline_demo=True,
        backend="python",
        satcat=False,
    )


class TestReachIdsAndFlags(unittest.TestCase):
    def test_id_canon(self):
        from engine.reach_studio import (
            cell_atom_id,
            fleet_bubble_id,
            session_bubble_id,
            shell_bubble_id,
            sat_atom_id,
        )

        self.assertEqual(sat_atom_id(12345), "sat:12345")
        self.assertEqual(cell_atom_id(3, 7), "cell:3:7")
        self.assertEqual(shell_bubble_id("53"), "shell:53")
        self.assertEqual(shell_bubble_id("shell:53"), "shell:53")
        self.assertEqual(shell_bubble_id("all"), "all")
        self.assertEqual(fleet_bubble_id("starlink"), "fleet:starlink")
        self.assertEqual(session_bubble_id("default"), "session:default")
        self.assertEqual(session_bubble_id("session:default"), "session:default")

    def test_flag_off_skips_session(self):
        from engine.build import build_map
        from engine.reach_studio import reach_enabled, session_reach

        old = os.environ.get("CYNOBER_REACH")
        oldm = os.environ.get("CYNOBER_REACH_MODE")
        try:
            os.environ["CYNOBER_REACH"] = "0"
            self.assertFalse(reach_enabled())
            store, amap, use, _ = build_map(
                limit=12,
                hot_only=True,
                offline_demo=True,
                backend="python",
                satcat=False,
            )
            self.assertIsNone(getattr(amap, "_reach_session", None))
            self.assertIsNone(store.get_bubble("session:default"))
            self.assertEqual(session_reach(amap), set())
            self.assertGreater(len(use), 0)
        finally:
            if old is None:
                os.environ.pop("CYNOBER_REACH", None)
            else:
                os.environ["CYNOBER_REACH"] = old
            if oldm is None:
                os.environ.pop("CYNOBER_REACH_MODE", None)
            else:
                os.environ["CYNOBER_REACH_MODE"] = oldm


class TestSessionRoot(unittest.TestCase):
    def test_default_attach_binds_catalog(self):
        from engine.reach_studio import session_reach

        store, amap, use, _ = _mixed_map(40)
        self.assertIsNotNone(store.get_bubble("session:default"))
        reach = session_reach(amap)
        sats = {a for a in reach if a.startswith("sat:")}
        self.assertEqual(len(sats), len(use))
        self.assertTrue(all(store.has_atom(aid) for aid in sats))

    def test_scope_shell_is_subset(self):
        from engine.reach_studio import session_reach, set_session_scope

        _, amap, use, _ = _mixed_map(40)
        shells = dict(amap._shells)
        self.assertGreater(len(shells), 1, "need mixed shells in demo catalog")
        target = max(shells, key=shells.get)
        before = {a for a in session_reach(amap) if a.startswith("sat:")}
        info = set_session_scope(amap, shell=target)
        after = {a for a in session_reach(amap) if a.startswith("sat:")}
        allowed = set(amap._shell_index.get(target, set()))
        self.assertTrue(after <= allowed)
        self.assertTrue(after <= before)
        self.assertGreater(len(after), 0)
        self.assertEqual(info["n_sats"], len(after))
        self.assertLess(len(after), len(before))

        # clear scope → reach grows back deterministically
        set_session_scope(amap, shell="all")
        restored = {a for a in session_reach(amap) if a.startswith("sat:")}
        self.assertEqual(len(restored), len(use))
        self.assertEqual(restored, before)

        # empty shell → empty sat reach
        set_session_scope(amap, shell="99")
        empty = {a for a in session_reach(amap) if a.startswith("sat:")}
        self.assertEqual(empty, set())

    def test_scope_fleet(self):
        from engine.build import build_map
        from engine.reach_studio import session_reach, set_session_scope
        from engine.tle import TleSat, build_demo_catalog

        a = build_demo_catalog(16, fleet="starlink")
        b = build_demo_catalog(16, fleet="oneweb")
        # unique norads
        b2 = []
        for s in b:
            b2.append(
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
            )
        cat = a + b2
        _, amap, use, _ = build_map(
            catalog=cat,
            src="reach-test:fleets",
            limit=0,
            hot_only=True,
            offline_demo=True,
            backend="python",
            satcat=False,
        )
        set_session_scope(amap, fleet="starlink")
        sl = {x for x in session_reach(amap) if x.startswith("sat:")}
        self.assertEqual(len(sl), 16)
        for aid in sl:
            atom = amap.store.get_atom(aid)
            self.assertEqual((atom.metadata.get("v") or {}).get("fleet"), "starlink")

    def test_snapshot_default_keys_unchanged(self):
        _, amap, _, _ = _mixed_map(20)
        snap = amap.snapshot()
        self.assertEqual(set(snap.keys()), set(_SNAP_KEYS))
        self.assertNotIn("reach_view", snap)
        reach_snap = amap.snapshot(reach_only=True)
        self.assertTrue(reach_snap.get("reach_view"))
        self.assertEqual(len(reach_snap["density"]), len(snap["density"]))

    def test_reach_only_filters_density(self):
        from engine.reach_studio import set_session_scope

        _, amap, _, _ = _mixed_map(40)
        full = amap.snapshot()
        target = min(amap._shells, key=amap._shells.get)
        set_session_scope(amap, shell=target)
        view = amap.snapshot(reach_only=True)
        self.assertTrue(view["reach_view"])
        self.assertLessEqual(len(view["density"]), len(full["density"]))
        view_sum = sum(c["count"] for c in view["density"])
        full_sum = sum(c["count"] for c in full["density"])
        self.assertLess(view_sum, full_sum)
        # empty scope → empty view; SoT density untouched
        set_session_scope(amap, shell="99")
        empty = amap.snapshot(reach_only=True)
        self.assertEqual(empty["density"], [])
        self.assertEqual(len(amap.density), len(full["density"]))

    def test_refresh_does_not_drop_session(self):
        from engine.reach_studio import session_reach

        _, amap, use, _ = _mixed_map(24)
        amap.refresh(use)
        sats = {a for a in session_reach(amap) if a.startswith("sat:")}
        self.assertEqual(len(sats), len(use))


class TestReachAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from engine.tle import build_demo_catalog
        from engine.build import build_map
        from ui.app import StudioState, create_handler

        cat = build_demo_catalog(40, fleet="starlink")
        store, amap, use, src = build_map(
            catalog=cat,
            src="reach-api:mixed",
            limit=0,
            hot_only=True,
            offline_demo=True,
            backend="python",
            satcat=False,
        )
        cls.amap = amap
        cls.use = use
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

    def test_data_without_reach_compatible(self):
        st, j = self._get("/api/data")
        self.assertEqual(st, 200)
        d = j["data"]
        extra = set(d.keys()) - _DATA_KEYS
        self.assertEqual(extra, set(), f"unexpected /api/data keys: {extra}")
        self.assertNotIn("reach_view", d)
        self.assertNotIn("reach", d)
        snap = self.amap.snapshot()
        self.assertEqual(d["density"], snap["density"])
        # second fetch identical density (stable SoT)
        _, j2 = self._get("/api/data")
        self.assertEqual(j2["data"]["density"], d["density"])

    def test_reach_status_and_session(self):
        st, j = self._get("/api/reach")
        self.assertEqual(st, 200)
        d = j["data"]
        self.assertTrue(d["enabled"])
        self.assertEqual(d["mode"], "session")
        self.assertEqual(d["n_sats"], len(self.use))
        self.assertNotIn("sats", d)
        self.assertNotIn("ids", d)

        target = max(self.amap._shells, key=self.amap._shells.get)
        v0 = int(self.amap.version)
        st, j = self._post("/api/session", {"shell": target, "min_count": 1})
        self.assertEqual(st, 200)
        self.assertGreater(j["data"]["version"], v0)
        self.assertLess(j["data"]["n_sats"], len(self.use))
        self.assertGreater(j["data"]["n_sats"], 0)

        _, full = self._get("/api/data")
        _, scoped = self._get("/api/data?reach=1")
        self.assertNotIn("reach_view", full["data"])
        self.assertTrue(scoped["data"].get("reach_view"))
        self.assertIn("reach", scoped["data"])
        full_sum = sum(c["count"] for c in full["data"]["density"])
        scoped_sum = sum(c["count"] for c in scoped["data"]["density"])
        self.assertLess(scoped_sum, full_sum)
        self._post("/api/session", {"shell": "99"})
        _, empty = self._get("/api/data?reach=1")
        self.assertEqual(empty["data"]["density"], [])
        # restore
        self._post("/api/session", {"shell": "all"})
        _, back = self._get("/api/data?reach=1")
        self.assertEqual(len(back["data"]["density"]), len(full["data"]["density"]))

    def test_index_has_reach_toggle(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        self.assertIn("reach-toggle", html)
        self.assertIn("Reach view", html)
        self.assertIn('max="50000"', html)
        self.assertIn("btn-export-json", html)
        self.assertIn("btn-layer-ghost", html)
        self.assertIn("wow-bar", html)

    def test_export_json_and_md(self):
        with urllib.request.urlopen(
            self.base + "/api/export?format=json", timeout=8
        ) as r:
            self.assertEqual(r.status, 200)
            disp = r.headers.get("Content-Disposition") or ""
            self.assertIn("attachment", disp)
            self.assertIn(".json", disp)
            payload = json.loads(r.read().decode("utf-8"))
        self.assertEqual(payload["format"], "karmin-satellite-export-v1")
        self.assertIn("density", payload)
        self.assertIn("reach", payload)
        self.assertIn("ghost", payload)
        self.assertNotIn("sat_positions", payload)
        with urllib.request.urlopen(
            self.base + "/api/export?format=md", timeout=8
        ) as r:
            md = r.read().decode("utf-8")
        self.assertIn("# Karmin Satellite", md)
        self.assertIn("Session reach", md)
        self.assertIn("Ghost", md)

    def test_ghost_demo_endpoint(self):
        st, j = self._get("/api/ghost")
        self.assertEqual(st, 200)
        self.assertTrue(j["data"]["enabled"])
        dens0 = len(self.amap.density)
        st, j = self._post("/api/ghost/demo", {"n": 5})
        self.assertEqual(st, 200)
        self.assertGreaterEqual(j["data"]["cooled"], 1)
        self.assertEqual(len(self.amap.density), dens0)


if __name__ == "__main__":
    unittest.main()
