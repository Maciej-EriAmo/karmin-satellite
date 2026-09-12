#!/usr/bin/env python3
"""
S2b / H6: density cells → sphere quads for Three.js / WebGL.

Source of truth = amap.density (hot-only safe). Math: lat/lon clamp + lon wrap
(dateline noted in payload).

Layers:
  density   — thermal T from count (classic)
  radiation — H6 solar exposure proxy (score × density weight)
  blend     — mix density + radiation colors
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from engine.grid import cell_id, density_to_T, t_to_rgb


def radiation_to_rgb(exposure: float, max_exp: float = 100.0) -> Tuple[int, int, int]:
    """
    Purple→magenta→red ramp for solar exposure (matches 2D hazard palette).
    Distinct from density thermal ramp.
    """
    mc = max_exp if max_exp > 0 else 100.0
    x = max(0.0, min(1.0, float(exposure or 0.0) / mc))
    if x < 0.4:
        k = x / 0.4
        return (
            int(20 + 80 * k),
            int(10 + 20 * k),
            int(60 + 100 * k),
        )
    if x < 0.75:
        k = (x - 0.4) / 0.35
        return (
            int(100 + 120 * k),
            int(30 + 40 * k),
            int(160 + 40 * k),
        )
    k = (x - 0.75) / 0.25
    return (
        int(220 + 35 * k),
        int(40 * (1 - k)),
        int(80 * (1 - k)),
    )


def _blend_rgb(
    a: Tuple[int, int, int], b: Tuple[int, int, int], w: float = 0.5
) -> Tuple[int, int, int]:
    w = max(0.0, min(1.0, float(w)))
    return (
        int(a[0] * (1 - w) + b[0] * w),
        int(a[1] * (1 - w) + b[1] * w),
        int(a[2] * (1 - w) + b[2] * w),
    )


def _rgb_css(rgb: Tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def _exposure_weight(count: int, max_count: int) -> float:
    mc = max(1, int(max_count))
    c = max(0, int(count))
    return 0.3 + 0.7 * (math.log1p(c) / math.log1p(mc))


class StarlinkGlobeProjection:
    """lat/lon/alt → unit-sphere-ish coords (Earth radius = r)."""

    def __init__(self, radius_earth: float = 1.0):
        self.r = float(radius_earth)

    def latlon_to_xyz(
        self, lat: float, lon: float, alt_km: float = 400.0
    ) -> Tuple[float, float, float]:
        # slight altitude offset so cells sit above surface mesh
        scale = self.r * (1.0 + max(0.0, alt_km) / 6378.137 * 0.08)
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        cl = math.cos(lat_rad)
        x = scale * cl * math.cos(lon_rad)
        y = scale * math.sin(lat_rad)
        z = scale * cl * math.sin(lon_rad)
        return (x, y, z)

    @staticmethod
    def wrap_lon(lon: float) -> float:
        return ((lon + 180.0) % 360.0) - 180.0

    def cell_to_sphere_quad(
        self,
        ilat: int,
        ilon: int,
        grid_deg: float = 5.0,
        alt_km: float = 400.0,
    ) -> List[List[float]]:
        lat0 = max(-90.0, min(90.0, -90.0 + ilat * grid_deg))
        lat1 = max(-90.0, min(90.0, -90.0 + (ilat + 1) * grid_deg))
        lon0 = self.wrap_lon(-180.0 + ilon * grid_deg)
        lon1 = self.wrap_lon(-180.0 + (ilon + 1) * grid_deg)
        corners = [
            (lat0, lon0),
            (lat1, lon0),
            (lat1, lon1),
            (lat0, lon1),
        ]
        return [
            list(self.latlon_to_xyz(lat, lon, alt_km)) for lat, lon in corners
        ]


def _resolve_base_score(
    assessment: Any,
    *,
    shell: str = "all",
    base_score: Optional[float] = None,
) -> Tuple[Optional[float], str]:
    if base_score is not None:
        return float(base_score), "INFO"
    if assessment is None:
        return None, "NONE"
    try:
        from engine.solar.hazard import base_score_for_shell, severity_for_score

        sc = float(base_score_for_shell(assessment, shell))
        w = getattr(assessment, "weather", None) or {}
        if isinstance(assessment, dict):
            w = assessment.get("weather") or {}
            sc = float(assessment.get("global_score") or sc)
        letter = str((w or {}).get("flare_class") or "A")[:1]
        kp = (w or {}).get("kp")
        sev = severity_for_score(sc, flare_letter=letter, kp=kp)
        return sc, sev
    except Exception:
        g = getattr(assessment, "global_score", None)
        if g is None and isinstance(assessment, dict):
            g = assessment.get("global_score")
        if g is None:
            return None, "NONE"
        return float(g), "INFO"


def export_sphere_data(
    amap: Any,
    *,
    layer: str = "density",
    assessment: Any = None,
    base_score: Optional[float] = None,
    shell: str = "all",
    min_count: int = 1,
    alt_km: float = 400.0,
    radius: float = 1.0,
    intensity_lift: bool = True,
) -> dict:
    """
    Export density cells as sphere quads + colors.

    ``layer``:
      density   — T from count
      radiation — H6 exposure proxy (solar score × density weight)
      intensity — alias of radiation
      hazard    — alias of radiation
      blend     — 50/50 density + radiation color
    """
    layer_key = (layer or "density").strip().lower()
    if layer_key in ("intensity", "hazard", "rad", "solar"):
        layer_key = "radiation"
    if layer_key not in ("density", "radiation", "blend"):
        layer_key = "density"

    # Prefer atomic density copy
    if hasattr(amap, "snapshot"):
        snap = amap.snapshot()
        dens_list = snap.get("density") or []
        dens = {
            (int(d["ilat"]), int(d["ilon"])): int(d["count"]) for d in dens_list
        }
        shells = snap.get("shells") or {}
        summary = snap.get("summary") or {}
        version = snap.get("version", getattr(amap, "version", 0))
        grid_deg = float(snap.get("grid_deg") or amap.grid_deg)
        hot_only = bool(snap.get("hot_only", getattr(amap, "hot_only", True)))
    else:
        dens = dict(getattr(amap, "density", {}) or {})
        shells = dict(getattr(amap, "_shells", {}) or {})
        summary = amap.summary() if callable(getattr(amap, "summary", None)) else {}
        version = getattr(amap, "version", 0)
        grid_deg = float(amap.grid_deg)
        hot_only = bool(getattr(amap, "hot_only", True))

    # optional shell filter via amap when available
    if shell and shell not in ("all", "*", ""):
        if hasattr(amap, "filter_density") and callable(amap.filter_density):
            filtered = amap.filter_density(shell=shell, min_count=int(min_count))
            dens = {
                (int(d["ilat"]), int(d["ilon"])): int(d["count"])
                for d in (filtered.get("density") or [])
            }
        else:
            dens = {k: v for k, v in dens.items() if int(v) >= int(min_count)}
    else:
        dens = {k: v for k, v in dens.items() if int(v) >= int(min_count)}

    proj = StarlinkGlobeProjection(radius_earth=radius)
    max_c = max(dens.values()) if dens else 1
    max_c = max(1, int(max_c))

    need_rad = layer_key in ("radiation", "blend")
    bscore, severity = (0.0, "NONE")
    solar_available = False
    if need_rad:
        got, severity = _resolve_base_score(
            assessment, shell=shell, base_score=base_score
        )
        if got is None:
            # do not invent a radiation field — show density and say so
            layer_key = "density"
            need_rad = False
            severity = "NONE"
        else:
            bscore = float(got)
            solar_available = True

    cells: List[dict] = []
    dateline_cells = 0
    exposures: List[float] = []

    for (ilat, ilon), count in dens.items():
        c = int(count)
        lon0 = -180.0 + ilon * grid_deg
        lon1 = -180.0 + (ilon + 1) * grid_deg
        if abs(proj.wrap_lon(lon1) - proj.wrap_lon(lon0)) > grid_deg * 1.5:
            dateline_cells += 1

        T = density_to_T(c, max_count=max_c)
        dens_rgb = t_to_rgb(T)
        exposure = round(min(100.0, max(0.0, bscore * _exposure_weight(c, max_c))), 2)
        if need_rad:
            exposures.append(exposure)
        rad_rgb = radiation_to_rgb(exposure, max_exp=max(bscore, 1.0))

        if layer_key == "radiation":
            rgb = rad_rgb
            # mild geometric lift for high intensity (visual only)
            cell_alt = float(alt_km)
            if intensity_lift:
                cell_alt = alt_km + (exposure / 100.0) * 120.0
            opacity = round(0.45 + 0.50 * min(1.0, exposure / max(bscore, 1.0)), 3)
        elif layer_key == "blend":
            w = min(1.0, exposure / max(bscore, 1.0)) * 0.55 + 0.25
            rgb = _blend_rgb(dens_rgb, rad_rgb, w)
            cell_alt = float(alt_km)
            if intensity_lift:
                cell_alt = alt_km + (exposure / 100.0) * 60.0
            opacity = 0.85
        else:
            rgb = dens_rgb
            cell_alt = float(alt_km)
            opacity = 0.85

        quad = proj.cell_to_sphere_quad(ilat, ilon, grid_deg, alt_km=cell_alt)
        cell: Dict[str, Any] = {
            "id": cell_id(ilat, ilon),
            "ilat": ilat,
            "ilon": ilon,
            "quad": quad,
            "color": _rgb_css(rgb),
            "T": round(T, 2),
            "count": c,
            "opacity": opacity,
        }
        if need_rad:
            cell["exposure"] = exposure
            cell["base_score"] = round(bscore, 2)
        cells.append(cell)

    max_exp = max(exposures) if exposures else 0.0
    mean_exp = round(sum(exposures) / len(exposures), 2) if exposures else 0.0

    return {
        "projection": "sphere",
        "layer": layer_key,
        "version": version,
        "grid_deg": grid_deg,
        "policy": "hot-only" if hot_only else "full-grid",
        "cells": cells,
        "shells": shells,
        "stats": summary,
        "solar": {
            "available": solar_available,
            "base_score": round(bscore, 2) if solar_available else None,
            "severity": severity if solar_available else None,
            "shell": shell if shell not in ("", "*") else "all",
            "max_exposure": max_exp,
            "mean_exposure": mean_exp,
            "note": (
                "3D exposure = solar score × density weight; "
                "research proxy, not physical dose."
                if solar_available
                else "density thermal layer (no weather — not radiation)"
            ),
        },
        "meta": {
            "count_cells": len(cells),
            "dateline_cells": dateline_cells,
            "alt_km": alt_km,
            "radius": radius,
            "layer": layer_key,
            "min_count": int(min_count),
        },
    }
