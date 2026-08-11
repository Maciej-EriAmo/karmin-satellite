#!/usr/bin/env python3
"""
starlink_atoms.py — Starlink engine for Cynober Studio
======================================================
Public TLE → sat+cell + bubbles → heatmap / HTML.

Vendored thermal atom substrate lives in ../substrate (pure-Python).
KarmazynOs is optional later (Lua tools, native slab) — not required to run.

  Docs: docs/STARLINK_ATOMS.md · docs/CYNOBER_STUDIO_PLAN.md

  python -m engine.starlink_atoms --offline-demo --limit 40 --hot-only
  python main.py --offline-demo --limit 40 --html
  python main.py --limit 0 --prop sgp4 --hot-only --html

Model: root bubble starlink → sats / grid / shell:N
Law: T = when (heatmap), reach = whether (GC).
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
_SUBSTRATE = ROOT / "substrate"
if str(_SUBSTRATE) not in sys.path:
    sys.path.insert(0, str(_SUBSTRATE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Studio is standalone: pure-Python store (native/Lua = optional KarmazynOs bridge later)
os.environ.setdefault("KARMAZYN_SUBSTRATE", "python")

from karmazyn_kernel import (  # noqa: E402
    T_HOT,
    T_INIT,
    T_MAX,
    T_TOMB,
    T_WARM,
    open_store,
    state_for_T,
)

CELESTRAK_URLS = (
    "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php?FILE=starlink&FORMAT=tle",
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink&FORMAT=tle",
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
S_SAT = "starlink:sat"
S_CELL = "starlink:cell"
MU_EARTH = 398600.4418
R_EARTH = 6378.137

try:
    from sgp4.api import Satrec, jday as sgp4_jday

    _HAS_SGP4 = True
except Exception:
    Satrec = None  # type: ignore
    sgp4_jday = None  # type: ignore
    _HAS_SGP4 = False


# ─── TLE ─────────────────────────────────────────────────────────────────────


@dataclass
class TleSat:
    name: str
    line1: str
    line2: str
    norad: int
    inclination_deg: float
    raan_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_per_day: float
    ecc: float
    _satrec: Any = field(default=None, repr=False, compare=False)

    @property
    def shell_key(self) -> str:
        return f"shell:{int(round(self.inclination_deg))}"

    def ensure_satrec(self) -> Any:
        if not _HAS_SGP4:
            return None
        if self._satrec is None:
            self._satrec = Satrec.twoline2rv(self.line1, self.line2)
        return self._satrec


def parse_tle_catalog(text: str) -> List[TleSat]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[TleSat] = []
    i = 0
    while i + 2 < len(lines):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if not (l1.startswith("1 ") and l2.startswith("2 ")):
            i += 1
            continue
        try:
            norad = int(l1[2:7])
            inc = float(l2[8:16])
            raan = float(l2[17:25])
            ecc = float("0." + l2[26:33].strip())
            ma = float(l2[43:51])
            n = float(l2[52:63])
        except (ValueError, IndexError):
            i += 3
            continue
        out.append(
            TleSat(
                name=name,
                line1=l1,
                line2=l2,
                norad=norad,
                inclination_deg=inc,
                raan_deg=raan,
                mean_anomaly_deg=ma,
                mean_motion_rev_per_day=n,
                ecc=ecc,
            )
        )
        i += 3
    return out


def fetch_starlink_tle(timeout: float = 60.0) -> Tuple[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"}
    errors: List[str] = []
    for url in CELESTRAK_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            if "1 " in text and "2 " in text:
                return text, url
            errors.append(f"{url}: empty/invalid")
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("Celestrak fetch failed: " + " | ".join(errors))


def demo_tle_blob(n: int = 12) -> str:
    parts: List[str] = []
    for i in range(n):
        norad = 50000 + i
        name = f"STARLINK-DEMO-{i:04d}"
        inc = 53.0 + (i % 5) * 0.1
        raan = (i * 30.0) % 360.0
        ma = (i * 17.0) % 360.0
        nn = 15.06 + (i % 7) * 0.01
        l1 = f"1 {norad:05d}U 00000A   26001.00000000  .00000000  00000-0  00000-0 0  9990"
        l2 = (
            f"2 {norad:05d} {inc:8.4f} {raan:8.4f} 0001000 "
            f"000.0000 {ma:8.4f} {nn:11.8f}"
        )
        parts.extend([name, l1, l2])
    return "\n".join(parts) + "\n"


def load_tle_text(
    *,
    offline_demo: bool,
    cache: Path,
    limit_hint: int,
    cache_ttl_hours: float = 12.0,
) -> Tuple[str, str]:
    if offline_demo:
        return demo_tle_blob(max(12, limit_hint or 12)), "offline-demo"
    raw = None
    src = ""
    ttl = max(0.0, float(cache_ttl_hours)) * 3600.0
    if cache.is_file() and cache.stat().st_size > 100:
        age = time.time() - cache.stat().st_mtime
        if ttl <= 0 or age < ttl:
            return (
                cache.read_text(encoding="utf-8", errors="replace"),
                f"cache:{cache} ({age / 3600:.1f}h)",
            )
    try:
        raw, url = fetch_starlink_tle()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw, encoding="utf-8")
        return raw, f"celestrak:{url.split('/')[-1]}"
    except Exception as e:
        if cache.is_file():
            return (
                cache.read_text(encoding="utf-8", errors="replace"),
                f"cache-fallback ({e})",
            )
        raise


# ─── Math / propagate ────────────────────────────────────────────────────────


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


def position_sgp4(
    sat: TleSat,
    when: Optional[datetime] = None,
) -> Optional[Tuple[float, float, float]]:
    if not _HAS_SGP4:
        return None
    rec = sat.ensure_satrec()
    if rec is None:
        return None
    when = when or datetime.now(timezone.utc)
    jd, fr = sgp4_jday(
        when.year,
        when.month,
        when.day,
        when.hour,
        when.minute,
        when.second + when.microsecond * 1e-6,
    )
    err, r, _v = rec.sgp4(jd, fr)
    if err != 0 or r is None:
        return None
    return teme_to_geodetic(r, jd, fr)


def resolve_prop_mode(requested: str) -> str:
    req = (requested or "auto").lower()
    if req == "auto":
        return "sgp4" if _HAS_SGP4 else "approx"
    if req == "sgp4" and not _HAS_SGP4:
        print("WARN: sgp4 niedostępne (pip install sgp4) — approx", file=sys.stderr)
        return "approx"
    return req


def position_of(
    sat: TleSat,
    *,
    mode: str,
    when: Optional[datetime] = None,
    minutes: float = 0.0,
) -> Tuple[float, float, float]:
    if mode == "sgp4":
        base = when or datetime.now(timezone.utc)
        if minutes:
            base = datetime.fromtimestamp(
                base.timestamp() + minutes * 60.0, tz=timezone.utc
            )
        pos = position_sgp4(sat, base)
        if pos is not None:
            return pos
        return position_approx(sat, minutes)
    return position_approx(sat, minutes)


# ─── Grid / heat ─────────────────────────────────────────────────────────────


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


# ─── Store map ───────────────────────────────────────────────────────────────


class StarlinkAtomMap:
    """Hybryda sat+cell + bąble; full grid lub hot-only.

    Studio-ready (Faza 1): RLock, version, snapshot(), shell_index,
    filter_density(), sat GC on refresh. density dict = source of truth
    for hot-only visualization.
    """

    def __init__(
        self,
        store: Any,
        *,
        grid_deg: float = 5.0,
        hot_only: bool = False,
        prop_mode: str = "auto",
        listen: bool = True,
    ):
        self.store = store
        self.grid_deg = float(grid_deg)
        self.hot_only = bool(hot_only)
        self.prop_mode = resolve_prop_mode(prop_mode)
        self.state_changes = 0
        self._lock = RLock()
        self.version: int = 0
        self._shells: Dict[str, int] = {}
        self._shell_index: Dict[str, Set[str]] = {}
        self._active_cells: Set[Tuple[int, int]] = set()
        self.density: Dict[Tuple[int, int], int] = {}
        self.last_prop_ms: float = 0.0
        self.last_error_sats: int = 0
        self.last_prop_errors: List[Tuple[int, str]] = []
        self.last_gc_sats: int = 0

        store.create_bubble("starlink", root=True)
        store.create_bubble("sats")
        store.create_bubble("grid")
        if listen and hasattr(store, "events"):
            store.events.on("state_changed", self._on_state)

    def _on_state(self, atom: Any) -> None:
        self.state_changes += 1

    def get_export_version(self) -> int:
        return self.version

    def _ensure_shell_bubble(self, key: str) -> None:
        if key not in self._shell_index:
            self.store.create_bubble(key)
            self._shell_index[key] = set()

    def ingest_sats(self, sats: Sequence[TleSat], *, gc_missing: bool = False) -> int:
        """Upsert sat atoms. gc_missing=True removes sats not in catalog (refresh path)."""
        with self._lock:
            return self._ingest_sats_unlocked(sats, gc_missing=gc_missing)

    def ensure_sats(self, sats: Sequence[TleSat]) -> int:
        """Upsert + GC martwych satów (audit #12)."""
        return self.ingest_sats(sats, gc_missing=True)

    def _ingest_sats_unlocked(
        self, sats: Sequence[TleSat], *, gc_missing: bool = False
    ) -> int:
        seen: Set[str] = set()
        new_index: Dict[str, Set[str]] = {}
        n = 0
        for sat in sats:
            aid = f"sat:{sat.norad}"
            seen.add(aid)
            if not self.store.has_atom(aid):
                self.store.create_atom(aid, S=S_SAT, E=sat.name, T=T_INIT)
            atom = self.store.get_atom(aid)
            if atom is None:
                continue
            # Preserve T on re-ingest; only refresh metadata + E
            atom.E = sat.name
            prev = dict(atom.metadata.get("v") or {})
            atom.metadata["v"] = {
                **prev,
                "norad": sat.norad,
                "name": sat.name,
                "tle1": sat.line1,
                "tle2": sat.line2,
                "inc": sat.inclination_deg,
                "shell": sat.shell_key,
                "kind": "sat",
                "prop": self.prop_mode,
            }
            self.store.import_to_bubble("starlink", aid)
            self.store.import_to_bubble("sats", aid)
            self._ensure_shell_bubble(sat.shell_key)
            self.store.import_to_bubble(sat.shell_key, aid)
            new_index.setdefault(sat.shell_key, set()).add(aid)
            n += 1

        gc = 0
        if gc_missing:
            for a in list(self.iter_sats()):
                aid = str(a.id)
                if aid in seen:
                    continue
                if callable(getattr(self.store, "delete_atom", None)):
                    self.store.delete_atom(aid)
                gc += 1
        self.last_gc_sats = gc
        self._shell_index = new_index
        self._shells = {k: len(v) for k, v in new_index.items()}
        return n

    def ensure_full_grid(self) -> int:
        """Faza 0/1: wszystkie komórki jako atomy."""
        with self._lock:
            nlat = int(math.ceil(180.0 / self.grid_deg))
            nlon = int(math.ceil(360.0 / self.grid_deg))
            created = 0
            for ilat in range(nlat):
                for ilon in range(nlon):
                    if self._upsert_cell(
                        ilat, ilon, count=0, max_count=1, create_empty=True
                    ):
                        created += 1
            return created

    def _upsert_cell(
        self,
        ilat: int,
        ilon: int,
        *,
        count: int,
        max_count: int,
        create_empty: bool,
    ) -> bool:
        """Zwraca True jeśli utworzono nowy atom. Caller holds lock."""
        aid = cell_id(ilat, ilon)
        created = False
        if not self.store.has_atom(aid):
            if count <= 0 and not create_empty:
                return False
            lat0 = -90.0 + ilat * self.grid_deg
            lon0 = -180.0 + ilon * self.grid_deg
            self.store.create_atom(
                aid,
                S=S_CELL,
                E=f"{lat0:.1f},{lon0:.1f}",
                T=density_to_T(count, max_count=max_count),
            )
            created = True
            atom = self.store.get_atom(aid)
            if atom is None:
                return created
            atom.metadata["v"] = {
                "ilat": ilat,
                "ilon": ilon,
                "lat0": lat0,
                "lon0": lon0,
                "deg": self.grid_deg,
                "count": count,
                "kind": "cell",
            }
            self.store.import_to_bubble("starlink", aid)
            self.store.import_to_bubble("grid", aid)
        else:
            atom = self.store.get_atom(aid)
            if atom is None:
                return False
            v = dict(atom.metadata.get("v") or {})
            v["count"] = count
            v.setdefault("ilat", ilat)
            v.setdefault("ilon", ilon)
            atom.metadata["v"] = v
            _set_T(atom, density_to_T(count, max_count=max_count))
        return created

    def propagate_and_bin(
        self,
        sats: Sequence[TleSat],
        *,
        when: Optional[datetime] = None,
        minutes: float = 0.0,
        heat_sats: bool = True,
    ) -> Dict[Tuple[int, int], int]:
        with self._lock:
            return self._propagate_and_bin_unlocked(
                sats, when=when, minutes=minutes, heat_sats=heat_sats
            )

    def _propagate_and_bin_unlocked(
        self,
        sats: Sequence[TleSat],
        *,
        when: Optional[datetime] = None,
        minutes: float = 0.0,
        heat_sats: bool = True,
    ) -> Dict[Tuple[int, int], int]:
        t0 = time.perf_counter()
        counts: Dict[Tuple[int, int], int] = {}
        errors: List[Tuple[int, str]] = []
        when = when or datetime.now(timezone.utc)
        for sat in sats:
            aid = f"sat:{sat.norad}"
            atom = self.store.get_atom(aid)
            if atom is None:
                continue
            try:
                lat, lon, alt = position_of(
                    sat, mode=self.prop_mode, when=when, minutes=minutes
                )
                if (
                    lat is None
                    or lon is None
                    or math.isnan(lat)
                    or math.isnan(lon)
                    or not (-90.0 <= lat <= 90.0)
                ):
                    errors.append((sat.norad, "invalid_lat_lon"))
                    continue
                lon = _wrap_lon(lon)
            except Exception as e:
                errors.append((sat.norad, str(e)[:120]))
                continue
            v = dict(atom.metadata.get("v") or {})
            v.update(
                {
                    "lat": lat,
                    "lon": lon,
                    "alt_km": alt,
                    "t_min": minutes,
                    "prop": self.prop_mode,
                    "when": when.isoformat(),
                }
            )
            atom.metadata["v"] = v
            if heat_sats:
                if hasattr(atom, "heat"):
                    atom.heat(3.0)
                else:
                    atom.touch(0.3)
            ilat, ilon = latlon_to_bin(lat, lon, self.grid_deg)
            counts[(ilat, ilon)] = counts.get((ilat, ilon), 0) + 1
        self.density = counts
        self.last_prop_ms = (time.perf_counter() - t0) * 1000.0
        self.last_error_sats = len(errors)
        self.last_prop_errors = errors
        return counts

    def apply_density(self, counts: Optional[Dict[Tuple[int, int], int]] = None) -> int:
        with self._lock:
            return self._apply_density_unlocked(counts)

    def _apply_density_unlocked(
        self, counts: Optional[Dict[Tuple[int, int], int]] = None
    ) -> int:
        counts = counts if counts is not None else self.density
        max_c = max(counts.values()) if counts else 0
        hot_cells = 0

        if self.hot_only:
            new_keys = set(counts.keys())
            for key in list(self._active_cells - new_keys):
                aid = cell_id(*key)
                atom = self.store.get_atom(aid)
                if atom is not None:
                    if callable(getattr(self.store, "delete_atom", None)):
                        self.store.delete_atom(aid)
                    else:
                        _set_T(atom, float(T_TOMB) * 0.5)
                self._active_cells.discard(key)
            for (ilat, ilon), c in counts.items():
                self._upsert_cell(
                    ilat, ilon, count=c, max_count=max_c, create_empty=False
                )
                self._active_cells.add((ilat, ilon))
                if density_to_T(c, max_count=max_c) >= T_HOT:
                    hot_cells += 1
            return hot_cells

        nlat = int(math.ceil(180.0 / self.grid_deg))
        nlon = int(math.ceil(360.0 / self.grid_deg))
        for ilat in range(nlat):
            for ilon in range(nlon):
                c = counts.get((ilat, ilon), 0)
                self._upsert_cell(
                    ilat, ilon, count=c, max_count=max_c, create_empty=True
                )
                if density_to_T(c, max_count=max_c) >= T_HOT:
                    hot_cells += 1
        self._active_cells = set(counts.keys())
        return hot_cells

    def refresh(
        self,
        sats: Sequence[TleSat],
        *,
        when: Optional[datetime] = None,
        minutes: float = 0.0,
        ensure: bool = True,
    ) -> dict:
        """Update positions + density. ensure=True: upsert sats and GC missing."""
        with self._lock:
            if ensure:
                self._ingest_sats_unlocked(sats, gc_missing=True)
            counts = self._propagate_and_bin_unlocked(
                sats, when=when, minutes=minutes
            )
            hot = self._apply_density_unlocked(counts)
            self.version += 1
            return {
                "bins": len(counts),
                "hot": hot,
                "prop_ms": self.last_prop_ms,
                "errors": self.last_error_sats,
                "gc_sats": self.last_gc_sats,
                "version": self.version,
            }

    def snapshot(self) -> dict:
        """Atomic immutable-ish view for UI / API (audit #1)."""
        with self._lock:
            dens = dict(self.density)
            max_c = max(dens.values()) if dens else 1
            cells_out: List[dict] = []
            for (ilat, ilon), count in dens.items():
                aid = cell_id(ilat, ilon)
                atom = self.store.get_atom(aid)
                if atom is not None:
                    T = float(atom.T)
                else:
                    T = density_to_T(count, max_count=max_c)
                rgb = t_to_rgb(T)
                cells_out.append(
                    {
                        "id": aid,
                        "ilat": ilat,
                        "ilon": ilon,
                        "count": int(count),
                        "T": round(T, 2),
                        "color": f"rgb({rgb[0]},{rgb[1]},{rgb[2]})",
                    }
                )
            return {
                "version": self.version,
                "grid_deg": self.grid_deg,
                "hot_only": self.hot_only,
                "policy": "hot-only" if self.hot_only else "full-grid",
                "density": [
                    {"ilat": ilat, "ilon": ilon, "count": int(c)}
                    for (ilat, ilon), c in dens.items()
                ],
                "cells": cells_out,
                "shells": dict(self._shells),
                "summary": self._summary_unlocked(),
                "prop_errors_sample": list(self.last_prop_errors[:20]),
            }

    def filter_density(
        self,
        *,
        shell: str = "all",
        min_count: int = 1,
    ) -> dict:
        """S4b backend: filter by shell (inclination) and min cell count."""
        with self._lock:
            shell_key = "all"
            if shell and shell not in ("all", "*", ""):
                shell_key = (
                    shell if str(shell).startswith("shell:") else f"shell:{shell}"
                )

            if shell_key == "all":
                dens = {
                    k: int(v)
                    for k, v in self.density.items()
                    if int(v) >= min_count
                }
            else:
                # Re-bin only sats belonging to shell (uses last lat/lon on atoms)
                counts: Dict[Tuple[int, int], int] = {}
                for aid in self._shell_index.get(shell_key, set()):
                    atom = self.store.get_atom(aid)
                    if atom is None:
                        continue
                    v = atom.metadata.get("v") or {}
                    if "lat" not in v or "lon" not in v:
                        continue
                    try:
                        lat = float(v["lat"])
                        lon = float(v["lon"])
                    except (TypeError, ValueError):
                        continue
                    key = latlon_to_bin(lat, lon, self.grid_deg)
                    counts[key] = counts.get(key, 0) + 1
                dens = {k: c for k, c in counts.items() if c >= min_count}

            max_c = max(dens.values()) if dens else 1
            cells = []
            for (ilat, ilon), count in dens.items():
                T = density_to_T(count, max_count=max_c)
                rgb = t_to_rgb(T)
                cells.append(
                    {
                        "id": cell_id(ilat, ilon),
                        "ilat": ilat,
                        "ilon": ilon,
                        "count": count,
                        "T": round(T, 2),
                        "color": f"rgb({rgb[0]},{rgb[1]},{rgb[2]})",
                    }
                )
            return {
                "version": self.version,
                "shell": shell_key,
                "min_count": int(min_count),
                "count_cells": len(cells),
                "count_sats": sum(dens.values()) if dens else 0,
                "cells": cells,
                "density": [
                    {"ilat": k[0], "ilon": k[1], "count": c}
                    for k, c in dens.items()
                ],
            }

    def density_cell_consistency(self) -> dict:
        """Faza 0 check: hot-only density keys vs cell atoms in store."""
        with self._lock:
            dens_keys = set(self.density.keys())
            atom_keys: Set[Tuple[int, int]] = set()
            for a in self.iter_cells():
                v = a.metadata.get("v") or {}
                if "ilat" in v and "ilon" in v:
                    atom_keys.add((int(v["ilat"]), int(v["ilon"])))
                else:
                    # parse cell:ilat:ilon
                    parts = str(a.id).split(":")
                    if len(parts) == 3 and parts[0] == "cell":
                        atom_keys.add((int(parts[1]), int(parts[2])))
            missing_atoms = dens_keys - atom_keys
            ghost_atoms = atom_keys - dens_keys if self.hot_only else set()
            return {
                "density_n": len(dens_keys),
                "cell_atoms_n": len(atom_keys),
                "missing_atoms": len(missing_atoms),
                "ghost_atoms": len(ghost_atoms),
                "ok": len(missing_atoms) == 0
                and (not self.hot_only or len(ghost_atoms) == 0),
            }

    def iter_cells(self):
        for a in self.store.atoms():
            if getattr(a, "S", None) == S_CELL:
                yield a

    def iter_sats(self):
        for a in self.store.atoms():
            if getattr(a, "S", None) == S_SAT:
                yield a

    def summary(self) -> dict:
        with self._lock:
            return self._summary_unlocked()

    def _summary_unlocked(self) -> dict:
        sats = list(self.iter_sats())
        cells = list(self.iter_cells())
        hot_c = sum(1 for a in cells if a.T >= T_HOT)
        warm_c = sum(1 for a in cells if T_WARM <= a.T < T_HOT)
        max_cell = max(cells, key=lambda a: a.T) if cells else None
        st = self.store.stats() if callable(getattr(self.store, "stats", None)) else {}
        err_rate = (
            (self.last_error_sats / len(sats)) if sats else 0.0
        )
        return {
            "sats": len(sats),
            "cells": len(cells),
            "hot_cells": hot_c,
            "warm_cells": warm_c,
            "hot_only": self.hot_only,
            "prop": self.prop_mode,
            "sgp4": _HAS_SGP4,
            "shells": dict(self._shells),
            "state_changes": self.state_changes,
            "prop_ms": self.last_prop_ms,
            "prop_errors": self.last_error_sats,
            "prop_error_rate": round(err_rate, 4),
            "gc_sats": self.last_gc_sats,
            "version": self.version,
            "max_cell": (
                {
                    "id": max_cell.id,
                    "T": round(float(max_cell.T), 2),
                    "E": max_cell.E,
                    "count": (max_cell.metadata.get("v") or {}).get("count"),
                }
                if max_cell
                else None
            ),
            "store": st,
        }


def render_heatmap_png(
    amap: StarlinkAtomMap,
    path: Path,
    *,
    width: int = 720,
    height: int = 360,
) -> Path:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("Pillow wymagany: pip install pillow") from e

    deg = amap.grid_deg
    nlat = int(math.ceil(180.0 / deg))
    nlon = int(math.ceil(360.0 / deg))
    grid = Image.new("RGB", (nlon, nlat), (8, 12, 28))
    px = grid.load()
    # z density array (działa też przy hot-only)
    max_c = max(amap.density.values()) if amap.density else 1
    if amap.density:
        for (ilat, ilon), c in amap.density.items():
            if 0 <= ilat < nlat and 0 <= ilon < nlon:
                y = nlat - 1 - ilat
                px[ilon, y] = t_to_rgb(density_to_T(c, max_count=max_c))
    else:
        for a in amap.iter_cells():
            v = a.metadata.get("v") or {}
            ilat, ilon = int(v.get("ilat", 0)), int(v.get("ilon", 0))
            if 0 <= ilat < nlat and 0 <= ilon < nlon:
                y = nlat - 1 - ilat
                px[ilon, y] = t_to_rgb(float(a.T))
    out = grid.resize((width, height), Image.Resampling.NEAREST)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, format="PNG")
    return path


def export_report_payload(
    amap: StarlinkAtomMap,
    *,
    src: str = "",
    using: int = 0,
    elapsed_s: float = 0.0,
    heatmap_path: Optional[Path] = None,
    top_n: int = 40,
) -> dict:
    """JSON pod stronę HTML / API (bez binarnych blobów poza opcjonalnym b64)."""
    summ = amap.summary()
    deg = amap.grid_deg
    nlat = int(math.ceil(180.0 / deg))
    nlon = int(math.ceil(360.0 / deg))
    dens = [
        {"ilat": ilat, "ilon": ilon, "count": int(c)}
        for (ilat, ilon), c in sorted(amap.density.items(), key=lambda x: -x[1])
    ]
    cells = list(amap.iter_cells())
    cells.sort(key=lambda a: float(a.T), reverse=True)
    top = []
    for a in cells[:top_n]:
        v = a.metadata.get("v") or {}
        top.append(
            {
                "id": str(a.id),
                "T": round(float(a.T), 2),
                "state": str(a.state),
                "E": str(a.E),
                "count": v.get("count"),
                "lat0": v.get("lat0"),
                "lon0": v.get("lon0"),
            }
        )
    heat_b64 = None
    heat_name = None
    if heatmap_path and Path(heatmap_path).is_file():
        heat_name = Path(heatmap_path).name
        heat_b64 = base64.b64encode(Path(heatmap_path).read_bytes()).decode("ascii")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tle_source": src,
        "using": using,
        "elapsed_s": round(elapsed_s, 3),
        "grid_deg": deg,
        "nlat": nlat,
        "nlon": nlon,
        "version": getattr(amap, "version", 0),
        "summary": summ,
        "shells": summ.get("shells") or {},
        "density": dens,
        "top_cells": top,
        "heatmap_file": heat_name,
        "heatmap_png_b64": heat_b64,
        "law": "temperatura mowi KIEDY, osiagalnosc mowi CZY",
        "project": "Cynober Studio · Starlink atoms · bubbles",
    }


def write_html_report(payload: dict, path: Path) -> Path:
    """Samowystarczalna strona HTML (file://) — canvas + przyciski wizualizacji."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # osobny JSON obok HTML (łatwy podgląd / fetch przy serwerze)
    json_path = path.with_suffix(".json")
    slim = dict(payload)
    # w pliku JSON nie dubluj mega b64 jeśli HTML go embeduje — zostaw referencję
    slim_for_file = {k: v for k, v in slim.items() if k != "heatmap_png_b64"}
    if payload.get("heatmap_file"):
        slim_for_file["heatmap_file"] = payload["heatmap_file"]
    json_path.write_text(
        json.dumps(slim_for_file, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    data_js = json.dumps(payload, ensure_ascii=False)
    # escape </script> in JSON
    data_js = data_js.replace("</", "<\\/")

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Karmazyn · Starlink atoms</title>
<style>
  :root {{
    --bg: #0c0a0f;
    --panel: #16121c;
    --ink: #f2e8e8;
    --muted: #9a8a92;
    --crimson: #b01030;
    --hot: #ff3b1f;
    --warm: #f0a030;
    --cold: #3a6a9a;
    --line: #2a2230;
    --ok: #3dba7a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 20% -10%, #2a1020 0%, var(--bg) 55%);
    color: var(--ink); min-height: 100vh;
  }}
  header {{
    padding: 1.1rem 1.4rem; border-bottom: 1px solid var(--line);
    display: flex; flex-wrap: wrap; gap: .8rem; align-items: baseline;
    justify-content: space-between;
  }}
  header h1 {{ margin: 0; font-size: 1.25rem; letter-spacing: .02em; }}
  header h1 span {{ color: var(--crimson); }}
  header .sub {{ color: var(--muted); font-size: .85rem; }}
  main {{
    display: grid;
    grid-template-columns: minmax(260px, 320px) 1fr;
    gap: 1rem; padding: 1rem; max-width: 1400px; margin: 0 auto;
  }}
  @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} }}
  .panel {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; padding: 1rem;
  }}
  .panel h2 {{
    margin: 0 0 .75rem; font-size: .78rem; text-transform: uppercase;
    letter-spacing: .12em; color: var(--muted);
  }}
  .stat {{
    display: flex; justify-content: space-between; padding: .35rem 0;
    border-bottom: 1px solid #221c28; font-size: .92rem;
  }}
  .stat b {{ color: var(--warm); font-variant-numeric: tabular-nums; }}
  .shell-bar {{
    display: grid; grid-template-columns: 72px 1fr 40px; gap: .4rem;
    align-items: center; margin: .35rem 0; font-size: .82rem;
  }}
  .shell-bar .track {{
    height: 8px; background: #221820; border-radius: 4px; overflow: hidden;
  }}
  .shell-bar .fill {{ height: 100%; background: linear-gradient(90deg, var(--crimson), var(--hot)); }}
  .btns {{ display: flex; flex-wrap: wrap; gap: .45rem; margin: .5rem 0 1rem; }}
  button {{
    appearance: none; border: 1px solid var(--line); background: #1e1824;
    color: var(--ink); border-radius: 8px; padding: .45rem .7rem;
    font-size: .82rem; cursor: pointer;
  }}
  button:hover {{ border-color: var(--crimson); }}
  button.active {{
    background: linear-gradient(180deg, #3a1520, #241018);
    border-color: var(--crimson); color: #ffd0d0;
  }}
  label.chk {{ font-size: .82rem; color: var(--muted); display: flex; gap: .35rem; align-items: center; }}
  .viz-wrap {{
    position: relative; background: #08060a; border-radius: 10px;
    border: 1px solid var(--line); overflow: hidden;
  }}
  canvas, .heat-img {{
    display: block; width: 100%; height: auto; image-rendering: pixelated;
  }}
  .heat-img {{ display: none; }}
  .heat-img.show {{ display: block; }}
  canvas.hide {{ display: none; }}
  table {{
    width: 100%; border-collapse: collapse; font-size: .8rem; margin-top: .5rem;
  }}
  th, td {{ text-align: left; padding: .35rem .4rem; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--muted); font-weight: 600; }}
  tr:hover td {{ background: #1c1620; }}
  .pill {{
    display: inline-block; padding: .1rem .4rem; border-radius: 999px;
    font-size: .72rem; background: #2a1820; color: var(--hot);
  }}
  .pill.warm {{ color: var(--warm); background: #2a2418; }}
  footer {{
    max-width: 1400px; margin: 0 auto; padding: 0 1rem 1.5rem;
    color: var(--muted); font-size: .78rem;
  }}
  #status {{ min-height: 1.2em; color: var(--ok); font-size: .82rem; margin-top: .4rem; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>Karmazyn · <span>Starlink</span> atoms</h1>
    <div class="sub">multi-task: Store · bąble · T-heatmap · SGP4 · HTML view</div>
  </div>
  <div class="sub" id="genAt"></div>
</header>
<main>
  <aside class="panel">
    <h2>Wyniki</h2>
    <div id="stats"></div>
    <h2 style="margin-top:1.2rem">Bąble shell</h2>
    <div id="shells"></div>
    <h2 style="margin-top:1.2rem">Wizualizacja</h2>
    <div class="btns" id="modeBtns">
      <button type="button" data-mode="canvas" class="active">Canvas density</button>
      <button type="button" data-mode="png">PNG heatmap</button>
      <button type="button" data-mode="both">Oba</button>
    </div>
    <div class="btns" id="palBtns">
      <button type="button" data-pal="thermal" class="active">Thermal</button>
      <button type="button" data-pal="crimson">Crimson</button>
      <button type="button" data-pal="mono">Mono</button>
    </div>
    <div class="btns">
      <button type="button" id="btnHot">Tylko HOT bins</button>
      <button type="button" id="btnAll">Wszystkie biny</button>
      <button type="button" id="btnGrid">Siatka on/off</button>
      <button type="button" id="btnLabels">Etykiety max</button>
    </div>
    <label class="chk"><input type="range" id="minCount" min="1" max="20" value="1"/> min count: <span id="minCountVal">1</span></label>
    <div id="status"></div>
    <h2 style="margin-top:1.2rem">Top komórki</h2>
    <div style="overflow:auto; max-height: 320px;">
      <table>
        <thead><tr><th>id</th><th>T</th><th>n</th><th>E</th></tr></thead>
        <tbody id="topBody"></tbody>
      </table>
    </div>
  </aside>
  <section class="panel">
    <h2>Mapa</h2>
    <div class="viz-wrap">
      <img id="heatPng" class="heat-img" alt="heatmap PNG"/>
      <canvas id="cv" width="720" height="360"></canvas>
    </div>
    <p class="sub" style="margin:.6rem 0 0">
      Atomy <code>starlink:cell</code> · T = gęstość · bąble <code>shell:*</code> ·
      law: temperature says WHEN, reachability says WHETHER.
    </p>
  </section>
</main>
<footer>
  Dane publiczne TLE (Celestrak). Wygenerowano przez
  <code>software/starlink_atoms.py --html</code>. JSON: <span id="jsonName"></span>
</footer>
<script id="payload" type="application/json">{data_js}</script>
<script>
(function() {{
  const DATA = JSON.parse(document.getElementById('payload').textContent);
  const S = DATA.summary || {{}};
  const cv = document.getElementById('cv');
  const ctx = cv.getContext('2d');
  const img = document.getElementById('heatPng');
  let palette = 'thermal';
  let mode = 'canvas';
  let onlyHot = false;
  let showGrid = false;
  let showLabels = true;
  let minCount = 1;

  document.getElementById('genAt').textContent = (DATA.generated_at || '') +
    (DATA.tle_source ? ' · ' + DATA.tle_source : '');
  document.getElementById('jsonName').textContent = (location.pathname.replace(/\\.html?$/i, '.json').split('/').pop()) || 'starlink_report.json';

  function el(tag, html) {{
    const n = document.createElement(tag);
    if (html != null) n.innerHTML = html;
    return n;
  }}

  function fillStats() {{
    const box = document.getElementById('stats');
    const rows = [
      ['Satelity', S.sats],
      ['Komórki (atomy)', S.cells],
      ['HOT cells', S.hot_cells],
      ['WARM cells', S.warm_cells],
      ['Prop', S.prop + (S.sgp4 ? ' (sgp4 OK)' : '')],
      ['hot_only', S.hot_only ? 'tak' : 'nie'],
      ['prop_ms', (S.prop_ms != null ? S.prop_ms.toFixed(1) : '?')],
      ['using TLE', DATA.using],
      ['grid', DATA.grid_deg + '°'],
      ['elapsed', DATA.elapsed_s + 's'],
    ];
    box.innerHTML = '';
    rows.forEach(([k,v]) => {{
      const d = el('div', '<span>'+k+'</span><b>'+v+'</b>');
      d.className = 'stat';
      box.appendChild(d);
    }});
    if (S.max_cell) {{
      const d = el('div', '<span>max_cell</span><b>'+S.max_cell.id+' · T='+S.max_cell.T+' · n='+S.max_cell.count+'</b>');
      d.className = 'stat';
      box.appendChild(d);
    }}
  }}

  function fillShells() {{
    const shells = DATA.shells || {{}};
    const box = document.getElementById('shells');
    box.innerHTML = '';
    const vals = Object.values(shells);
    const max = Math.max(1, ...vals);
    Object.keys(shells).sort().forEach(k => {{
      const n = shells[k];
      const row = el('div');
      row.className = 'shell-bar';
      row.innerHTML = '<span>'+k.replace('shell:','')+'°</span><div class="track"><div class="fill" style="width:'+(100*n/max)+'%"></div></div><span>'+n+'</span>';
      box.appendChild(row);
    }});
    if (!vals.length) box.textContent = '(brak)';
  }}

  function fillTop() {{
    const tb = document.getElementById('topBody');
    tb.innerHTML = '';
    (DATA.top_cells || []).forEach(c => {{
      const tr = document.createElement('tr');
      const pill = c.T >= 70 ? 'pill' : 'pill warm';
      tr.innerHTML = '<td>'+c.id+'</td><td><span class="'+pill+'">'+c.T+'</span></td><td>'+(c.count??'')+'</td><td>'+c.E+'</td>';
      tb.appendChild(tr);
    }});
  }}

  function colorThermal(t01) {{
    if (t01 < 0.33) {{
      const k = t01/0.33;
      return [0, 40+80*k, 80+175*k];
    }}
    if (t01 < 0.66) {{
      const k = (t01-0.33)/0.33;
      return [255*k, 200+55*k, 255*(1-k)];
    }}
    const k = (t01-0.66)/0.34;
    return [255, 255*(1-k), 0];
  }}
  function colorCrimson(t01) {{
    return [40+200*t01, 8+30*t01, 20+40*(1-t01)];
  }}
  function colorMono(t01) {{
    const v = 20 + 220*t01;
    return [v, v*0.85, v*0.9];
  }}
  function pickColor(t01) {{
    if (palette === 'crimson') return colorCrimson(t01);
    if (palette === 'mono') return colorMono(t01);
    return colorThermal(t01);
  }}

  function maxCount() {{
    let m = 1;
    (DATA.density || []).forEach(d => {{ if (d.count > m) m = d.count; }});
    return m;
  }}

  function densityToT01(count, maxC) {{
    if (count <= 0) return 0;
    return Math.log(1+count) / Math.log(1+maxC);
  }}

  function draw() {{
    const nlat = DATA.nlat || 36, nlon = DATA.nlon || 72;
    const W = cv.width, H = cv.height;
    ctx.fillStyle = '#08060a';
    ctx.fillRect(0,0,W,H);
    const cw = W / nlon, ch = H / nlat;
    const maxC = maxCount();
    const hotThresh = 0.7; // ~ T_HOT scale on log density
    let drawn = 0;
    (DATA.density || []).forEach(d => {{
      if (d.count < minCount) return;
      const t01 = densityToT01(d.count, maxC);
      if (onlyHot && t01 < hotThresh) return;
      const [r,g,b] = pickColor(t01);
      ctx.fillStyle = 'rgb('+r+','+g+','+b+')';
      const x = d.ilon * cw;
      const y = (nlat - 1 - d.ilat) * ch;
      ctx.fillRect(x, y, Math.ceil(cw)+0.5, Math.ceil(ch)+0.5);
      drawn++;
    }});
    if (showGrid) {{
      ctx.strokeStyle = 'rgba(255,255,255,0.08)';
      ctx.lineWidth = 1;
      for (let i=0;i<=nlon;i++) {{
        ctx.beginPath(); ctx.moveTo(i*cw,0); ctx.lineTo(i*cw,H); ctx.stroke();
      }}
      for (let j=0;j<=nlat;j++) {{
        ctx.beginPath(); ctx.moveTo(0,j*ch); ctx.lineTo(W,j*ch); ctx.stroke();
      }}
    }}
    if (showLabels && DATA.top_cells && DATA.top_cells[0]) {{
      const c = DATA.top_cells[0];
      // rough place from E "lat,lon"
      const parts = String(c.E||'').split(',');
      if (parts.length >= 2) {{
        const lat = parseFloat(parts[0]), lon = parseFloat(parts[1]);
        if (!isNaN(lat) && !isNaN(lon)) {{
          const x = ((lon + 180) / 360) * W;
          const y = ((90 - lat) / 180) * H;
          ctx.fillStyle = '#fff';
          ctx.font = '12px sans-serif';
          ctx.fillText('★ '+c.id+' n='+c.count, x+4, y-4);
          ctx.beginPath();
          ctx.arc(x,y,4,0,Math.PI*2);
          ctx.fillStyle = '#ff3b1f';
          ctx.fill();
        }}
      }}
    }}
    document.getElementById('status').textContent =
      'canvas bins=' + drawn + ' · palette=' + palette +
      (onlyHot ? ' · HOT filter' : '') + ' · minCount=' + minCount;
  }}

  function applyMode() {{
    const showCv = mode === 'canvas' || mode === 'both';
    const showPng = mode === 'png' || mode === 'both';
    cv.classList.toggle('hide', !showCv);
    img.classList.toggle('show', showPng && !!img.src);
    if (showCv) draw();
  }}

  // PNG
  if (DATA.heatmap_png_b64) {{
    img.src = 'data:image/png;base64,' + DATA.heatmap_png_b64;
  }} else if (DATA.heatmap_file) {{
    img.src = DATA.heatmap_file;
  }}

  document.getElementById('modeBtns').addEventListener('click', e => {{
    const b = e.target.closest('button[data-mode]');
    if (!b) return;
    mode = b.dataset.mode;
    [...document.getElementById('modeBtns').children].forEach(x => x.classList.toggle('active', x===b));
    applyMode();
  }});
  document.getElementById('palBtns').addEventListener('click', e => {{
    const b = e.target.closest('button[data-pal]');
    if (!b) return;
    palette = b.dataset.pal;
    [...document.getElementById('palBtns').children].forEach(x => x.classList.toggle('active', x===b));
    draw();
  }});
  document.getElementById('btnHot').onclick = () => {{ onlyHot = true; draw(); }};
  document.getElementById('btnAll').onclick = () => {{ onlyHot = false; draw(); }};
  document.getElementById('btnGrid').onclick = () => {{ showGrid = !showGrid; draw(); }};
  document.getElementById('btnLabels').onclick = () => {{ showLabels = !showLabels; draw(); }};
  const rng = document.getElementById('minCount');
  const maxC = maxCount();
  rng.max = Math.max(2, Math.min(50, maxC));
  rng.oninput = () => {{
    minCount = parseInt(rng.value, 10) || 1;
    document.getElementById('minCountVal').textContent = minCount;
    draw();
  }};

  fillStats();
  fillShells();
  fillTop();
  applyMode();
}})();
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def project_starlink_view(
    amap: StarlinkAtomMap,
    guest: Any,
    *,
    copy_sats: bool = False,
    max_cells: Optional[int] = None,
) -> dict:
    """Faza 3: projekcja katalogu → osobny Store gościa (bez heapu Lua na katalogu).

    Katalog (`amap.store`) zostaje czysty. Gość dostaje:
      • starlink:meta  — liczniki katalogu (E parse'owalne w Lua)
      • starlink:cell  — atomy komórek (HOT list / multi-task odczyt)
      • bąble starlink/sats/grid/shell:* (shell = meta count, nie 10k bindów)
      • opcjonalnie saty (copy_sats=True — ciężkie)

    Zwraca dict diagnostyczny (ile skopiowano).
    """
    summ = amap.summary()
    guest.create_bubble("starlink", root=True)
    guest.create_bubble("sats")
    guest.create_bubble("grid")

    shells = summ.get("shells") or {}
    for sk in shells:
        guest.create_bubble(str(sk))

    meta_e = (
        f"sats={summ['sats']};cells={summ['cells']};"
        f"hot={summ['hot_cells']};warm={summ['warm_cells']};"
        f"prop={summ.get('prop')};hot_only={1 if summ.get('hot_only') else 0};"
        f"prop_ms={summ.get('prop_ms', 0):.1f};isolated=1"
    )
    guest.create_atom("starlink:meta", S="starlink:meta", E=meta_e, T=float(T_HOT))
    meta = guest.get_atom("starlink:meta")
    if meta is not None:
        meta.metadata["v"] = {
            "kind": "meta",
            "sats": summ["sats"],
            "cells": summ["cells"],
            "hot_cells": summ["hot_cells"],
            "warm_cells": summ["warm_cells"],
            "shells": dict(shells),
            "prop": summ.get("prop"),
            "hot_only": summ.get("hot_only"),
            "isolated": True,
            "catalog_store": summ.get("store"),
        }
        guest.import_to_bubble("starlink", "starlink:meta")
        guest.import_to_bubble("sats", "starlink:meta")

    # shell meta atoms (count only — nie bind 5k satów)
    for sk, n in shells.items():
        sid = f"shellmeta:{sk}"
        guest.create_atom(sid, S="starlink:shell", E=f"{sk}={n}", T=float(T_WARM))
        sa = guest.get_atom(sid)
        if sa is not None:
            sa.metadata["v"] = {"shell": sk, "count": n, "kind": "shell"}
            guest.import_to_bubble("starlink", sid)
            guest.import_to_bubble(str(sk), sid)

    # cells: sort HOT first, opcjonalny cap
    cells = list(amap.iter_cells())
    cells.sort(key=lambda a: float(a.T), reverse=True)
    if max_cells is not None and max_cells >= 0:
        cells = cells[:max_cells]
    n_cell = 0
    for a in cells:
        aid = str(a.id)
        if guest.has_atom(aid):
            continue
        guest.create_atom(aid, S=S_CELL, E=str(a.E), T=float(a.T))
        ga = guest.get_atom(aid)
        if ga is None:
            continue
        ga.metadata["v"] = dict(a.metadata.get("v") or {})
        if hasattr(ga, "_update_state"):
            ga._update_state()
        else:
            ga.state = state_for_T(ga.T)
        guest.import_to_bubble("starlink", aid)
        guest.import_to_bubble("grid", aid)
        n_cell += 1

    n_sat = 0
    if copy_sats:
        for a in amap.iter_sats():
            aid = str(a.id)
            if guest.has_atom(aid):
                continue
            guest.create_atom(aid, S=S_SAT, E=str(a.E), T=float(a.T))
            ga = guest.get_atom(aid)
            if ga is None:
                continue
            ga.metadata["v"] = dict(a.metadata.get("v") or {})
            guest.import_to_bubble("starlink", aid)
            guest.import_to_bubble("sats", aid)
            shell = (ga.metadata.get("v") or {}).get("shell")
            if shell:
                if not guest.get_bubble(str(shell)):
                    guest.create_bubble(str(shell))
                guest.import_to_bubble(str(shell), aid)
            n_sat += 1

    st = guest.stats() if callable(getattr(guest, "stats", None)) else {}
    return {
        "projected_cells": n_cell,
        "projected_sats": n_sat,
        "meta": True,
        "shells": len(shells),
        "guest_before_lua": st,
    }


def run_lua_tool_name(
    store: Any,
    name: str = "starlink",
    *,
    amap: Optional[StarlinkAtomMap] = None,
    isolated: bool = True,
    copy_sats: bool = False,
    max_cells: Optional[int] = None,
) -> str:
    """Uruchom lua_bin/<name>.lua.

    isolated=True (Faza 3 domyślnie):
      katalog zostaje na `store`/`amap`; Lua montuje **osobny Store** z projekcją
      (meta + cells), więc get_resources() nie miesza heapu gościa z 10k satami.
    isolated=False:
      stary tryb — mount na tym samym Store (debug / shared multi-task).
    """
    # Optional KarmazynOs bridge (Lua tools). Studio runs without it.
    k_os = Path(os.environ.get("KARMAZYN_OS", r"C:\Users\drwis\KarmazynOs"))
    lua_bin = k_os / "lua_bin"
    if not (lua_bin / f"{name}.lua").is_file():
        return (
            f"(brak {name}.lua — opcjonalny most KarmazynOs; "
            f"ustaw KARMAZYN_OS lub pomiń --lua)"
        )
    if not (k_os / "LUA").is_dir():
        return f"(brak LUA w {k_os} — opcjonalny most KarmazynOs)"
    sys.path.insert(0, str(k_os / "LUA"))
    sys.path.insert(0, str(k_os / "software"))
    try:
        from _paths import ensure_kernel_on_path, ensure_lua_package  # type: ignore

        ensure_kernel_on_path(str(k_os / "LUA"))
        ensure_lua_package(str(k_os / "LUA"))
        from karmazyn_host import install_karmazyn_host, run_lua_tool  # type: ignore
        import karmazyn_boot as boot  # type: ignore
    except Exception as e:
        return f"(Lua bridge niedostępny bez KarmazynOs: {e})"

    header_lines: List[str] = []
    tool_store = store
    if isolated:
        if amap is None:
            # zbuduj cienką fasadę na istniejącym store (gdy wywołano bez amap)
            amap = StarlinkAtomMap(store, grid_deg=5.0, hot_only=True, listen=False)
            # nie twórz ponownie bąbli — już są; StarlinkAtomMap.__init__ create_bubble
            # jest idempotentne (reuse)
        guest = open_store(thermal=True, backend="python")
        proj = project_starlink_view(
            amap, guest, copy_sats=copy_sats, max_cells=max_cells
        )
        tool_store = guest
        cat = amap.summary().get("store") or {}
        header_lines.append(
            f"[Faza3 isolate] catalog alive={cat.get('alive', cat.get('total', '?'))} "
            f"bubbles={cat.get('bubbles', '?')}  |  "
            f"view cells={proj['projected_cells']} sats_copied={proj['projected_sats']} "
            f"guest_pre_lua={proj['guest_before_lua'].get('total', '?')}"
        )
    else:
        header_lines.append("[Faza3 shared] Lua na tym samym Store co katalog (stats zmieszane)")

    ev = boot.mount_evaluator(tool_store, kind="lua", lua_bin=str(lua_bin))
    install_karmazyn_host(ev, store=tool_store)
    ret = run_lua_tool(ev, name, lua_bin=str(lua_bin))
    body = ev.format_run_result(ret=ret)
    return "\n".join(header_lines + [body])


def build_map(
    *,
    limit: int = 400,
    grid: float = 5.0,
    hot_only: bool = True,
    prop: str = "auto",
    offline_demo: bool = False,
    cache: str = "out/starlink_tle_cache.txt",
    backend: str = "python",
    minutes: float = 0.0,
    store: Any = None,
) -> Tuple[Any, StarlinkAtomMap, List[TleSat], str]:
    """API do seedowania Store (boot / tool / testy)."""
    if backend and backend != "default":
        os.environ["KARMAZYN_SUBSTRATE"] = backend
    raw, src = load_tle_text(
        offline_demo=offline_demo,
        cache=Path(cache),
        limit_hint=limit or 12,
    )
    catalog = parse_tle_catalog(raw)
    use = catalog if limit == 0 else catalog[:limit]
    if store is None:
        store = open_store(
            thermal=True,
            backend=backend if backend != "default" else None,
        )
    amap = StarlinkAtomMap(
        store, grid_deg=grid, hot_only=hot_only, prop_mode=prop
    )
    amap.ingest_sats(use)
    if not hot_only:
        amap.ensure_full_grid()
    amap.refresh(use, minutes=minutes)
    return store, amap, use, src


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Cynober Studio — Starlink thermal atoms (engine + optional UI)"
    )
    ap.add_argument("--limit", type=int, default=400, help="0 = cały katalog")
    ap.add_argument("--grid", type=float, default=5.0)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--heatmap", type=str, default="out/starlink_heat.png")
    ap.add_argument("--no-heatmap", action="store_true")
    ap.add_argument("--offline-demo", action="store_true")
    ap.add_argument("--cache", type=str, default="out/starlink_tle_cache.txt")
    ap.add_argument("--lua", action="store_true", help=":tool starlink (izolowany Store widoku)")
    ap.add_argument("--lua-hot", action="store_true", help="starlink_hot.lua")
    ap.add_argument(
        "--lua-shared",
        action="store_true",
        help="Lua na tym samym Store co katalog (stary tryb; miesza stats)",
    )
    ap.add_argument(
        "--lua-copy-sats",
        action="store_true",
        help="przy isolate: skopiuj też atomy sat (ciężkie; domyślnie tylko meta+cells)",
    )
    ap.add_argument("--ticks", type=int, default=0)
    ap.add_argument("--backend", choices=("python", "native", "default"), default="python")
    ap.add_argument(
        "--prop",
        choices=("auto", "sgp4", "approx"),
        default="auto",
        help="Faza 1: sgp4 (domyślnie auto)",
    )
    ap.add_argument(
        "--hot-only",
        action="store_true",
        help="Faza 2: tylko atomy komórek z count>0",
    )
    ap.add_argument(
        "--full-grid",
        action="store_true",
        help="wymusza pełną siatkę atomów (Faza 0)",
    )
    ap.add_argument("--live", type=int, default=0, help="liczba odświeżeń live (Faza 1)")
    ap.add_argument("--hz", type=float, default=1.0, help="częstotliwość live refresh")
    ap.add_argument(
        "--html",
        nargs="?",
        const="out/starlink_report.html",
        default=None,
        help="zapisz stronę HTML z wynikami i wizualizacją (domyślnie out/starlink_report.html)",
    )
    ap.add_argument(
        "--open-html",
        action="store_true",
        help="po --html otwórz w domyślnej przeglądarce",
    )
    ap.add_argument(
        "--studio",
        action="store_true",
        help="uruchom Cynober Studio HTTP UI (2D heatmap + API)",
    )
    ap.add_argument("--host", type=str, default="127.0.0.1", help="Studio bind host")
    ap.add_argument("--port", type=int, default=8765, help="Studio HTTP port")
    ap.add_argument(
        "--open-browser",
        action="store_true",
        help="po --studio otwórz przeglądarkę",
    )
    ap.add_argument(
        "--live-feed",
        action="store_true",
        help="Faza 3: cykliczny refresh w tle (wymaga --studio lub działa z --live-feed-cli)",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=900.0,
        help="interwał live-feed w sekundach (domyślnie 900 = 15 min)",
    )
    ap.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=12.0,
        help="TTL cache TLE przy reload (godziny; 0 = zawsze bierz cache jeśli jest)",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.full_grid:
        hot_only = False
    elif args.hot_only:
        hot_only = True
    else:
        # auto: pełny katalog / duże limity → hot-only (Faza 2)
        hot_only = args.limit == 0 or args.limit >= 1000

    t0 = time.perf_counter()
    try:
        store, amap, use, src = build_map(
            limit=args.limit,
            grid=args.grid,
            hot_only=hot_only,
            prop=args.prop,
            offline_demo=args.offline_demo,
            cache=args.cache,
            backend=args.backend,
            minutes=args.minutes,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: --offline-demo", file=sys.stderr)
        return 2

    for _ in range(max(0, args.ticks)):
        store.tick()

    summ = amap.summary()
    dt = time.perf_counter() - t0
    print(
        f"TLE source={src}  using={len(use)}  grid={args.grid}°  "
        f"prop={summ['prop']} sgp4={summ['sgp4']} hot_only={summ['hot_only']}"
    )
    print("---")
    print(
        f"sats={summ['sats']}  cells={summ['cells']}  "
        f"hot_cells={summ['hot_cells']}  warm={summ['warm_cells']}"
    )
    print(f"shells={summ['shells']}")
    print(f"max_cell={summ['max_cell']}")
    print(
        f"prop_ms={summ['prop_ms']:.1f}  prop_errors={summ['prop_errors']}  "
        f"state_changes={summ['state_changes']}"
    )
    print(f"store={summ['store']}")
    print(f"elapsed={dt:.2f}s")

    if args.studio:
        from ui.app import StudioState, run_studio

        state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            limit=int(args.limit or 0),
            offline_demo=bool(args.offline_demo),
            cache=args.cache,
            cache_ttl_hours=float(args.cache_ttl_hours),
        )
        if args.live_feed:
            state.attach_feeder(
                interval_sec=float(args.interval),
                reload_tle=not bool(args.offline_demo),
                refresh_first=False,
            )
            print(
                f"live-feed ON  interval={args.interval}s  "
                f"reload_tle={not args.offline_demo}"
            )
        return run_studio(
            state,
            host=args.host,
            port=args.port,
            open_browser=bool(args.open_browser),
        )

    heat_path: Optional[Path] = None
    if not args.no_heatmap:
        heat_path = render_heatmap_png(amap, Path(args.heatmap))
        print(f"heatmap: {heat_path.resolve()}")

    if args.live > 0:
        period = 1.0 / max(args.hz, 0.05)
        print(f"--- live {args.live}× @ {args.hz} Hz ---")
        for i in range(args.live):
            time.sleep(period)
            info = amap.refresh(use)
            if not args.no_heatmap:
                render_heatmap_png(amap, Path(args.heatmap))
            print(
                f"  [{i+1}/{args.live}] bins={info['bins']} hot={info['hot']} "
                f"prop_ms={info['prop_ms']:.1f} err={info['errors']}"
            )
            if not args.no_heatmap:
                heat_path = Path(args.heatmap)

    if args.html:
        # po live heatmapa może być świeższa
        if heat_path is None and not args.no_heatmap and Path(args.heatmap).is_file():
            heat_path = Path(args.heatmap)
        if heat_path is None and not args.no_heatmap:
            heat_path = render_heatmap_png(amap, Path(args.heatmap))
        payload = export_report_payload(
            amap,
            src=src,
            using=len(use),
            elapsed_s=dt,
            heatmap_path=heat_path,
        )
        html_path = write_html_report(payload, Path(args.html))
        json_side = html_path.with_suffix(".json")
        print(f"html: {html_path.resolve()}")
        print(f"json: {json_side.resolve()}")
        if args.open_html:
            try:
                import webbrowser

                webbrowser.open(html_path.resolve().as_uri())
            except Exception as e:
                print(f"open-html: {e}", file=sys.stderr)

    if args.lua or args.lua_hot:
        tool = "starlink_hot" if args.lua_hot else "starlink"
        isolated = not args.lua_shared
        print(f"--- lua :tool {tool}  isolate={isolated} ---")
        try:
            print(
                run_lua_tool_name(
                    store,
                    tool,
                    amap=amap,
                    isolated=isolated,
                    copy_sats=args.lua_copy_sats,
                )
            )
        except Exception as e:
            print(f"Lua tool error: {e}", file=sys.stderr)
            return 1
        # katalog nienaruszony przez heap Lua
        cat_after = store.stats() if callable(getattr(store, "stats", None)) else {}
        print(
            f"catalog after lua: total={cat_after.get('total')} "
            f"alive={cat_after.get('alive')} bubbles={cat_after.get('bubbles')}"
        )

    print("OK plan: multi-task Store = sats + cells + bubbles + heat + optional Lua")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
