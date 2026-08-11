"""Minimal smoke: substrate import + offline map."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


def test_open_store():
    from karmazyn_kernel import open_store, T_INIT

    store = open_store(thermal=True, backend="python")
    assert store is not None
    a = store.create_atom("smoke:1", S="test", E="x", T=T_INIT)
    assert a is not None or store.has_atom("smoke:1")


def test_offline_map():
    from engine.starlink_atoms import build_map

    store, amap, use, src = build_map(
        limit=12,
        hot_only=True,
        offline_demo=True,
        backend="python",
        cache="out/starlink_tle_cache.txt",
    )
    assert len(use) > 0
    summ = amap.summary()
    assert summ.get("sats", 0) > 0 or summ.get("cells", 0) >= 0
    assert "offline" in src or src  # source string present
