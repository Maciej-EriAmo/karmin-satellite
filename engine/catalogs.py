#!/usr/bin/env python3
"""
H7 — multi-fleet open catalogs (public Celestrak GP groups).

No API keys. Research / enthusiast use only.
Primary: Celestrak GROUP=… TLE. Optional merge of several fleets.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Public Celestrak endpoints (no auth).
_HOST = "https://celestrak.org"
_CELESTRAK_GROUP = _HOST + "/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
_CELESTRAK_INTDES = _HOST + "/NORAD/elements/gp.php?INTDES={intdes}&FORMAT=tle"
_CELESTRAK_SUP = (
    _HOST + "/NORAD/elements/supplemental/sup-gp.php?FILE={file}&FORMAT=tle"
)


@dataclass(frozen=True)
class CatalogSpec:
    """One public constellation / collection."""

    id: str
    label: str
    group: str  # Celestrak GROUP= or supplemental FILE=
    kind: str = "group"  # group | supplemental
    role: str = "fleet"  # fleet | debris
    intdes: str = ""  # optional yyyy-nnn launch designator
    note: str = ""

    def urls(self) -> Tuple[str, ...]:
        out: List[str] = []
        if self.kind == "supplemental":
            out.append(_CELESTRAK_SUP.format(file=self.group))
        if self.intdes:
            # INTDES first for debris — GROUP=yyyy-nnn 503s while INTDES works
            out.append(_CELESTRAK_INTDES.format(intdes=self.intdes))
        out.append(_CELESTRAK_GROUP.format(group=self.group))
        seen = set()
        uniq: List[str] = []
        for u in out:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return tuple(uniq)

    def cache_basename(self) -> str:
        return f"tle_{self.id}.txt"


# Curated public fleets (LEO-first + a few classics)
FLEET_CATALOG: Tuple[CatalogSpec, ...] = (
    CatalogSpec(
        "starlink",
        "Starlink",
        "starlink",
        kind="supplemental",
        note="SpaceX Starlink (supplemental GP preferred)",
    ),
    CatalogSpec(
        "oneweb",
        "OneWeb",
        "oneweb",
        note="OneWeb broadband LEO",
    ),
    CatalogSpec(
        "iridium",
        "Iridium NEXT",
        "iridium-NEXT",
        note="Iridium NEXT constellation",
    ),
    CatalogSpec(
        "globalstar",
        "Globalstar",
        "globalstar",
        note="Globalstar LEO",
    ),
    CatalogSpec(
        "orbcomm",
        "Orbcomm",
        "orbcomm",
        note="Orbcomm M2M",
    ),
    CatalogSpec(
        "planet",
        "Planet",
        "planet",
        note="Planet Labs Dove/SuperDove",
    ),
    CatalogSpec(
        "spire",
        "Spire",
        "spire",
        note="Spire Lemur",
    ),
    CatalogSpec(
        "swarm",
        "Swarm",
        "swarm",
        note="Swarm SpaceBEE",
    ),
    CatalogSpec(
        "gps",
        "GPS operational",
        "gps-ops",
        note="GPS ops (MEO)",
    ),
    CatalogSpec(
        "galileo",
        "Galileo",
        "galileo",
        note="Galileo GNSS",
    ),
    CatalogSpec(
        "stations",
        "Stations / ISS",
        "stations",
        note="Space stations (ISS etc.)",
    ),
    CatalogSpec(
        "visual",
        "100 brightest",
        "visual",
        note="Brightest visual satellites",
    ),
    CatalogSpec(
        "active",
        "All active",
        "active",
        note="Full active catalog — large; use limit",
    ),
)

# Public Celestrak event-cloud debris (no Space-Track; not SSA).
DEBRIS_CATALOG: Tuple[CatalogSpec, ...] = (
    CatalogSpec(
        "fy1c-debris",
        "Fengyun-1C debris",
        "1999-025",
        role="debris",
        intdes="1999-025",
        note="2007 Chinese ASAT cloud",
    ),
    CatalogSpec(
        "cosmos-2251-debris",
        "Cosmos 2251 debris",
        "cosmos-2251-debris",
        role="debris",
        intdes="1993-036",
        note="2009 collision cloud (Cosmos 2251)",
    ),
    CatalogSpec(
        "iridium-33-debris",
        "Iridium 33 debris",
        "iridium-33-debris",
        role="debris",
        intdes="1997-051",
        note="2009 collision cloud (Iridium 33)",
    ),
    CatalogSpec(
        "microsat-r-debris",
        "Microsat-R debris",
        "2019-006",
        role="debris",
        intdes="2019-006",
        note="2019 Indian ASAT cloud",
    ),
    CatalogSpec(
        "cosmos-1408-debris",
        "Cosmos 1408 debris",
        "cosmos-1408-debris",
        role="debris",
        intdes="1982-092",
        note="2021 Russian ASAT cloud",
    ),
)

DEBRIS_ALIASES = frozenset(
    {"debris", "space-debris", "space_debris", "orbital-debris", "junk"}
)

_ALL_CATALOGS: Tuple[CatalogSpec, ...] = FLEET_CATALOG + DEBRIS_CATALOG
_BY_ID: Dict[str, CatalogSpec] = {c.id: c for c in _ALL_CATALOGS}


def list_fleets() -> List[dict]:
    return [
        {
            "id": c.id,
            "label": c.label,
            "group": c.group,
            "kind": c.kind,
            "role": c.role,
            "note": c.note,
            "urls": list(c.urls()),
        }
        for c in _ALL_CATALOGS
    ]


def debris_catalog_ids() -> List[str]:
    return [c.id for c in DEBRIS_CATALOG]


def get_fleet(fleet_id: str) -> CatalogSpec:
    key = (fleet_id or "starlink").strip().lower()
    if key in DEBRIS_ALIASES:
        return DEBRIS_CATALOG[0]
    if key in _BY_ID:
        return _BY_ID[key]
    # allow raw celestrak group names
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "" for ch in key)
    if not safe:
        return _BY_ID["starlink"]
    return CatalogSpec(
        id=safe,
        label=safe,
        group=safe,
        kind="group",
        note="ad-hoc Celestrak GROUP",
    )


def curated_fleet_ids(*, include_active: bool = False) -> List[str]:
    """Ordered curated fleet ids (optionally including huge 'active' group)."""
    ids = [c.id for c in FLEET_CATALOG]
    if not include_active:
        ids = [i for i in ids if i != "active"]
    return ids


def parse_fleet_list(value: Optional[str]) -> List[str]:
    """
    'starlink' | 'starlink,oneweb' | 'starlink+oneweb' → list of ids.
    'all' / '*' → all curated fleets except 'active' and debris.
    'debris' → public Celestrak event clouds (FY-1C, Iridium 33, Cosmos 2251,
    Microsat-R, Cosmos 1408). Empty → ['starlink'].
    """
    if not value or not str(value).strip():
        return ["starlink"]
    raw = str(value).replace("+", ",").replace(";", ",").strip().lower()
    if raw in DEBRIS_ALIASES:
        return debris_catalog_ids()
    if raw in ("all", "*", "all-curated", "all_curated"):
        return curated_fleet_ids(include_active=False)
    if raw in ("all+active", "all_active", "all,active"):
        return curated_fleet_ids(include_active=True)
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    # expand lone 'all' token inside a list
    expanded: List[str] = []
    for p in parts:
        if p in ("all", "*"):
            expanded.extend(curated_fleet_ids(include_active=False))
        elif p in DEBRIS_ALIASES:
            expanded.extend(debris_catalog_ids())
        else:
            expanded.append(p)
    # dedupe preserve order
    seen = set()
    out: List[str] = []
    for p in expanded:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out or ["starlink"]


def default_cache_path(fleet_id: str, root: str = "") -> str:
    spec = get_fleet(fleet_id)
    name = spec.cache_basename()
    if root:
        return f"{root.rstrip('/')}/{name}"
    try:
        from engine.user_paths import cache_file, relocate_legacy

        relocate_legacy()
        return str(cache_file(name))
    except Exception:
        return f"out/{name}"
