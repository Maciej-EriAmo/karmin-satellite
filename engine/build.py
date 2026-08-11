"""build_map: seed store from TLE."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Tuple

from engine.bootstrap import ensure_paths

ensure_paths()
from karmazyn_kernel import open_store  # noqa: E402

from engine.map import StarlinkAtomMap
from engine.tle import TleSat, load_tle_text, parse_tle_catalog

def build_map(
    *,
    limit: int = 400,
    grid: float = 5.0,
    hot_only: bool = True,
    prop: str = "auto",
    offline_demo: bool = False,
    cache: str = "out/starlink_tle_cache.txt",
    backend: str = "python",
    minutes: float = 0.0,
    store: Any = None,
) -> Tuple[Any, StarlinkAtomMap, List[TleSat], str]:
    """API do seedowania Store (boot / tool / testy)."""
    if backend and backend != "default":
        os.environ["KARMAZYN_SUBSTRATE"] = backend
    raw, src = load_tle_text(
        offline_demo=offline_demo,
        cache=Path(cache),
        limit_hint=limit or 12,
    )
    catalog = parse_tle_catalog(raw)
    use = catalog if limit == 0 else catalog[:limit]
    if store is None:
        store = open_store(
            thermal=True,
            backend=backend if backend != "default" else None,
        )
    amap = StarlinkAtomMap(
        store, grid_deg=grid, hot_only=hot_only, prop_mode=prop
    )
    amap.ingest_sats(use)
    if not hot_only:
        amap.ensure_full_grid()
    amap.refresh(use, minutes=minutes)
    return store, amap, use, src
