#!/usr/bin/env python3
"""
H5 — altitude bands + sunlit fraction (research geometry).

Public LEO context only:
  - altitude bands from sat alt_km after prop
  - sunlit via approximate subsolar geometry + Earth limb depression

Not operational eclipse prediction / SSA.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from engine.constants import R_EARTH

# Default LEO / Starlink-oriented bands (km)
DEFAULT_ALT_BANDS: Tuple[Tuple[str, float, float], ...] = (
    ("lt350", 0.0, 350.0),
    ("350-450", 350.0, 450.0),
    ("450-550", 450.0, 550.0),
    ("550-650", 550.0, 650.0),
    ("650-800", 650.0, 800.0),
    ("800-1200", 800.0, 1200.0),
    ("gt1200", 1200.0, 1.0e9),
)


def _utc(dt: Optional[datetime] = None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_of_year(dt: datetime) -> float:
    d = _utc(dt)
    start = datetime(d.year, 1, 1, tzinfo=timezone.utc)
    return (d - start).total_seconds() / 86400.0 + 1.0


def solar_declination_deg(dt: datetime) -> float:
    """Approximate solar declination (degrees)."""
    n = day_of_year(dt)
    # Spencer / NOAA-ish simple form
    return 23.44 * math.sin(math.radians(360.0 / 365.0 * (n - 81.0)))


def subsolar_longitude_deg(dt: datetime) -> float:
    """Longitude where sun is on meridian (approx, no EoT)."""
    d = _utc(dt)
    # 15° per hour; noon UTC → lon 0
    hours = d.hour + d.minute / 60.0 + d.second / 3600.0
    lon = 15.0 * (12.0 - hours)
    return ((lon + 180.0) % 360.0) - 180.0


def solar_elevation_deg(lat: float, lon: float, dt: datetime) -> float:
    """Solar elevation angle at ground point (degrees)."""
    dec = math.radians(solar_declination_deg(dt))
    lat_r = math.radians(float(lat))
    ha = math.radians(float(lon) - subsolar_longitude_deg(dt))
    sin_el = (
        math.sin(lat_r) * math.sin(dec)
        + math.cos(lat_r) * math.cos(dec) * math.cos(ha)
    )
    sin_el = max(-1.0, min(1.0, sin_el))
    return math.degrees(math.asin(sin_el))


def earth_limb_depression_deg(alt_km: float) -> float:
    """
    Max depression below horizon still seeing sun from altitude
    (geometric Earth disk, no atmosphere).
    """
    h = max(0.0, float(alt_km))
    ratio = R_EARTH / (R_EARTH + h)
    ratio = max(0.0, min(1.0, ratio))
    return math.degrees(math.acos(ratio))


def is_sunlit(
    lat: float,
    lon: float,
    alt_km: float,
    dt: Optional[datetime] = None,
) -> bool:
    """
    Research proxy: sunlit if solar elevation at sub-satellite point
    exceeds -limb_depression(alt).
    """
    when = _utc(dt)
    elev = solar_elevation_deg(lat, lon, when)
    limb = earth_limb_depression_deg(alt_km)
    return elev > -limb


def band_for_alt(
    alt_km: float,
    bands: Sequence[Tuple[str, float, float]] = DEFAULT_ALT_BANDS,
) -> str:
    a = float(alt_km)
    for name, lo, hi in bands:
        if lo <= a < hi:
            return name
    return bands[-1][0] if bands else "unknown"


@dataclass
class AltBandStat:
    band: str
    lo_km: float
    hi_km: float
    n_sats: int
    share: float
    sunlit: int
    sunlit_frac: float
    mean_alt_km: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ShellGeoStat:
    shell: str
    n_sats: int
    sunlit: int
    sunlit_frac: float
    mean_alt_km: float
    median_alt_km: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class GeoContext:
    """H5 aggregate: altitude bands + sunlit fractions."""

    as_of: str
    n_sats: int
    n_with_pos: int
    sunlit: int
    sunlit_frac: float
    eclipsed: int
    mean_alt_km: float
    median_alt_km: float
    min_alt_km: Optional[float]
    max_alt_km: Optional[float]
    bands: List[AltBandStat] = field(default_factory=list)
    shells: List[ShellGeoStat] = field(default_factory=list)
    method: str = "subsolar+limb"
    disclaimer: str = (
        "Geometric sunlit proxy (subsolar + Earth limb) — "
        "not operational eclipse ephemeris."
    )
    version: str = "geo-v1"

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "n_sats": self.n_sats,
            "n_with_pos": self.n_with_pos,
            "sunlit": self.sunlit,
            "sunlit_frac": self.sunlit_frac,
            "eclipsed": self.eclipsed,
            "mean_alt_km": self.mean_alt_km,
            "median_alt_km": self.median_alt_km,
            "min_alt_km": self.min_alt_km,
            "max_alt_km": self.max_alt_km,
            "bands": [b.as_dict() for b in self.bands],
            "shells": [s.as_dict() for s in self.shells],
            "method": self.method,
            "disclaimer": self.disclaimer,
            "version": self.version,
        }


def _median(xs: List[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def assess_geo_from_positions(
    rows: Sequence[dict],
    *,
    when: Optional[datetime] = None,
    bands: Sequence[Tuple[str, float, float]] = DEFAULT_ALT_BANDS,
) -> GeoContext:
    """
    rows: {lat, lon, alt_km, shell?} from sat metadata after prop.
    """
    when = _utc(when)
    alts: List[float] = []
    sunlit_n = 0
    band_acc: Dict[str, Dict[str, Any]] = {
        name: {"n": 0, "sun": 0, "alts": [], "lo": lo, "hi": hi}
        for name, lo, hi in bands
    }
    shell_acc: Dict[str, Dict[str, Any]] = {}

    for r in rows:
        try:
            lat = float(r["lat"])
            lon = float(r["lon"])
            alt = float(r["alt_km"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isnan(lat) or math.isnan(lon) or math.isnan(alt):
            continue
        alts.append(alt)
        lit = is_sunlit(lat, lon, alt, when)
        if lit:
            sunlit_n += 1
        bname = band_for_alt(alt, bands)
        ba = band_acc.get(bname)
        if ba is not None:
            ba["n"] += 1
            ba["alts"].append(alt)
            if lit:
                ba["sun"] += 1
        sk = str(r.get("shell") or "shell:?")
        sa = shell_acc.setdefault(sk, {"n": 0, "sun": 0, "alts": []})
        sa["n"] += 1
        sa["alts"].append(alt)
        if lit:
            sa["sun"] += 1

    n = len(alts)
    ecl = n - sunlit_n
    band_stats: List[AltBandStat] = []
    for name, lo, hi in bands:
        ba = band_acc[name]
        nn = int(ba["n"])
        ss = int(ba["sun"])
        band_stats.append(
            AltBandStat(
                band=name,
                lo_km=float(lo),
                hi_km=float(hi) if hi < 1e8 else 99999.0,
                n_sats=nn,
                share=round(nn / n, 4) if n else 0.0,
                sunlit=ss,
                sunlit_frac=round(ss / nn, 4) if nn else 0.0,
                mean_alt_km=round(sum(ba["alts"]) / nn, 1) if nn else 0.0,
            )
        )

    shell_stats: List[ShellGeoStat] = []
    for sk, sa in sorted(shell_acc.items(), key=lambda x: -x[1]["n"]):
        nn = int(sa["n"])
        ss = int(sa["sun"])
        a_list = sa["alts"]
        shell_stats.append(
            ShellGeoStat(
                shell=sk,
                n_sats=nn,
                sunlit=ss,
                sunlit_frac=round(ss / nn, 4) if nn else 0.0,
                mean_alt_km=round(sum(a_list) / nn, 1) if nn else 0.0,
                median_alt_km=round(_median(a_list), 1),
            )
        )

    return GeoContext(
        as_of=when.replace(microsecond=0).isoformat(),
        n_sats=n,
        n_with_pos=n,
        sunlit=sunlit_n,
        sunlit_frac=round(sunlit_n / n, 4) if n else 0.0,
        eclipsed=ecl,
        mean_alt_km=round(sum(alts) / n, 1) if n else 0.0,
        median_alt_km=round(_median(alts), 1) if n else 0.0,
        min_alt_km=round(min(alts), 1) if alts else None,
        max_alt_km=round(max(alts), 1) if alts else None,
        bands=band_stats,
        shells=shell_stats,
    )


def collect_sat_positions(amap: Any, *, max_sats: int = 50_000) -> List[dict]:
    """Pull lat/lon/alt/shell from sat atoms (after prop)."""
    rows: List[dict] = []
    if amap is None or not hasattr(amap, "iter_sats"):
        return rows
    for i, atom in enumerate(amap.iter_sats()):
        if i >= max_sats:
            break
        v = dict(atom.metadata.get("v") or {})
        if v.get("lat") is None or v.get("lon") is None or v.get("alt_km") is None:
            continue
        try:
            rows.append(
                {
                    "lat": float(v["lat"]),
                    "lon": float(v["lon"]),
                    "alt_km": float(v["alt_km"]),
                    "shell": str(v.get("shell") or ""),
                    "norad": v.get("norad"),
                }
            )
        except (TypeError, ValueError):
            continue
    return rows


def assess_geo_from_amap(
    amap: Any,
    *,
    when: Optional[datetime] = None,
    max_sats: int = 50_000,
) -> GeoContext:
    """H5 convenience: positions from StarlinkAtomMap sat metadata."""
    rows = collect_sat_positions(amap, max_sats=max_sats)
    return assess_geo_from_positions(rows, when=when)


def short_geo_line(geo: GeoContext) -> str:
    return (
        f"n={geo.n_with_pos} · sunlit={geo.sunlit_frac * 100:.0f}% "
        f"({geo.sunlit}/{geo.n_with_pos}) · "
        f"alt med={geo.median_alt_km:.0f} km "
        f"[{geo.min_alt_km or '—'}–{geo.max_alt_km or '—'}]"
    )
