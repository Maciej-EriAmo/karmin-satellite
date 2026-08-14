"""Storm bar = NOAA thresholds now or at the 6h horizon. Crowding = counts.

WATCH: Kp≥5, flare M/X, or hazard score≥55 — on current SWPC or H3 6h row.
No extra forecast equation. Not a magnetometer. Not CA.

Crowding (ops∩debris cells) is reported and does not fire the bar.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

KP_WATCH = 5.0
SCORE_WATCH = 55.0


def _as_map(obj: Any) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "as_dict"):
        obj = obj.as_dict()
    return obj if isinstance(obj, dict) else {}


def _horizon(predict: Any, label: str = "6h") -> dict:
    p = _as_map(predict)
    want = {label, label.replace("h", "")}
    for row in p.get("horizons") or []:
        if isinstance(row, dict) and str(row.get("label") or "") in want:
            return row
    return {}


def _wx_fields(weather: Any) -> dict:
    w = _as_map(weather)
    inner = w.get("weather") if isinstance(w.get("weather"), dict) else {}
    src = {**inner, **{k: v for k, v in w.items() if k != "weather"}}
    letter = str(src.get("flare_letter") or "").upper()[:1]
    if not letter and src.get("flare_class"):
        letter = str(src.get("flare_class"))[:1].upper()
    try:
        kp = float(src["kp"]) if src.get("kp") is not None else None
    except (TypeError, ValueError):
        kp = None
    try:
        score = float(src["global_score"]) if src.get("global_score") is not None else None
    except (TypeError, ValueError):
        score = None
    return {"kp": kp, "flare_letter": letter or "A", "score": score}


def _storm_hit(kp: Optional[float], letter: str, score: Optional[float]) -> bool:
    if kp is not None and kp >= KP_WATCH:
        return True
    if (letter or "A") in ("M", "X"):
        return True
    if score is not None and score >= SCORE_WATCH:
        return True
    return False


def assess_storm(weather: Any = None, predict: Any = None) -> Dict[str, Any]:
    now = _wx_fields(weather)
    h6 = _wx_fields(_horizon(predict, "6h"))
    kp_6h = h6["kp"]
    sc_6h = h6["score"]
    letter_6h = h6["flare_letter"] if h6.get("flare_letter") else now["flare_letter"]
    hit_now = _storm_hit(now["kp"], now["flare_letter"], now["score"])
    hit_6h = _storm_hit(kp_6h, letter_6h, sc_6h)
    rising = (
        now["kp"] is not None
        and kp_6h is not None
        and kp_6h > now["kp"] + 0.25
    )
    fire = hit_now or hit_6h
    if fire and hit_6h and not hit_now:
        kind = "rising" if rising else "forecast"
        kp_a = f"{now['kp']:.1f}" if now["kp"] is not None else "—"
        kp_b = f"{kp_6h:.1f}" if kp_6h is not None else "—"
        line = f"EM storm watch · Kp {kp_a} → 6h {kp_b} · public SWPC"
    elif fire:
        kind = "now"
        kp_s = f"{now['kp']:.1f}" if now["kp"] is not None else "—"
        line = f"EM storm now · Kp {kp_s} · flare {now['flare_letter']} · public SWPC"
    else:
        kind = "quiet"
        kp_s = f"{now['kp']:.1f}" if now["kp"] is not None else "—"
        line = f"quiet · Kp {kp_s} · flare {now['flare_letter']}"
    return {
        "alert": bool(fire),
        "kind": kind,
        "kp": None if now["kp"] is None else round(now["kp"], 2),
        "kp_6h": None if kp_6h is None else round(kp_6h, 2),
        "flare_letter": now["flare_letter"],
        "score": None if now["score"] is None else round(now["score"], 1),
        "score_6h": None if sc_6h is None else round(sc_6h, 1),
        "note": "Kp/flare/score now or H3 6h ≥ WATCH. public SWPC.",
        "line": line,
    }


def _is_debris_fleet(name: str) -> bool:
    n = (name or "").lower()
    return "debris" in n or n in {"junk", "orbital-debris"}


def _sat_fleet(amap: Any, aid: str) -> str:
    store = getattr(amap, "store", None)
    atom = store.get_atom(aid) if store is not None else None
    if atom is None:
        return ""
    v = dict(getattr(atom, "metadata", None) or {})
    meta = dict(v.get("v") or v)
    return str(meta.get("fleet") or "")


def cell_mix(amap: Any) -> Tuple[int, int, int, int]:
    """Current-map counts only."""
    cell_to_sats = getattr(amap, "cell_to_sats", None) or {}
    occupied = mixed = ops_only = debris_only = 0
    for sats in cell_to_sats.values():
        if not sats:
            continue
        occupied += 1
        has_ops = has_deb = False
        for aid in sats:
            if _is_debris_fleet(_sat_fleet(amap, str(aid))):
                has_deb = True
            else:
                has_ops = True
            if has_ops and has_deb:
                break
        if has_ops and has_deb:
            mixed += 1
        elif has_deb:
            debris_only += 1
        else:
            ops_only += 1
    if occupied == 0:
        dens = getattr(amap, "density", None) or {}
        occupied = sum(1 for c in dens.values() if int(c) > 0)
    return occupied, mixed, ops_only, debris_only


def assess_event_alert(
    amap: Any = None,
    *,
    weather: Any = None,
    predict: Any = None,
) -> Dict[str, Any]:
    storm = assess_storm(weather, predict)
    occupied = mixed = ops_only = debris_only = 0
    if amap is not None:
        occupied, mixed, ops_only, debris_only = cell_mix(amap)
    out = dict(storm)
    out["crowding"] = {
        "occupied": occupied,
        "mixed": mixed,
        "ops_only": ops_only,
        "debris_only": debris_only,
        "note": "current bins only",
    }
    return out
