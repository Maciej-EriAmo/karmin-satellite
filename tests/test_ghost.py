"""W2: ghost / retained TOMB layer (beside density SoT)."""
from __future__ import annotations

import sys
import unittest
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
        src="ghost-test:mixed",
        limit=0,
        hot_only=True,
        offline_demo=True,
        backend="python",
        satcat=False,
    )


class TestGhostLayer(unittest.TestCase):
    def test_cool_in_reach_appears_ghost_stays_reachable(self):
        from engine.reach_studio import (
            collect_ghost,
            demo_cool_in_reach,
            session_reach,
        )

        _, amap, use, _ = _mixed_map(36)
        dens0 = dict(amap.density)
        reach0 = {a for a in session_reach(amap) if a.startswith("sat:")}
        self.assertEqual(len(reach0), len(use))
        before = collect_ghost(amap)
        self.assertTrue(before["enabled"])
        info = demo_cool_in_reach(amap, n=6)
        self.assertGreaterEqual(info["cooled"], 1)
        self.assertGreaterEqual(info["n_sats"], 1)
        self.assertGreaterEqual(info["n_cells"], 1)
        after_reach = {a for a in session_reach(amap) if a.startswith("sat:")}
        self.assertEqual(after_reach, reach0)
        self.assertEqual(dict(amap.density), dens0)
        sample = set(info.get("cooled_sample") or [])
        self.assertTrue(sample <= after_reach)

    def test_cold_outside_reach_not_in_ghost(self):
        from engine.grid import _set_T
        from engine.reach_studio import (
            collect_ghost,
            session_reach,
            set_session_scope,
        )
        from karmazyn_kernel import T_TOMB

        _, amap, _, _ = _mixed_map(40)
        shells = dict(amap._shells)
        self.assertGreater(len(shells), 1)
        keep = max(shells, key=shells.get)
        drop = min(shells, key=shells.get)
        self.assertNotEqual(keep, drop)
        outsider = next(iter(amap._shell_index.get(drop) or []), None)
        self.assertIsNotNone(outsider)
        atom = amap.store.get_atom(outsider)
        _set_T(atom, T_TOMB * 0.4)
        amap.store.tick()
        set_session_scope(amap, shell=keep)
        reach = session_reach(amap)
        self.assertNotIn(outsider, reach)
        ghost = collect_ghost(amap)
        sample = set(ghost.get("sats_sample") or [])
        self.assertNotIn(outsider, sample)
        # still retained in store (catalog root) — just not in ghost view
        self.assertTrue(amap.store.has_atom(outsider))

    def test_flag_off_ghost_disabled(self):
        import os

        from engine.build import build_map
        from engine.reach_studio import collect_ghost

        old = os.environ.get("CYNOBER_REACH")
        try:
            os.environ["CYNOBER_REACH"] = "0"
            _, amap, _, _ = build_map(
                limit=12,
                hot_only=True,
                offline_demo=True,
                backend="python",
                satcat=False,
            )
            g = collect_ghost(amap)
            self.assertFalse(g["enabled"])
            self.assertEqual(g["n_cells"], 0)
        finally:
            if old is None:
                os.environ.pop("CYNOBER_REACH", None)
            else:
                os.environ["CYNOBER_REACH"] = old


if __name__ == "__main__":
    unittest.main()
