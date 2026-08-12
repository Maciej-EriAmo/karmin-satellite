"""Faza 5: snapshot save/load density roundtrip."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestSnapshots(unittest.TestCase):
    def test_roundtrip_density(self):
        from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map
        from engine.build import build_map

        _, amap, use, src = build_map(
            limit=25,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        dens0 = dict(amap.density)
        self.assertGreater(len(dens0), 0)

        with tempfile.TemporaryDirectory() as td:
            store = SnapshotStore(Path(td), retention_days=7)
            meta = store.save(amap, snapshot_id="test_round", src=src, using=len(use))
            self.assertEqual(meta.snapshot_id, "test_round")
            self.assertTrue(meta.path.is_file())

            items = store.list()
            self.assertEqual(len(items), 1)

            payload = store.load_raw("test_round")
            _s, amap2, use2, src2 = load_snapshot_into_map(payload)
            dens1 = dict(amap2.density)
            self.assertEqual(dens0, dens1)
            self.assertGreaterEqual(amap2.summary()["sats"], 1)
            cons = amap2.density_cell_consistency()
            self.assertTrue(cons["ok"], cons)

    def test_prune_old(self):
        from adapters.snapshot_store import SnapshotStore
        from engine.build import build_map
        from datetime import datetime, timezone, timedelta
        import json

        _, amap, use, src = build_map(
            limit=10,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SnapshotStore(root, retention_days=7)
            store.save(amap, snapshot_id="fresh", src=src, using=len(use), prune=False)
            # forge old snapshot
            old = store.build_payload(amap, src=src, using=len(use))
            old["snapshot_id"] = "ancient"
            old["created_at"] = (
                datetime.now(timezone.utc) - timedelta(days=30)
            ).isoformat()
            (root / "ancient.json").write_text(
                json.dumps(old), encoding="utf-8"
            )
            removed = store.prune(retention_days=7)
            self.assertGreaterEqual(removed, 1)
            ids = {m.snapshot_id for m in store.list()}
            self.assertIn("fresh", ids)
            self.assertNotIn("ancient", ids)

    def test_solar_meta_on_save(self):
        """H4: snapshot payload carries solar weather/hazard block."""
        from adapters.snapshot_store import SnapshotStore
        from engine.build import build_map

        _, amap, use, src = build_map(
            limit=15,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        with tempfile.TemporaryDirectory() as td:
            store = SnapshotStore(Path(td), retention_days=0)
            meta = store.save(
                amap,
                snapshot_id="solar_snap",
                src=src,
                using=len(use),
                attach_solar=True,
                solar_offline=True,
                prune=False,
            )
            payload = store.load_raw(meta.snapshot_id)
            self.assertIn("solar", payload)
            solar = payload["solar"]
            self.assertIn("weather", solar)
            self.assertIn("hazard", solar)
            self.assertIn("global_score", solar["hazard"])
            self.assertIn("predict", solar)


if __name__ == "__main__":
    unittest.main()
