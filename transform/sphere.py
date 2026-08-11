#!/usr/bin/env python3
"""
S2b: density cells → sphere quads for Three.js / WebGL.

Source of truth = amap.density (hot-only safe). Math: lat/lon clamp + lon wrap
(dateline noted in payload).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from engine.grid import cell_id, density_to_T, t_to_rgb


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


def export_sphere_data(
    amap: Any,
    *,
    alt_km: float = 400.0,
    radius: float = 1.0,
) -> dict:
    """Export density cells as sphere quads + colors (locked via snapshot density)."""
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

    proj = StarlinkGlobeProjection(radius_earth=radius)
    max_c = max(dens.values()) if dens else 1
    cells: List[dict] = []
    dateline_cells = 0

    for (ilat, ilon), count in dens.items():
        lon0 = -180.0 + ilon * grid_deg
        lon1 = -180.0 + (ilon + 1) * grid_deg
        # dateline if segment crosses ±180 after wrap
        if abs(proj.wrap_lon(lon1) - proj.wrap_lon(lon0)) > grid_deg * 1.5:
            dateline_cells += 1
        T = density_to_T(int(count), max_count=max_c)
        rgb = t_to_rgb(T)
        quad = proj.cell_to_sphere_quad(ilat, ilon, grid_deg, alt_km=alt_km)
        cells.append(
            {
                "id": cell_id(ilat, ilon),
                "ilat": ilat,
                "ilon": ilon,
                "quad": quad,
                "color": f"rgb({rgb[0]},{rgb[1]},{rgb[2]})",
                "T": round(T, 2),
                "count": int(count),
            }
        )

    return {
        "projection": "sphere",
        "version": version,
        "grid_deg": grid_deg,
        "policy": "hot-only" if hot_only else "full-grid",
        "cells": cells,
        "shells": shells,
        "stats": summary,
        "meta": {
            "count_cells": len(cells),
            "dateline_cells": dateline_cells,
            "alt_km": alt_km,
            "radius": radius,
        },
    }
