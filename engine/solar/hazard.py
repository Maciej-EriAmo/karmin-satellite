#!/usr/bin/env python3
"""
Solar hazard scores for Starlink groups (public-index proxy).

Maps NOAA SWPC indices (F10.7, X-ray flare class, Kp) onto constellation
aggregates — primarily orbital inclination shells already tracked by
StarlinkAtomMap.

This is a research heuristic for enthusiasts, NOT operational radiation
or collision certification.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Flare letter contribution to 0..100 score
_FLARE_BASE = {"A": 5, "B": 15, "C": 30, "M": 55, "X": 80}


@dataclass
class HazardGroup:
    group_id: str
    kind: str  # constellation | shell
    n_sats: int
    share: float  # 0..1 of constellation
    score: float  # 0..100
    severity: str  # INFO | WATCH | WARNING
    drivers: List[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class HazardAssessment:
    as_of: str
    weather: dict
    global_score: float
    severity: str
    drivers: List[str]
    groups: List[HazardGroup]
    disclaimer: str = (
        "Public-index proxy for research — not operational certification."
    )
    version: str = "hazard-v1"

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "weather": self.weather,
            "global_score": self.global_score,
            "severity": self.severity,
            "drivers": self.drivers,
            "groups": [g.as_dict() for g in self.groups],
            "disclaimer": self.disclaimer,
            "version": self.version,
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def flare_component(letter: str, mag: float) -> Tuple[float, str]:
    base = float(_FLARE_BASE.get((letter or "A").upper()[:1], 10))
    # within-class magnitude (e.g. M2.5 → + up to ~12)
    m = max(0.0, min(9.9, float(mag or 0.0)))
    score = base + min(15.0, m * 1.5)
    return score, f"flare:{letter}{m:.1f}"


def f107_component(f107: Optional[float]) -> Tuple[float, str]:
    """F10.7: quiet ~70, moderate ~120, high ~200+."""
    if f107 is None:
        return 10.0, "f107:unknown"
    f = float(f107)
    if f <= 70:
        s = 5.0 + (f / 70.0) * 5.0
    elif f <= 150:
        s = 10.0 + (f - 70.0) / 80.0 * 25.0
    else:
        s = 35.0 + min(25.0, (f - 150.0) / 100.0 * 25.0)
    return s, f"f107:{f:.0f}"


def kp_component(kp: Optional[float]) -> Tuple[float, str]:
    """Kp 0–9 → geomagnetic contribution."""
    if kp is None:
        return 5.0, "kp:unknown"
    k = max(0.0, min(9.0, float(kp)))
    # roughly: Kp0–2 calm, 5 storm, 8+ severe
    s = (k / 9.0) ** 1.2 * 40.0
    return s, f"kp:{k:.2f}"


def combine_global(
    *,
    flare_letter: str,
    flare_mag: float,
    f107: Optional[float],
    kp: Optional[float],
) -> Tuple[float, List[str]]:
    """
    Weighted mix → 0..100.
    Weights emphasize impulsive flare + geomagnetic, F10.7 as background.
    """
    fl, d1 = flare_component(flare_letter, flare_mag)
    f1, d2 = f107_component(f107)
    k1, d3 = kp_component(kp)
    # normalize component ranges loosely then weight
    score = 0.45 * fl + 0.25 * f1 + 0.30 * (k1 * 2.0)  # kp already 0..40
    # re-scale: typical calm ~15–25, M+Kp5 ~60+
    score = _clamp(score * 0.95)
    drivers = [d1, d2, d3]
    return round(score, 1), drivers


def severity_for_score(
    score: float,
    *,
    flare_letter: str = "A",
    kp: Optional[float] = None,
) -> str:
    letter = (flare_letter or "A").upper()[:1]
    k = float(kp or 0.0)
    if letter == "X" or k >= 7.0 or score >= 80:
        return "WARNING"
    if letter == "M" or k >= 5.0 or score >= 55:
        return "WATCH"
    return "INFO"


def group_score_adjust(
    global_score: float,
    *,
    n_sats: int,
    total_sats: int,
    shell_key: str = "",
) -> Tuple[float, List[str], str]:
    """
    Per-shell adjustment: larger groups inherit global; polar shells get
    slight geomagnetic emphasis (research heuristic only).
    """
    extra_drivers: List[str] = []
    adj = 0.0
    # parse inclination from shell:53
    inc = None
    sk = shell_key or ""
    if sk.startswith("shell:"):
        try:
            inc = float(sk.split(":", 1)[1])
        except ValueError:
            inc = None
    if inc is not None:
        # mid/high inclination: modest + for geomagnetic coupling proxy
        if inc >= 70:
            adj += 4.0
            extra_drivers.append("high_inc")
        elif inc >= 50:
            adj += 2.0
            extra_drivers.append("mid_inc")
        elif inc <= 20:
            adj -= 1.0
            extra_drivers.append("low_inc")

    share = (n_sats / total_sats) if total_sats > 0 else 0.0
    # tiny density-of-attention bump for large shells (more sats under same weather)
    if share >= 0.4:
        adj += 1.5
        extra_drivers.append("large_group")

    score = _clamp(global_score + adj)
    note = f"{n_sats} sats ({share * 100:.0f}% of map)"
    return round(score, 1), extra_drivers, note


def assess_hazard(
    weather: Any,
    *,
    shells: Optional[Dict[str, int]] = None,
    total_sats: Optional[int] = None,
) -> HazardAssessment:
    """
    Build global + per-shell hazard from a SpaceWeatherSnapshot (or dict)
    and shell counts from amap.summary()['shells'].
    """
    if hasattr(weather, "as_dict"):
        w = weather.as_dict()
    else:
        w = dict(weather or {})

    letter = str(w.get("flare_letter") or "A")
    mag = float(w.get("flare_mag") or 0.0)
    # parse from flare_class if letter missing
    if not w.get("flare_letter") and w.get("flare_class"):
        fc = str(w["flare_class"])
        letter = fc[:1] if fc else "A"
        try:
            mag = float(fc[1:]) if len(fc) > 1 else 0.0
        except ValueError:
            mag = 0.0

    f107 = w.get("f107")
    kp = w.get("kp")
    gscore, drivers = combine_global(
        flare_letter=letter,
        flare_mag=mag,
        f107=float(f107) if f107 is not None else None,
        kp=float(kp) if kp is not None else None,
    )
    sev = severity_for_score(gscore, flare_letter=letter, kp=float(kp) if kp is not None else None)

    shell_map = dict(shells or {})
    tot = int(total_sats) if total_sats is not None else sum(int(v) for v in shell_map.values())
    groups: List[HazardGroup] = [
        HazardGroup(
            group_id="constellation",
            kind="constellation",
            n_sats=tot,
            share=1.0,
            score=gscore,
            severity=sev,
            drivers=list(drivers),
            note="entire map / active fleet",
        )
    ]

    for sk, n in sorted(shell_map.items(), key=lambda x: -int(x[1])):
        n_i = int(n)
        sc, extra, note = group_score_adjust(
            gscore, n_sats=n_i, total_sats=tot or 1, shell_key=str(sk)
        )
        gsev = severity_for_score(sc, flare_letter=letter, kp=float(kp) if kp is not None else None)
        groups.append(
            HazardGroup(
                group_id=str(sk),
                kind="shell",
                n_sats=n_i,
                share=round((n_i / tot) if tot else 0.0, 4),
                score=sc,
                severity=gsev,
                drivers=list(drivers) + extra,
                note=note,
            )
        )

    return HazardAssessment(
        as_of=str(w.get("as_of") or w.get("fetched_at") or ""),
        weather={
            "flare_class": w.get("flare_class"),
            "f107": w.get("f107"),
            "kp": w.get("kp"),
            "mode": w.get("mode"),
            "source": w.get("source"),
            "xray_flux": w.get("xray_flux"),
        },
        global_score=gscore,
        severity=sev,
        drivers=drivers,
        groups=groups,
    )


def assess_from_amap(
    amap: Any,
    weather: Any,
) -> HazardAssessment:
    """Convenience: pull shells + sats from StarlinkAtomMap."""
    shells: Dict[str, int] = {}
    total = 0
    if amap is not None:
        if hasattr(amap, "summary") and callable(amap.summary):
            summ = amap.summary()
            shells = dict(summ.get("shells") or {})
            total = int(summ.get("sats") or 0)
        elif hasattr(amap, "_shells"):
            shells = dict(amap._shells or {})
            total = sum(shells.values())
    return assess_hazard(weather, shells=shells, total_sats=total or None)


def short_badge(assessment: HazardAssessment) -> str:
    """One-line UI badge text."""
    w = assessment.weather or {}
    fc = w.get("flare_class") or "?"
    f107 = w.get("f107")
    kp = w.get("kp")
    f107_s = f"{float(f107):.0f}" if f107 is not None else "—"
    kp_s = f"{float(kp):.1f}" if kp is not None else "—"
    return (
        f"{fc} · F10.7={f107_s} · Kp={kp_s} · "
        f"stress={assessment.global_score:.0f} · {assessment.severity}"
    )


def base_score_for_shell(
    assessment: HazardAssessment,
    shell: str = "all",
) -> float:
    """Pick constellation or matching shell score for map overlay."""
    sk = (shell or "all").strip()
    if sk in ("", "all", "*"):
        return float(assessment.global_score)
    if not sk.startswith("shell:"):
        sk = f"shell:{sk}"
    for g in assessment.groups:
        if g.kind == "shell" and g.group_id == sk:
            return float(g.score)
    return float(assessment.global_score)


def exposure_cells(
    density: Sequence[Any],
    base_score: float,
    *,
    min_count: int = 1,
) -> List[dict]:
    """
    H2: map-level solar exposure proxy for 2D overlay (cells-scale, SLA-safe).

    exposure ∈ [0, 100] ≈ base_score × density weight (log count).
    Not physical irradiance — research visualization only.
    """
    rows: List[Tuple[int, int, int]] = []
    for d in density or []:
        if isinstance(d, dict):
            try:
                ilat = int(d["ilat"])
                ilon = int(d["ilon"])
                count = int(d.get("count") or 0)
            except (KeyError, TypeError, ValueError):
                continue
        elif isinstance(d, (list, tuple)) and len(d) >= 3:
            ilat, ilon, count = int(d[0]), int(d[1]), int(d[2])
        else:
            continue
        if count < int(min_count):
            continue
        rows.append((ilat, ilon, count))

    max_c = max((c for _, _, c in rows), default=1)
    max_c = max(1, max_c)
    bs = _clamp(float(base_score))
    out: List[dict] = []

    for ilat, ilon, count in rows:
        # 0.3 floor so even sparse cells show global weather context
        weight = 0.3 + 0.7 * (math.log1p(count) / math.log1p(max_c))
        exposure = round(_clamp(bs * weight), 2)
        out.append(
            {
                "ilat": ilat,
                "ilon": ilon,
                "count": count,
                "exposure": exposure,
                "base_score": round(bs, 2),
            }
        )
    return out


def build_overlay(
    assessment: HazardAssessment,
    density: Sequence[Any],
    *,
    shell: str = "all",
    min_count: int = 1,
) -> dict:
    """Package for GET /api/hazard?grid=1 and UI blend mode."""
    base = base_score_for_shell(assessment, shell)
    cells = exposure_cells(density, base, min_count=min_count)
    exps = [c["exposure"] for c in cells]
    return {
        "shell": shell if shell not in ("", "*") else "all",
        "base_score": round(base, 2),
        "severity": severity_for_score(
            base,
            flare_letter=str((assessment.weather or {}).get("flare_class") or "A")[:1],
            kp=(assessment.weather or {}).get("kp"),
        ),
        "cells": cells,
        "n_cells": len(cells),
        "max_exposure": max(exps) if exps else 0.0,
        "mean_exposure": round(sum(exps) / len(exps), 2) if exps else 0.0,
        "note": (
            "2D exposure = solar score × density weight; "
            "not physical radiation; 3D radiation layer available via /api/sphere?layer=radiation."
        ),
    }
