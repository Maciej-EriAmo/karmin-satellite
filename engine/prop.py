"""Orbit propagation: SGP4 + approx fallback."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from engine.constants import HAS_SGP4, MU_EARTH, R_EARTH, sgp4_jday
from engine.tle import TleSat

def _deg2rad(d: float) -> float:
    return d * math.pi / 180.0


def _rad2deg(r: float) -> float:
    return r * 180.0 / math.pi


def _wrap_lon(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def gmst_rad(jd: float, fr: float = 0.0) -> float:
    """Greenwich mean sidereal time [rad] — wystarczy do heatmapy gęstości."""
    d = jd - 2451545.0 + fr
    return _deg2rad((280.46061837 + 360.98564736629 * d) % 360.0)


def teme_to_geodetic(r_km: Sequence[float], jd: float, fr: float) -> Tuple[float, float, float]:
    x, y, z = float(r_km[0]), float(r_km[1]), float(r_km[2])
    th = gmst_rad(jd, fr)
    c, s = math.cos(th), math.sin(th)
    # TEME → ECEF (obrót o GMST wokół Z)
    xe = c * x + s * y
    ye = -s * x + c * y
    ze = z
    lon = _wrap_lon(_rad2deg(math.atan2(ye, xe)))
    lat = _rad2deg(math.atan2(ze, math.hypot(xe, ye)))
    alt = math.sqrt(xe * xe + ye * ye + ze * ze) - R_EARTH
    return lat, lon, alt


def position_approx(sat: TleSat, minutes_from_epoch: float = 0.0) -> Tuple[float, float, float]:
    """Fallback bez sgp4 (Faza 0)."""
    n_rad_s = sat.mean_motion_rev_per_day * 2.0 * math.pi / 86400.0
    if n_rad_s <= 0:
        a = R_EARTH + 550.0
    else:
        a = (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)
    alt = max(0.0, a - R_EARTH)
    ma = (
        sat.mean_anomaly_deg
        + sat.mean_motion_rev_per_day * 360.0 * (minutes_from_epoch / 1440.0)
    ) % 360.0
    u = _deg2rad(ma)
    i = _deg2rad(sat.inclination_deg)
    raan = _deg2rad(sat.raan_deg)
    x = math.cos(u)
    y = math.sin(u) * math.cos(i)
    z = math.sin(u) * math.sin(i)
    xr = x * math.cos(raan) - y * math.sin(raan)
    yr = x * math.sin(raan) + y * math.cos(raan)
    zr = z
    lat = _rad2deg(math.atan2(zr, math.hypot(xr, yr)))
    lon = _wrap_lon(_rad2deg(math.atan2(yr, xr)) - 0.25 * minutes_from_epoch)
    return lat, lon, alt


def jd_fr_for(when: Optional[datetime], minutes: float = 0.0) -> Tuple[float, float]:
    """(jd, fr) for `when` shifted by `minutes`. Shared so a batch of satellites
    propagated for the same instant can compute this once instead of per-sat."""
    base = when or datetime.now(timezone.utc)
    if minutes:
        base = datetime.fromtimestamp(base.timestamp() + minutes * 60.0, tz=timezone.utc)
    return sgp4_jday(
        base.year,
        base.month,
        base.day,
        base.hour,
        base.minute,
        base.second + base.microsecond * 1e-6,
    )


def position_sgp4(
    sat: TleSat,
    when: Optional[datetime] = None,
    *,
    jd: Optional[float] = None,
    fr: Optional[float] = None,
) -> Optional[Tuple[float, float, float]]:
    if not HAS_SGP4:
        return None
    rec = sat.ensure_satrec()
    if rec is None:
        return None
    if jd is None or fr is None:
        jd, fr = jd_fr_for(when)
    err, r, _v = rec.sgp4(jd, fr)
    if err != 0 or r is None:
        return None
    return teme_to_geodetic(r, jd, fr)


def resolve_prop_mode(requested: str) -> str:
    req = (requested or "auto").lower()
    if req == "auto":
        return "sgp4" if HAS_SGP4 else "approx"
    if req == "sgp4" and not HAS_SGP4:
        print("WARN: sgp4 niedostępne (pip install sgp4) — approx", file=sys.stderr)
        return "approx"
    return req


def position_of(
    sat: TleSat,
    *,
    mode: str,
    when: Optional[datetime] = None,
    minutes: float = 0.0,
    jd: Optional[float] = None,
    fr: Optional[float] = None,
) -> Tuple[float, float, float]:
    if mode == "sgp4":
        if jd is None or fr is None:
            jd, fr = jd_fr_for(when, minutes)
        pos = position_sgp4(sat, jd=jd, fr=fr)
        if pos is not None:
            return pos
        raise ValueError("sgp4_failed")
    return position_approx(sat, minutes)

