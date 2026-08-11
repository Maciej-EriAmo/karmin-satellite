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
from engine.tle import TleSat, build_demo_catalog, load_tle_text, parse_tle_catalog


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
) -> Tuple[Any, StarlinkAtomMap, List[TleSat], str]:
    """API do seedowania Store (boot / tool / testy).

    limit:
      0 → cały katalog TLE (po parse), potem opcjonalnie cięcie do ARCH_CEILING_SATS
      N → pierwsze N wpisów
    arch_cap=True: twardy sufit ARCH_CEILING_SATS (100_000).
    catalog=...: gotowa lista (capacity tests); pomija fetch/parse.
    """
    if backend and backend != "default":
        os.environ["KARMAZYN_SUBSTRATE"] = backend

    if catalog is not None:
        full = list(catalog)
        src_s = src or "catalog:injected"
    else:
        raw, src_s = load_tle_text(
            offline_demo=offline_demo,
            cache=Path(cache),
            limit_hint=limit or 12,
        )
        full = parse_tle_catalog(raw)

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
