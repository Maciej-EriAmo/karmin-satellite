#!/usr/bin/env python3
"""
B — snapshot timeline + light analytics (cells-scale).

Compare density frames over time without re-prop.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _density_map(payload: dict) -> Dict[Tuple[int, int], int]:
    out: Dict[Tuple[int, int], int] = {}
    for d in payload.get("density") or []:
        try:
            if isinstance(d, dict):
                out[(int(d["ilat"]), int(d["ilon"]))] = int(d.get("count") or 0)
            elif isinstance(d, (list, tuple)) and len(d) >= 3:
                out[(int(d[0]), int(d[1]))] = int(d[2])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def snapshot_metrics(payload: dict) -> dict:
    dens = _density_map(payload)
    counts = list(dens.values())
    total = sum(counts)
    n = len(counts)
    max_c = max(counts) if counts else 0
    mean = (total / n) if n else 0.0
    shells = payload.get("shells") or {}
    solar = payload.get("solar") or {}
    haz = (solar.get("hazard") or {}) if isinstance(solar, dict) else {}
    return {
        "snapshot_id": payload.get("snapshot_id") or "",
        "created_at": payload.get("created_at") or "",
        "src": payload.get("src") or "",
        "version": payload.get("version") or 0,
        "cells": n,
        "sum_count": total,
        "max_count": max_c,
        "mean_count": round(mean, 3),
        "shells_n": len(shells),
        "has_solar": bool(solar),
        "hazard_score": haz.get("global_score"),
        "hazard_severity": haz.get("severity"),
        "sats_count": len(payload.get("sats") or []),
        "using": payload.get("using"),
        "catalog_hash": payload.get("catalog_hash"),
    }


def _sat_norad_set(payload: dict) -> set:
    out: set = set()
    for s in payload.get("sats") or []:
        if not isinstance(s, dict):
            continue
        n = s.get("norad")
        if n is None:
            aid = str(s.get("id") or "")
            if aid.startswith("sat:"):
                n = aid.split(":", 1)[1]
        if n is None or n == "":
            continue
        try:
            out.add(int(n))
        except (TypeError, ValueError):
            out.add(str(n))
    return out


def compare_sats(a: dict, b: dict) -> dict:
    """
    NORAD set diff when snapshots carry sats[].
    Research proxy for fleet loss / appearance — not conjunction SSA.
    """
    sa, sb = _sat_norad_set(a), _sat_norad_set(b)
    lost = sorted(sa - sb, key=lambda x: (isinstance(x, str), x))
    gained = sorted(sb - sa, key=lambda x: (isinstance(x, str), x))
    return {
        "available": bool(sa or sb),
        "a_n": len(sa),
        "b_n": len(sb),
        "lost_n": len(lost),
        "gained_n": len(gained),
        "lost": lost[:40],
        "gained": gained[:40],
        "note": (
            "NORAD presence diff when sats were saved in snapshots. "
            "Not collision/CDM assessment; solar storms can correlate with fleet loss."
        ),
    }


def compare_hazard(a: dict, b: dict) -> dict:
    """Solar / hazard meta delta between snapshot payloads (if solar attached)."""
    ma, mb = snapshot_metrics(a), snapshot_metrics(b)
    sa = (a.get("solar") or {}) if isinstance(a.get("solar"), dict) else {}
    sb = (b.get("solar") or {}) if isinstance(b.get("solar"), dict) else {}
    ha = (sa.get("hazard") or {}) if isinstance(sa.get("hazard"), dict) else {}
    hb = (sb.get("hazard") or {}) if isinstance(sb.get("hazard"), dict) else {}
    score_a = ha.get("global_score", ma.get("hazard_score"))
    score_b = hb.get("global_score", mb.get("hazard_score"))
    try:
        d_score = (
            float(score_b) - float(score_a)
            if score_a is not None and score_b is not None
            else None
        )
    except (TypeError, ValueError):
        d_score = None
    return {
        "available": bool(sa or sb or score_a is not None or score_b is not None),
        "a": {
            "score": score_a,
            "severity": ha.get("severity") or ma.get("hazard_severity"),
        },
        "b": {
            "score": score_b,
            "severity": hb.get("severity") or mb.get("hazard_severity"),
        },
        "delta_score": d_score,
        "note": "Research proxy · attach solar on snapshot save for richer Δ.",
    }


def compare_density(a: dict, b: dict, *, include_sats: bool = True) -> dict:
    """Cell-level delta between two snapshot payloads (+ optional sat/hazard)."""
    da, db = _density_map(a), _density_map(b)
    keys = set(da) | set(db)
    grew = shrunk = same = appeared = vanished = 0
    delta_sum = 0
    top_up: List[dict] = []
    top_down: List[dict] = []
    cells_changed: List[dict] = []
    for k in keys:
        ca, cb = int(da.get(k, 0)), int(db.get(k, 0))
        d = cb - ca
        delta_sum += d
        if ca == 0 and cb > 0:
            appeared += 1
            kind = "appeared"
        elif ca > 0 and cb == 0:
            vanished += 1
            kind = "vanished"
        elif d > 0:
            grew += 1
            kind = "grew"
        elif d < 0:
            shrunk += 1
            kind = "shrunk"
        else:
            same += 1
            continue
        row = {
            "ilat": k[0],
            "ilon": k[1],
            "a": ca,
            "b": cb,
            "delta": d,
            "kind": kind,
            "count": abs(d) if kind in ("appeared", "vanished") else abs(d),
        }
        cells_changed.append(row)
        if d > 0:
            top_up.append(row)
        else:
            top_down.append(row)
    top_up.sort(key=lambda r: -r["delta"])
    top_down.sort(key=lambda r: r["delta"])
    cells_changed.sort(key=lambda r: -abs(r["delta"]))
    ma, mb = snapshot_metrics(a), snapshot_metrics(b)
    out = {
        "a": ma,
        "b": mb,
        "cells_union": len(keys),
        "grew": grew,
        "shrunk": shrunk,
        "same": same,
        "appeared": appeared,
        "vanished": vanished,
        "delta_sum_count": delta_sum,
        "top_up": top_up[:12],
        "top_down": top_down[:12],
        "cells_changed": cells_changed[:800],
        "nlat": int(b.get("nlat") or a.get("nlat") or 0) or None,
        "nlon": int(b.get("nlon") or a.get("nlon") or 0) or None,
        "grid_deg": b.get("grid_deg") or a.get("grid_deg"),
        "hazard_delta": compare_hazard(a, b),
        "note": (
            "Density cell delta · research compare. "
            "Vanished cells ≈ density loss regions (not SSA collisions). "
            "Optional NORAD diff when sats[] present."
        ),
    }
    if include_sats:
        out["sats_delta"] = compare_sats(a, b)
    return out


def timeline_from_store(
    store: Any,
    *,
    limit: int = 50,
) -> List[dict]:
    """
    Build timeline entries from SnapshotStore.list() + light metrics.
    store: adapters.snapshot_store.SnapshotStore
    """
    items = list(store.list())[: max(1, int(limit))]
    out: List[dict] = []
    for m in items:
        try:
            payload = store.load_raw(m.snapshot_id)
            met = snapshot_metrics(payload)
            met["path"] = str(getattr(m, "path", "") or "")
            out.append(met)
        except Exception:
            out.append(
                {
                    "snapshot_id": m.snapshot_id,
                    "created_at": m.created_at,
                    "cells": m.cells_count,
                    "sats_count": m.sats_count,
                    "error": "load_failed",
                }
            )
    # chronological ascending for charts
    out.sort(key=lambda x: str(x.get("created_at") or ""))
    return out


def amap_density_analytics(amap: Any) -> dict:
    """Live map analytics (same shape as /api/analyze core)."""
    dens = list((getattr(amap, "density", None) or {}).items())
    counts = sorted(int(c) for _, c in dens)
    total = sum(counts)
    max_c = counts[-1] if counts else 0
    hotspot = None
    for (ilat, ilon), c in dens:
        if int(c) == max_c:
            hotspot = {"ilat": ilat, "ilon": ilon, "count": int(c)}
            break

    def _pct(p: float) -> int:
        if not counts:
            return 0
        i = min(len(counts) - 1, max(0, int(round((p / 100.0) * (len(counts) - 1)))))
        return int(counts[i])

    top = sorted(
        ({"ilat": ilat, "ilon": ilon, "count": int(c)} for (ilat, ilon), c in dens),
        key=lambda x: -x["count"],
    )[:12]
    summ = amap.summary() if hasattr(amap, "summary") else {}
    return {
        "cells": len(counts),
        "sum_count": total,
        "max_count": max_c,
        "hotspot": hotspot,
        "p50": _pct(50),
        "p90": _pct(90),
        "top_cells": top,
        "shells": summ.get("shells") or {},
        "fleets": summ.get("fleets") or {},
        "countries": summ.get("countries") or {},
        "version": summ.get("version"),
    }
