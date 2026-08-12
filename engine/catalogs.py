#!/usr/bin/env python3
"""
H7 — multi-fleet open catalogs (public Celestrak GP groups).

No API keys. Research / enthusiast use only.
Primary: Celestrak GROUP=… TLE. Optional merge of several fleets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# Public Celestrak endpoints (no auth)
_CELESTRAK_GROUP = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
)
_CELESTRAK_SUP = (
    "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php"
    "?FILE={file}&FORMAT=tle"
)


@dataclass(frozen=True)
class CatalogSpec:
    """One public constellation / collection."""

    id: str
    label: str
    group: str  # Celestrak GROUP= or supplemental FILE=
    kind: str = "group"  # group | supplemental
    note: str = ""

    def urls(self) -> Tuple[str, ...]:
        if self.kind == "supplemental":
            return (
                _CELESTRAK_SUP.format(file=self.group),
                _CELESTRAK_GROUP.format(group=self.group),
            )
        return (_CELESTRAK_GROUP.format(group=self.group),)

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

_BY_ID: Dict[str, CatalogSpec] = {c.id: c for c in FLEET_CATALOG}


def list_fleets() -> List[dict]:
    return [
        {
            "id": c.id,
            "label": c.label,
            "group": c.group,
            "kind": c.kind,
            "note": c.note,
            "urls": list(c.urls()),
        }
        for c in FLEET_CATALOG
    ]


def get_fleet(fleet_id: str) -> CatalogSpec:
    key = (fleet_id or "starlink").strip().lower()
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
    'all' / '*' → all curated fleets except 'active' (use 'all+active' for that).
    Empty → ['starlink'].
    """
    if not value or not str(value).strip():
        return ["starlink"]
    raw = str(value).replace("+", ",").replace(";", ",").strip().lower()
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


def default_cache_path(fleet_id: str, root: str = "out") -> str:
    spec = get_fleet(fleet_id)
    return f"{root.rstrip('/')}/{spec.cache_basename()}"


def fleet_label(fleet_ids: Sequence[str]) -> str:
    ids = list(fleet_ids) or ["starlink"]
    if len(ids) == 1:
        return get_fleet(ids[0]).label
    return "+".join(get_fleet(i).label for i in ids)
