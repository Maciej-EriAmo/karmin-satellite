"""build_map: seed store from TLE."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, List, Tuple

from engine.bootstrap import ensure_paths

ensure_paths()
from karmazyn_kernel import open_store  # noqa: E402

from engine.constants import (
    ARCH_CEILING_SATS,
    ARCH_MAX_SATS,
    ARCH_USABLE_SATS,
    DEFAULT_LIMIT,
)
from engine.map import StarlinkAtomMap
from engine.tle import TleSat, build_demo_catalog, load_catalog


def build_map(
    *,
    limit: int = DEFAULT_LIMIT,
    grid: float = 5.0,
    hot_only: bool = True,
    prop: str = "auto",
    offline_demo: bool = False,
    cache: str = "out/starlink_tle_cache.txt",
    backend: str = "python",
    minutes: float = 0.0,
    store: Any = None,
    arch_cap: bool = True,
    catalog: List[TleSat] | None = None,
    src: str | None = None,
    fleet: str = "starlink",
) -> Tuple[Any, StarlinkAtomMap, List[TleSat], str]:
    """API do seedowania Store (boot / tool / testy).

    limit:
      0 → cały katalog TLE (po parse), potem opcjonalnie cięcie do ARCH_CEILING_SATS
      N → pierwsze N wpisów
    arch_cap=True: twardy sufit ARCH_CEILING_SATS (100_000).
    catalog=...: gotowa lista (capacity tests); pomija fetch/parse.
    fleet: H7 — id floty lub lista ``starlink,oneweb``.
    """
    if backend and backend != "default":
        os.environ["KARMAZYN_SUBSTRATE"] = backend

    if catalog is not None:
        full = list(catalog)
        src_s = src or "catalog:injected"
    else:
        from engine.catalogs import parse_fleet_list

        fleet_ids = parse_fleet_list(fleet)
        multi = len(fleet_ids) > 1
        # multi-fleet: split limit across fleets so merge is not first-fleet-only
        per = None
        if multi and limit and limit > 0:
            per = max(1, int(limit) // len(fleet_ids))
        full, src_s = load_catalog(
            fleet=fleet,
            offline_demo=offline_demo,
            cache=Path(cache) if not multi else None,
            cache_dir=Path(cache).parent if cache else Path("out"),
            limit_hint=limit or 12,
            per_fleet_limit=per,
        )

    use = full if limit == 0 else full[:limit]
    if arch_cap and len(use) > ARCH_CEILING_SATS:
        print(
            f"WARN: using={len(use)} > ARCH_CEILING_SATS={ARCH_CEILING_SATS}; "
            f"capping. Pass arch_cap=False to override.",
            file=sys.stderr,
        )
        use = use[:ARCH_CEILING_SATS]
    elif len(use) > ARCH_USABLE_SATS:
        print(
            f"NOTE: using={len(use)} > ARCH_USABLE_SATS={ARCH_USABLE_SATS} "
            f"(ceiling={ARCH_CEILING_SATS}) — above recommended operating budget.",
            file=sys.stderr,
        )

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
    return store, amap, use, src_s


def build_capacity_map(
    n: int,
    *,
    hot_only: bool = True,
    prop: str = "sgp4",
    grid: float = 5.0,
    backend: str = "python",
) -> Tuple[Any, StarlinkAtomMap, List[TleSat], str]:
    """Synthetic catalog of exactly n unique sats (for capacity / soak)."""
    cat = build_demo_catalog(n)
    return build_map(
        limit=0,
        catalog=cat,
        src=f"capacity-demo:{n}",
        hot_only=hot_only,
        prop=prop,
        backend=backend,
        grid=grid,
        arch_cap=True,
    )
