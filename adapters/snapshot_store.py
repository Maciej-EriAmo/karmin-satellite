#!/usr/bin/env python3
"""
Local snapshot store for Cynober Studio (S1b MVP).

Standalone file store under ``out/snapshots/`` (or custom dir) — no live
Cynober server required. Optional remote Cynober bridge can wrap the same
payload later (env CYNOBER_*).

Payload = export-friendly view: density + shells + summary + optional sat TLE.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_dir() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "out" / "snapshots"


@dataclass
class SnapshotMeta:
    snapshot_id: str
    created_at: str
    path: Path
    sats_count: int = 0
    cells_count: int = 0
    src: str = ""
    version: int = 0

    def as_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "path": str(self.path),
            "sats_count": self.sats_count,
            "cells_count": self.cells_count,
            "src": self.src,
            "version": self.version,
        }


class SnapshotStore:
    """JSON files: one snapshot per ``{id}.json``."""

    def __init__(self, root: Optional[Path] = None, *, retention_days: int = 7):
        self.root = Path(root) if root else _default_dir()
        self.retention_days = int(retention_days)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, snapshot_id: str) -> Path:
        if not _SAFE_ID.match(snapshot_id):
            raise ValueError(f"invalid snapshot_id: {snapshot_id!r}")
        return self.root / f"{snapshot_id}.json"

    def make_id(self, prefix: str = "snap") -> str:
        ts = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        return f"{prefix}_{ts}_{int(time.time() * 1000) % 100000:05d}"

    def build_payload(
        self,
        amap: Any,
        *,
        src: str = "",
        using: int = 0,
        include_sats: bool = True,
        max_sats: int = 50_000,
        solar: Optional[dict] = None,
        extra: Optional[dict] = None,
    ) -> dict:
        """Serialize map view for disk (density = SoT).

        Optional ``solar`` = H4 weather/hazard/predict meta (research proxy).
        Optional ``extra`` merged at top level (non-conflicting keys only).
        """
        dens = [
            {"ilat": int(k[0]), "ilon": int(k[1]), "count": int(v)}
            for k, v in sorted(
                (amap.density or {}).items(), key=lambda x: -int(x[1])
            )
        ]
        shells = dict(getattr(amap, "_shells", {}) or {})
        summary = amap.summary() if callable(getattr(amap, "summary", None)) else {}
        sats_out: List[dict] = []
        if include_sats and hasattr(amap, "iter_sats"):
            for i, a in enumerate(amap.iter_sats()):
                if i >= max_sats:
                    break
                v = dict(a.metadata.get("v") or {})
                sats_out.append(
                    {
                        "id": str(a.id),
                        "norad": v.get("norad"),
                        "name": v.get("name") or str(a.E),
                        "tle1": v.get("tle1"),
                        "tle2": v.get("tle2"),
                        "inc": v.get("inc"),
                        "shell": v.get("shell"),
                        "lat": v.get("lat"),
                        "lon": v.get("lon"),
                        "alt_km": v.get("alt_km"),
                        "T": float(a.T),
                    }
                )
        raw_for_hash = json.dumps(
            {"density": dens, "shells": shells}, sort_keys=True
        ).encode("utf-8")
        payload: Dict[str, Any] = {
            "format": "cynober-studio-snapshot-v1",
            "created_at": _utc_now().isoformat(),
            "src": src,
            "using": using or len(sats_out),
            "grid_deg": float(getattr(amap, "grid_deg", 5.0)),
            "hot_only": bool(getattr(amap, "hot_only", True)),
            "prop": summary.get("prop"),
            "version": int(getattr(amap, "version", 0) or 0),
            "shells": shells,
            "summary": summary,
            "density": dens,
            "sats": sats_out,
            "catalog_hash": hashlib.sha256(raw_for_hash).hexdigest()[:16],
        }
        if solar:
            payload["solar"] = dict(solar)
        if extra:
            reserved = set(payload.keys()) | {"snapshot_id", "solar"}
            for k, v in dict(extra).items():
                if k not in reserved:
                    payload[k] = v
        return payload

    def save(
        self,
        amap: Any,
        *,
        snapshot_id: Optional[str] = None,
        src: str = "",
        using: int = 0,
        include_sats: bool = True,
        prune: bool = True,
        solar: Optional[dict] = None,
        extra: Optional[dict] = None,
        attach_solar: bool = False,
        solar_offline: bool = False,
        solar_with_predict: bool = True,
    ) -> SnapshotMeta:
        """
        Write snapshot JSON.

        H4: pass ``solar=`` meta dict, or ``attach_solar=True`` to collect
        weather/hazard/predict from ``engine.solar`` at save time.
        """
        sid = snapshot_id or self.make_id()
        solar_block = solar
        if solar_block is None and attach_solar:
            try:
                from engine.solar import collect_solar_for_map

                report = collect_solar_for_map(
                    amap,
                    offline=bool(solar_offline),
                    with_predict=bool(solar_with_predict),
                    src=src,
                )
                solar_block = report.solar_meta()
            except Exception:
                solar_block = None
        payload = self.build_payload(
            amap,
            src=src,
            using=using,
            include_sats=include_sats,
            solar=solar_block,
            extra=extra,
        )
        payload["snapshot_id"] = sid
        path = self._path(sid)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if prune:
            self.prune()
        return SnapshotMeta(
            snapshot_id=sid,
            created_at=payload["created_at"],
            path=path,
            sats_count=len(payload.get("sats") or []),
            cells_count=len(payload.get("density") or []),
            src=src,
            version=int(payload.get("version") or 0),
        )

    def load_raw(self, snapshot_id: str) -> dict:
        path = self._path(snapshot_id)
        if not path.is_file():
            raise FileNotFoundError(f"snapshot not found: {snapshot_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> List[SnapshotMeta]:
        out: List[SnapshotMeta] = []
        for p in sorted(self.root.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            dens = data.get("density") or []
            sats = data.get("sats") or []
            out.append(
                SnapshotMeta(
                    snapshot_id=str(data.get("snapshot_id") or p.stem),
                    created_at=str(data.get("created_at") or ""),
                    path=p,
                    sats_count=len(sats),
                    cells_count=len(dens),
                    src=str(data.get("src") or ""),
                    version=int(data.get("version") or 0),
                )
            )
        return out

    def prune(self, *, retention_days: Optional[int] = None) -> int:
        days = self.retention_days if retention_days is None else int(retention_days)
        if days <= 0:
            return 0
        cutoff = _utc_now() - timedelta(days=days)
        removed = 0
        for p in self.root.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                created = data.get("created_at") or ""
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                # fall back to mtime
                dt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if dt < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        return removed

    def delete(self, snapshot_id: str) -> bool:
        path = self._path(snapshot_id)
        if path.is_file():
            path.unlink()
            return True
        return False


def load_snapshot_into_map(
    payload: dict,
    *,
    store: Any = None,
    backend: str = "python",
) -> Tuple[Any, Any, List[Any], str]:
    """
    Rebuild Store + StarlinkAtomMap from snapshot.

    Returns (store, amap, tle_sats, src) — tle_sats may be empty if snapshot
    had no TLE lines (density-only restore still works).
    """
    from engine.bootstrap import ensure_paths

    ensure_paths()
    from karmazyn_kernel import open_store

    from engine.grid import cell_id, density_to_T
    from engine.map import StarlinkAtomMap
    from engine.tle import TleSat

    if store is None:
        store = open_store(thermal=True, backend=backend)
    grid = float(payload.get("grid_deg") or 5.0)
    hot_only = bool(payload.get("hot_only", True))
    amap = StarlinkAtomMap(
        store,
        grid_deg=grid,
        hot_only=hot_only,
        prop_mode=str(payload.get("prop") or "auto"),
        listen=False,
    )

    # Rebuild sat atoms from snapshot TLE when present
    tle_sats: List[TleSat] = []
    for s in payload.get("sats") or []:
        tle1, tle2 = s.get("tle1"), s.get("tle2")
        norad = s.get("norad")
        if not tle1 or not tle2 or norad is None:
            continue
        try:
            sat = TleSat(
                name=str(s.get("name") or f"SAT-{norad}"),
                line1=str(tle1),
                line2=str(tle2),
                norad=int(norad),
                inclination_deg=float(s.get("inc") or 0.0),
                raan_deg=0.0,
                mean_anomaly_deg=0.0,
                mean_motion_rev_per_day=15.0,
                ecc=0.0,
            )
        except Exception:
            continue
        tle_sats.append(sat)
    if tle_sats:
        amap.ingest_sats(tle_sats, gc_missing=False)
        # restore positions on atoms if present
        for s in payload.get("sats") or []:
            aid = s.get("id") or (f"sat:{s.get('norad')}" if s.get("norad") else None)
            if not aid:
                continue
            atom = store.get_atom(str(aid))
            if atom is None:
                continue
            v = dict(atom.metadata.get("v") or {})
            for k in ("lat", "lon", "alt_km", "shell", "inc", "name"):
                if s.get(k) is not None:
                    v[k] = s[k]
            atom.metadata["v"] = v

    dens_list = payload.get("density") or []
    counts: Dict[Tuple[int, int], int] = {}
    for d in dens_list:
        try:
            key = (int(d["ilat"]), int(d["ilon"]))
            counts[key] = int(d["count"])
        except (KeyError, TypeError, ValueError):
            continue
    amap.density = counts
    amap._apply_density_unlocked(counts)
    amap.version = int(payload.get("version") or 0) + 0
    # mark as loaded
    if amap.version == 0:
        amap.version = 1
    src = str(payload.get("src") or f"snapshot:{payload.get('snapshot_id')}")
    try:
        from engine.reach_studio import attach_session, reach_enabled

        if reach_enabled() and tle_sats:
            attach_session(amap)
    except Exception as e:
        import logging

        logging.getLogger("cynober.studio").warning(
            "snapshot load: session attach skipped: %s", e
        )
    return store, amap, tle_sats, src
