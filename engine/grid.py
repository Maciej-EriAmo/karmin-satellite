"""Grid bins and thermal color mapping."""
from __future__ import annotations

from typing import Any, Tuple

from engine.bootstrap import ensure_paths

ensure_paths()
from karmazyn_kernel import T_MAX, T_TOMB, T_WARM, state_for_T  # noqa: E402

from engine.prop import _wrap_lon
import math

def cell_id(ilat: int, ilon: int) -> str:
    return f"cell:{ilat}:{ilon}"


def latlon_to_bin(lat: float, lon: float, deg: float) -> Tuple[int, int]:
    lat = max(-90.0, min(90.0, lat))
    lon = _wrap_lon(lon)
    ilat = int(math.floor((lat + 90.0) / deg))
    ilon = int(math.floor((lon + 180.0) / deg))
    nlat = int(math.ceil(180.0 / deg))
    nlon = int(math.ceil(360.0 / deg))
    return min(max(0, ilat), nlat - 1), min(max(0, ilon), nlon - 1)


def density_to_T(count: int, *, max_count: int) -> float:
    cold_floor = max(float(T_TOMB) + 4.0, 8.0)
    if count <= 0:
        return cold_floor
    if max_count <= 0:
        max_count = 1
    t = T_WARM + (T_MAX - T_WARM) * (math.log1p(count) / math.log1p(max_count))
    return max(cold_floor, min(T_MAX, t))


def t_to_rgb(T: float) -> Tuple[int, int, int]:
    x = max(0.0, min(1.0, T / T_MAX))
    if x < 0.33:
        k = x / 0.33
        return (0, int(40 + 80 * k), int(80 + 175 * k))
    if x < 0.66:
        k = (x - 0.33) / 0.33
        return (int(255 * k), int(200 + 55 * k), int(255 * (1 - k)))
    k = (x - 0.66) / 0.34
    return (255, int(255 * (1 - k)), 0)


def _set_T(atom: Any, T: float) -> None:
    atom.T = float(T)
    if hasattr(atom, "_update_state"):
        atom._update_state()
    else:
        atom.state = state_for_T(atom.T)

