"""StarlinkAtomMap: thermal store multi-task map."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from engine.bootstrap import ensure_paths

ensure_paths()
from karmazyn_kernel import (  # noqa: E402
    T_HOT,
    T_INIT,
    T_TOMB,
    T_WARM,
)

from engine.constants import HAS_SGP4, S_CELL, S_SAT
from engine.grid import _set_T, cell_id, density_to_T, latlon_to_bin, t_to_rgb
from engine.prop import _wrap_lon, position_of, resolve_prop_mode
from engine.tle import TleSat

# alias for summary
_HAS_SGP4 = HAS_SGP4

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
        self._fleet_index: Dict[str, Set[str]] = {}
        self._reach_session: Any = None
        self._active_cells: Set[Tuple[int, int]] = set()
        self.density: Dict[Tuple[int, int], int] = {}
        self.cell_to_sats: Dict[Tuple[int, int], Set[str]] = {}
        self.sat_to_cell: Dict[str, Tuple[int, int]] = {}
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

    def _ensure_fleet_bubble(self, key: str) -> None:
        if key not in self._fleet_index:
            self.store.create_bubble(key)
            self._fleet_index[key] = set()

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
        new_fleet: Dict[str, Set[str]] = {}
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
            fleet_name = getattr(sat, "fleet", None) or "starlink"
            atom.metadata["v"] = {
                **prev,
                "norad": sat.norad,
                "name": sat.name,
                "tle1": sat.line1,
                "tle2": sat.line2,
                "inc": sat.inclination_deg,
                "shell": sat.shell_key,
                "fleet": fleet_name,
                "country": getattr(sat, "country", None),
                "kind": "sat",
                "prop": self.prop_mode,
            }
            self.store.import_to_bubble("starlink", aid)
            self.store.import_to_bubble("sats", aid)
            self._ensure_shell_bubble(sat.shell_key)
            self.store.import_to_bubble(sat.shell_key, aid)
            new_index.setdefault(sat.shell_key, set()).add(aid)
            fkey = (
                fleet_name
                if str(fleet_name).startswith("fleet:")
                else f"fleet:{fleet_name}"
            )
            self._ensure_fleet_bubble(fkey)
            self.store.import_to_bubble(fkey, aid)
            new_fleet.setdefault(fkey, set()).add(aid)
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
        self._fleet_index = new_fleet
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
        cell_to_sats: Dict[Tuple[int, int], Set[str]] = {}
        sat_to_cell: Dict[str, Tuple[int, int]] = {}
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
            key = (ilat, ilon)
            counts[key] = counts.get(key, 0) + 1
            cell_to_sats.setdefault(key, set()).add(aid)
            sat_to_cell[aid] = key
        self.density = counts
        self.cell_to_sats = cell_to_sats
        self.sat_to_cell = sat_to_cell
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
            if getattr(self, "_reach_session", None) is not None:
                from engine.reach_studio import rebind_session

                rebind_session(self, bump_version=False)
            from engine.reach_studio import write_depends_on

            write_depends_on(self)
            self.version += 1
            return {
                "bins": len(counts),
                "hot": hot,
                "prop_ms": self.last_prop_ms,
                "errors": self.last_error_sats,
                "gc_sats": self.last_gc_sats,
                "version": self.version,
            }

    def snapshot(
        self,
        *,
        reach_only: bool = False,
        reach_ids: Optional[Set[str]] = None,
    ) -> dict:
        """Atomic immutable-ish view for UI / API (audit #1).

        Default (reach_only=False) is the density SoT contract.
        reach_only filters cells to the session closure — a view, not a rewrite.
        """
        with self._lock:
            dens = dict(self.density)
            extra: Dict[str, Any] = {}
            if reach_only:
                from engine.reach_studio import filter_density_keys, session_reach

                ids = reach_ids if reach_ids is not None else session_reach(self)
                dens = filter_density_keys(self, dens, ids)
                extra["reach_view"] = True
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
            out = {
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
            out.update(extra)
            return out

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

    def rebuild_bin_index(self) -> None:
        """Rebuild cell↔sat index from last lat/lon on sat atoms (no SGP4)."""
        cell_to_sats: Dict[Tuple[int, int], Set[str]] = {}
        sat_to_cell: Dict[str, Tuple[int, int]] = {}
        for atom in self.iter_sats():
            v = dict(getattr(atom, "metadata", None) or {})
            meta = dict(v.get("v") or v)
            if "lat" not in meta or "lon" not in meta:
                continue
            try:
                lat = float(meta["lat"])
                lon = float(meta["lon"])
            except (TypeError, ValueError):
                continue
            key = latlon_to_bin(lat, lon, self.grid_deg)
            aid = str(atom.id)
            cell_to_sats.setdefault(key, set()).add(aid)
            sat_to_cell[aid] = key
        self.cell_to_sats = cell_to_sats
        self.sat_to_cell = sat_to_cell
        try:
            from engine.reach_studio import write_depends_on
        except ImportError:
            return
        write_depends_on(self)

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
        n_sats = 0
        n_cells = 0
        hot_c = 0
        warm_c = 0
        max_cell = None
        fleets: Dict[str, int] = {}
        countries: Dict[str, int] = {}
        for a in self.store.atoms():
            kind = getattr(a, "S", None)
            if kind == S_SAT:
                n_sats += 1
                v = dict(a.metadata.get("v") or {})
                fk = str(v.get("fleet") or "starlink")
                fleets[fk] = fleets.get(fk, 0) + 1
                ck = str(v.get("country") or "?").upper()
                countries[ck] = countries.get(ck, 0) + 1
            elif kind == S_CELL:
                n_cells += 1
                t = float(a.T)
                if t >= T_HOT:
                    hot_c += 1
                elif T_WARM <= t < T_HOT:
                    warm_c += 1
                if max_cell is None or t > float(max_cell.T):
                    max_cell = a
        st = self.store.stats() if callable(getattr(self.store, "stats", None)) else {}
        err_rate = (self.last_error_sats / n_sats) if n_sats else 0.0
        return {
            "sats": n_sats,
            "cells": n_cells,
            "hot_cells": hot_c,
            "warm_cells": warm_c,
            "hot_only": self.hot_only,
            "prop": self.prop_mode,
            "sgp4": _HAS_SGP4,
            "shells": dict(self._shells),
            "fleets": fleets,
            "countries": countries,
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
