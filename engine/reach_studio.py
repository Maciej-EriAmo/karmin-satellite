"""Reach Studio — session root + reach view (KarmazynOs law, beside density).

Temperature says when; reachability says whether.
Density remains SoT. This module is a view + explicit session bubble.

Does not change Store.tick() semantics. Walks from the session bubble only
(not store._reachable(), which unions every store root including 'starlink').
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from engine.grid import cell_id, latlon_to_bin

REACH_MODES = ("off", "session", "ghost", "impact")
DEFAULT_SESSION_ID = "session:default"
ENV_REACH = "CYNOBER_REACH"
ENV_REACH_MODE = "CYNOBER_REACH_MODE"


# ── flags ───────────────────────────────────────────────────────────────────


def _env_truthy(name: str, default: str = "1") -> bool:
    v = os.environ.get(name, default)
    if v is None:
        return default not in ("0", "false", "off", "no", "")
    return str(v).strip().lower() not in ("0", "false", "off", "no", "")


def reach_flag() -> bool:
    """CYNOBER_REACH — default 1 (dev)."""
    return _env_truthy(ENV_REACH, "1")


def reach_mode_from_env() -> str:
    raw = (os.environ.get(ENV_REACH_MODE) or "session").strip().lower()
    if raw not in REACH_MODES:
        return "session"
    return raw


def effective_reach_mode(state: Any = None) -> str:
    """Resolve mode: StudioState.reach_mode → env → session. Flag 0 forces off."""
    if not reach_flag():
        return "off"
    override = ""
    if state is not None:
        override = str(getattr(state, "reach_mode", "") or "").strip().lower()
    mode = override or reach_mode_from_env()
    if mode not in REACH_MODES:
        mode = "session"
    return mode


def reach_enabled(state: Any = None) -> bool:
    return effective_reach_mode(state) != "off"


# ── atom / bubble IDs ───────────────────────────────────────────────────────


def sat_atom_id(norad: Any) -> str:
    return f"sat:{norad}"


def cell_atom_id(ilat: int, ilon: int) -> str:
    return cell_id(int(ilat), int(ilon))


def shell_bubble_id(key: Any) -> str:
    k = str(key or "").strip()
    if not k or k in ("all", "*", "shell:all"):
        return "all"
    return k if k.startswith("shell:") else f"shell:{k}"


def fleet_bubble_id(key: Any) -> str:
    k = str(key or "starlink").strip() or "starlink"
    if k.startswith("fleet:"):
        return k
    return f"fleet:{k}"


def session_bubble_id(key: Any = None) -> str:
    k = str(key or "default").strip() or "default"
    if k.startswith("session:"):
        return k
    return f"session:{k}"


def parse_cell_id(aid: str) -> Optional[Tuple[int, int]]:
    parts = str(aid).split(":")
    if len(parts) != 3 or parts[0] != "cell":
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


# ── scope ───────────────────────────────────────────────────────────────────


@dataclass
class SessionScope:
    session_id: str = DEFAULT_SESSION_ID
    shell: str = "all"
    fleet: str = ""
    country: str = ""
    min_count: int = 1

    def as_dict(self) -> dict:
        return {
            "session": self.session_id,
            "shell": self.shell,
            "fleet": self.fleet or "",
            "country": self.country or "",
            "min_count": int(self.min_count),
        }


def get_scope(amap: Any) -> SessionScope:
    sc = getattr(amap, "_reach_session", None)
    if isinstance(sc, SessionScope):
        return sc
    return SessionScope()


# ── walk (session-only; same shape as Store._walk_bubbles) ──────────────────


def walk_from_bubbles(store: Any, starts: Sequence[Any]) -> Set[str]:
    """BFS/DFS from given bubbles. Does not include store-wide extra_reach."""
    reach: Set[str] = set()
    if not starts:
        return reach
    seen: Set[int] = set()
    stack: List[Any] = [b for b in starts if b is not None]
    env_of = getattr(store, "_env_of", None)
    push_envs = getattr(store, "_push_envs", None)
    while stack:
        b = stack.pop()
        bid = id(b)
        if bid in seen:
            continue
        seen.add(bid)
        bindings = getattr(b, "bindings", None) or {}
        for _name, aid in list(bindings.items()):
            atom = store.get_atom(aid)
            if atom is None:
                continue
            reach.add(str(aid))
            if env_of is None:
                continue
            try:
                meta = getattr(atom, "metadata", None) or {}
                env = env_of(meta.get("v"))
            except Exception:
                continue
            if push_envs is not None:
                push_envs(env, stack)
            elif env is not None and hasattr(env, "bindings"):
                stack.append(env)
        parent = getattr(b, "parent", None)
        if parent is not None:
            stack.append(parent)
    return reach


def bind_atom(store: Any, bubble: Any, atom_id: str) -> bool:
    """Bind by atom id (unique). Avoids E-name collisions in import_to_bubble."""
    atom = store.get_atom(atom_id)
    if bubble is None or atom is None:
        return False
    bubble.bind(str(atom_id), atom)
    return True


# ── session lifecycle ───────────────────────────────────────────────────────


def ensure_session(amap: Any, session_id: str = DEFAULT_SESSION_ID) -> Any:
    """Create session bubble as an extra store root. Catalog roots stay."""
    store = amap.store
    sid = session_bubble_id(session_id)
    store.create_bubble(sid, root=True)
    return store.get_bubble(sid)


def _sat_matches(
    atom: Any,
    *,
    shell_key: str,
    fleet_key: str,
    country_key: str,
) -> bool:
    v = dict(getattr(atom, "metadata", None) or {})
    meta = dict(v.get("v") or v)
    if shell_key != "all":
        sk = str(meta.get("shell") or "")
        if not sk.startswith("shell:"):
            sk = f"shell:{sk}" if sk else ""
        if sk != shell_key:
            return False
    if fleet_key:
        fk = str(meta.get("fleet") or "").strip().lower()
        wanted = fleet_key.replace("fleet:", "").lower()
        have = fk.replace("fleet:", "")
        if have != wanted:
            return False
    if country_key:
        ck = str(meta.get("country") or "").strip().upper()
        if ck != country_key:
            return False
    return True


def _cell_of_sat(amap: Any, atom: Any) -> Optional[Tuple[int, int]]:
    v = dict(getattr(atom, "metadata", None) or {})
    meta = dict(v.get("v") or v)
    if "lat" not in meta or "lon" not in meta:
        return None
    try:
        lat = float(meta["lat"])
        lon = float(meta["lon"])
    except (TypeError, ValueError):
        return None
    return latlon_to_bin(lat, lon, amap.grid_deg)


def _select_sats(
    amap: Any,
    *,
    shell_key: str,
    fleet_key: str,
    country_key: str,
    min_count: int,
) -> List[Any]:
    selected: List[Any] = []
    for atom in amap.iter_sats():
        if _sat_matches(
            atom, shell_key=shell_key, fleet_key=fleet_key, country_key=country_key
        ):
            selected.append(atom)
    if int(min_count) <= 1:
        return selected
    counts: Dict[Tuple[int, int], int] = {}
    sat_cell: Dict[str, Tuple[int, int]] = {}
    for atom in selected:
        key = _cell_of_sat(amap, atom)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        sat_cell[str(atom.id)] = key
    return [
        a
        for a in selected
        if counts.get(sat_cell.get(str(a.id)), 0) >= int(min_count)
    ]


def set_session_scope(
    amap: Any,
    *,
    shell: str = "all",
    fleet: str = "",
    country: str = "",
    min_count: int = 1,
    session_id: str = DEFAULT_SESSION_ID,
    bump_version: bool = True,
) -> dict:
    """Rebuild session bubble bindings. Does not delete the catalog."""
    lock = getattr(amap, "_lock", None)
    if lock is not None:
        lock.acquire()
    try:
        return _set_session_scope_unlocked(
            amap,
            shell=shell,
            fleet=fleet,
            country=country,
            min_count=min_count,
            session_id=session_id,
            bump_version=bump_version,
        )
    finally:
        if lock is not None:
            lock.release()


def _set_session_scope_unlocked(
    amap: Any,
    *,
    shell: str,
    fleet: str,
    country: str,
    min_count: int,
    session_id: str,
    bump_version: bool,
) -> dict:
    store = amap.store
    sid = session_bubble_id(session_id)
    bubble = ensure_session(amap, sid)
    shell_key = shell_bubble_id(shell)
    fleet_raw = str(fleet or "").strip()
    # "all" / empty = no fleet constraint (already-loaded catalog)
    if fleet_raw.lower() in ("", "all", "*", "fleet:all"):
        fleet_key = ""
    else:
        fleet_key = fleet_bubble_id(fleet_raw)
    country_key = str(country or "").strip().upper()
    try:
        min_c = max(1, int(min_count))
    except (TypeError, ValueError):
        min_c = 1

    selected = _select_sats(
        amap,
        shell_key=shell_key,
        fleet_key=fleet_key,
        country_key=country_key,
        min_count=min_c,
    )

    # rebuild bindings by atom id
    if bubble is not None:
        store_lock = getattr(store, "lock", None)
        if store_lock is not None:
            with store_lock:
                bubble.bindings.clear()
        else:
            bubble.bindings.clear()
        for atom in selected:
            bind_atom(store, bubble, str(atom.id))
            key = _cell_of_sat(amap, atom)
            if key is None:
                continue
            cid = cell_atom_id(*key)
            if store.has_atom(cid):
                bind_atom(store, bubble, cid)

    scope = SessionScope(
        session_id=sid,
        shell=shell_key,
        fleet=fleet_raw,
        country=country_key,
        min_count=min_c,
    )
    amap._reach_session = scope
    if bump_version:
        amap.version = int(getattr(amap, "version", 0) or 0) + 1

    reach = walk_from_bubbles(store, [bubble] if bubble is not None else [])
    n_sats, n_cells = _count_reach(reach)
    return {
        "session": sid,
        "scope": scope.as_dict(),
        "n_reach": len(reach),
        "n_sats": n_sats,
        "n_cells": n_cells,
        "version": int(getattr(amap, "version", 0) or 0),
    }


def rebind_session(amap: Any, *, bump_version: bool = False) -> dict:
    """Re-apply stored scope (after refresh / bin change)."""
    sc = get_scope(amap)
    return _set_session_scope_unlocked(
        amap,
        shell=sc.shell,
        fleet=sc.fleet,
        country=sc.country,
        min_count=sc.min_count,
        session_id=sc.session_id,
        bump_version=bump_version,
    )


def attach_session(
    amap: Any,
    *,
    session_id: str = DEFAULT_SESSION_ID,
    shell: str = "all",
    fleet: str = "",
    country: str = "",
    min_count: int = 1,
) -> dict:
    """Boot hook: create session root and bind current catalog. No version bump."""
    if not reach_enabled():
        return {"enabled": False, "mode": "off"}
    info = set_session_scope(
        amap,
        shell=shell,
        fleet=fleet,
        country=country,
        min_count=min_count,
        session_id=session_id,
        bump_version=False,
    )
    info["enabled"] = True
    info["mode"] = effective_reach_mode()
    return info


def session_reach(amap: Any) -> Set[str]:
    """Atom ids reachable from the session bubble only."""
    sc = get_scope(amap)
    store = amap.store
    bubble = store.get_bubble(session_bubble_id(sc.session_id))
    return walk_from_bubbles(store, [bubble] if bubble is not None else [])


def _count_reach(reach: Iterable[str]) -> Tuple[int, int]:
    n_sats = 0
    n_cells = 0
    for aid in reach:
        s = str(aid)
        if s.startswith("sat:"):
            n_sats += 1
        elif s.startswith("cell:"):
            n_cells += 1
    return n_sats, n_cells


def cells_in_reach(amap: Any, reach_ids: Optional[Set[str]] = None) -> Set[Tuple[int, int]]:
    ids = reach_ids if reach_ids is not None else session_reach(amap)
    cells: Set[Tuple[int, int]] = set()
    store = amap.store
    for aid in ids:
        parsed = parse_cell_id(str(aid))
        if parsed is not None:
            cells.add(parsed)
            continue
        if not str(aid).startswith("sat:"):
            continue
        atom = store.get_atom(aid)
        if atom is None:
            continue
        key = _cell_of_sat(amap, atom)
        if key is not None:
            cells.add(key)
    return cells


def filter_density_keys(
    amap: Any,
    dens: Dict[Tuple[int, int], int],
    reach_ids: Optional[Set[str]] = None,
) -> Dict[Tuple[int, int], int]:
    allowed = cells_in_reach(amap, reach_ids)
    return {k: v for k, v in dens.items() if k in allowed}


def reach_status(amap: Any, *, state: Any = None) -> dict:
    mode = effective_reach_mode(state)
    if mode == "off":
        return {
            "enabled": False,
            "mode": "off",
            "session": DEFAULT_SESSION_ID,
            "scope": SessionScope().as_dict(),
            "n_reach": 0,
            "n_sats": 0,
            "n_cells": 0,
        }
    sc = get_scope(amap)
    ids = session_reach(amap)
    n_sats, n_cells = _count_reach(ids)
    return {
        "enabled": True,
        "mode": mode,
        "session": sc.session_id,
        "scope": sc.as_dict(),
        "n_reach": len(ids),
        "n_sats": n_sats,
        "n_cells": n_cells,
        "version": int(getattr(amap, "version", 0) or 0),
    }


# ── W2 ghost (retained TOMB ∩ session reach) ────────────────────────────────


def _thermal_thresholds() -> Tuple[float, float]:
    from engine.bootstrap import ensure_paths

    ensure_paths()
    from karmazyn_kernel import T_TOMB, T_WARM

    return float(T_TOMB), float(T_WARM)


def _retained_ids(store: Any) -> Set[str]:
    raw = getattr(store, "_retained_tomb", None)
    if not raw:
        return set()
    return {str(x) for x in raw}


def collect_ghost(amap: Any, *, state: Any = None, sample: int = 16) -> dict:
    """Ghost layer: retained/cold atoms in session reach. Density SoT untouched."""
    mode = effective_reach_mode(state)
    empty = {
        "enabled": False,
        "mode": mode,
        "n_cells": 0,
        "n_sats": 0,
        "n_retained": 0,
        "n_cold": 0,
        "cells": [],
        "sats_sample": [],
    }
    if mode == "off":
        return empty
    t_tomb, t_warm = _thermal_thresholds()
    store = amap.store
    reach = session_reach(amap)
    retained = _retained_ids(store)
    cell_map: Dict[Tuple[int, int], dict] = {}
    sat_ids: List[str] = []

    def _put_cell(key: Tuple[int, int], *, kind: str, T: float, aid: str) -> None:
        prev = cell_map.get(key)
        if prev is not None and prev.get("kind") == "retained" and kind != "retained":
            return
        cell_map[key] = {
            "ilat": int(key[0]),
            "ilon": int(key[1]),
            "kind": kind,
            "T": round(float(T), 2),
            "id": aid,
        }

    for aid in retained:
        if aid not in reach:
            continue
        atom = store.get_atom(aid)
        if atom is None:
            continue
        T = float(getattr(atom, "T", 0.0) or 0.0)
        if str(aid).startswith("sat:"):
            sat_ids.append(str(aid))
            key = _cell_of_sat(amap, atom)
            if key is not None:
                _put_cell(key, kind="retained", T=T, aid=str(aid))
        else:
            parsed = parse_cell_id(str(aid))
            if parsed is not None:
                _put_cell(parsed, kind="retained", T=T, aid=str(aid))

    for aid in reach:
        if aid in retained:
            continue
        atom = store.get_atom(aid)
        if atom is None:
            continue
        T = float(getattr(atom, "T", 0.0) or 0.0)
        if not (t_tomb <= T < t_warm):
            continue
        if str(aid).startswith("sat:"):
            key = _cell_of_sat(amap, atom)
            if key is not None:
                _put_cell(key, kind="cold", T=T, aid=str(aid))
        else:
            parsed = parse_cell_id(str(aid))
            if parsed is not None:
                _put_cell(parsed, kind="cold", T=T, aid=str(aid))

    cells = list(cell_map.values())
    n_ret = sum(1 for c in cells if c["kind"] == "retained")
    n_cold = len(cells) - n_ret
    return {
        "enabled": True,
        "mode": mode,
        "n_cells": len(cells),
        "n_sats": len(sat_ids),
        "n_retained": n_ret,
        "n_cold": n_cold,
        "cells": cells,
        "sats_sample": sat_ids[: max(0, int(sample))],
        "version": int(getattr(amap, "version", 0) or 0),
    }


def demo_cool_in_reach(amap: Any, *, n: int = 8, bump_version: bool = True) -> dict:
    """Cool a sample of session-reach sats (+ their cells). tick → retained TOMB.

    Does not rewrite density SoT. Atoms stay reachable (session + catalog roots).
    """
    from engine.grid import _set_T

    t_tomb, _t_warm = _thermal_thresholds()
    store = amap.store
    reach = session_reach(amap)
    sat_ids = [aid for aid in sorted(reach) if str(aid).startswith("sat:")]
    try:
        want = max(1, min(int(n), 40))
    except (TypeError, ValueError):
        want = 8
    cooled: List[str] = []
    for aid in sat_ids[:want]:
        atom = store.get_atom(aid)
        if atom is None:
            continue
        _set_T(atom, t_tomb * 0.4)
        cooled.append(str(aid))
        key = _cell_of_sat(amap, atom)
        if key is None:
            continue
        cell = store.get_atom(cell_atom_id(*key))
        if cell is not None:
            _set_T(cell, t_tomb * 0.4)
    if cooled and callable(getattr(store, "tick", None)):
        store.tick()
    if bump_version:
        amap.version = int(getattr(amap, "version", 0) or 0) + 1
    out = collect_ghost(amap)
    out["cooled"] = len(cooled)
    out["cooled_sample"] = cooled[:12]
    return out


def build_export_payload(
    amap: Any,
    *,
    state: Any = None,
    reach_only: bool = False,
    include_sats: bool = False,
    src: str = "",
    using: int = 0,
    fleet: str = "",
    country: str = "",
    max_sats: int = 50_000,
) -> dict:
    """File export: density view + reach + ghost. Sats optional (not API poll)."""
    from datetime import datetime, timezone

    snap = amap.snapshot(reach_only=bool(reach_only))
    rst = reach_status(amap, state=state)
    ghost = collect_ghost(amap, state=state)
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload: Dict[str, Any] = {
        "format": "karmin-satellite-export-v1",
        "created_at": created,
        "src": src,
        "using": int(using or 0),
        "fleet": fleet or "",
        "country": country or "",
        "reach_only": bool(reach_only),
        "grid_deg": snap.get("grid_deg"),
        "hot_only": snap.get("hot_only"),
        "version": snap.get("version"),
        "density": snap.get("density") or [],
        "shells": snap.get("shells") or {},
        "summary": snap.get("summary") or {},
        "reach": {
            "enabled": rst.get("enabled"),
            "mode": rst.get("mode"),
            "session": rst.get("session"),
            "scope": rst.get("scope"),
            "n_sats": rst.get("n_sats"),
            "n_cells": rst.get("n_cells"),
            "n_reach": rst.get("n_reach"),
        },
        "ghost": {
            "n_cells": ghost.get("n_cells"),
            "n_sats": ghost.get("n_sats"),
            "n_retained": ghost.get("n_retained"),
            "n_cold": ghost.get("n_cold"),
            "cells": ghost.get("cells") or [],
            "sats_sample": ghost.get("sats_sample") or [],
        },
    }
    if include_sats and hasattr(amap, "iter_sats"):
        sats_out: List[dict] = []
        for i, a in enumerate(amap.iter_sats()):
            if i >= int(max_sats):
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
                    "fleet": v.get("fleet"),
                    "lat": v.get("lat"),
                    "lon": v.get("lon"),
                    "alt_km": v.get("alt_km"),
                    "T": float(a.T),
                }
            )
        payload["sats"] = sats_out
    return payload


def export_as_markdown(payload: Mapping[str, Any]) -> str:
    """Human-readable export (reach + ghost + density, not a sat dump)."""
    reach = payload.get("reach") or {}
    ghost = payload.get("ghost") or {}
    summary = payload.get("summary") or {}
    dens = payload.get("density") or []
    top = sorted(dens, key=lambda c: -int(c.get("count") or 0))[:8]
    lines = [
        "# Karmin Satellite — export",
        "",
        f"**as_of:** {payload.get('created_at') or '—'}  ",
        f"**format:** `{payload.get('format')}`  ",
        f"**src:** {payload.get('src') or '—'}  ",
        f"**fleet:** {payload.get('fleet') or '—'}  "
        f"· country {payload.get('country') or '—'}  "
        f"· using {payload.get('using')}",
        f"**reach view:** {'yes' if payload.get('reach_only') else 'no (full density SoT)'}  ",
        "",
        "## Session reach",
        "",
        f"- enabled: {reach.get('enabled')}",
        f"- mode: `{reach.get('mode')}`",
        f"- session: `{reach.get('session')}`",
        f"- sats in reach: **{reach.get('n_sats')}**",
        f"- cells in reach: **{reach.get('n_cells')}**",
        f"- scope: `{reach.get('scope')}`",
        "",
        "## Ghost (retained / cold)",
        "",
        f"- ghost cells: **{ghost.get('n_cells')}** "
        f"(retained {ghost.get('n_retained')} · cold {ghost.get('n_cold')})",
        f"- retained sats: **{ghost.get('n_sats')}**",
        "",
        "## Density (SoT view in this file)",
        "",
        f"- cells: **{len(dens)}**",
        f"- hot cells: {summary.get('hot_cells', '—')}",
        f"- prop ms: {summary.get('prop_ms', '—')}",
        "",
    ]
    if top:
        lines.append("### Top cells")
        lines.append("")
        for c in top:
            lines.append(
                f"- `cell:{c.get('ilat')}:{c.get('ilon')}` · count {c.get('count')}"
            )
        lines.append("")
    if payload.get("sats"):
        lines.append(f"## Sats included: {len(payload['sats'])}")
        lines.append("")
    lines.extend(
        [
            "---",
            "",
            "Density is source of truth. Reach and ghost are views.  ",
            "Research workbench — not operational SSA.",
            "",
        ]
    )
    return "\n".join(lines)


# ── W3 impact_of_cooling (simulate default; density SoT untouched) ───────────


def ensure_bin_index(amap: Any) -> None:
    sat_to_cell = getattr(amap, "sat_to_cell", None)
    if isinstance(sat_to_cell, dict) and sat_to_cell:
        return
    if callable(getattr(amap, "rebuild_bin_index", None)):
        amap.rebuild_bin_index()
        return
    cell_to_sats: Dict[Tuple[int, int], Set[str]] = {}
    sat_map: Dict[str, Tuple[int, int]] = {}
    for atom in amap.iter_sats():
        key = _cell_of_sat(amap, atom)
        if key is None:
            continue
        aid = str(atom.id)
        cell_to_sats.setdefault(key, set()).add(aid)
        sat_map[aid] = key
    amap.cell_to_sats = cell_to_sats
    amap.sat_to_cell = sat_map


def resolve_cool_targets(
    amap: Any,
    *,
    cool_sats: Optional[Sequence[str]] = None,
    or_shell: str = "",
    or_fleet: str = "",
) -> List[str]:
    """Resolve sat ids to cool. Explicit list wins, then shell, then fleet."""
    out: List[str] = []
    if cool_sats:
        for raw in cool_sats:
            s = str(raw or "").strip()
            if not s:
                continue
            out.append(s if s.startswith("sat:") else sat_atom_id(s))
        return out
    shell_raw = str(or_shell or "").strip()
    if shell_raw and shell_raw not in ("all", "*", "shell:all"):
        sk = shell_bubble_id(shell_raw)
        idx = getattr(amap, "_shell_index", None) or {}
        return sorted(str(x) for x in idx.get(sk, set()))
    fleet_raw = str(or_fleet or "").strip()
    if fleet_raw and fleet_raw.lower() not in ("all", "*", "fleet:all"):
        fk = fleet_bubble_id(fleet_raw)
        idx = getattr(amap, "_fleet_index", None) or {}
        return sorted(str(x) for x in idx.get(fk, set()))
    return []


def _sat_shell(amap: Any, aid: str) -> str:
    atom = amap.store.get_atom(aid)
    if atom is None:
        return ""
    v = dict(getattr(atom, "metadata", None) or {})
    meta = dict(v.get("v") or v)
    sk = str(meta.get("shell") or "")
    if sk and not sk.startswith("shell:"):
        sk = f"shell:{sk}"
    return sk


def _hazard_delta_estimate(
    amap: Any,
    cooled: Sequence[str],
    *,
    weather: Any = None,
) -> dict:
    shells_before = dict(getattr(amap, "_shells", None) or {})
    shells_after = {k: int(v) for k, v in shells_before.items()}
    for aid in cooled:
        sk = _sat_shell(amap, aid)
        if sk in shells_after:
            shells_after[sk] = max(0, int(shells_after[sk]) - 1)
    tot_b = sum(int(v) for v in shells_before.values()) or 1
    tot_a = sum(int(v) for v in shells_after.values())
    gscore = 20.0
    if weather is not None:
        try:
            from engine.solar.hazard import assess_hazard

            ass = assess_hazard(
                weather, shells=shells_before, total_sats=tot_b
            )
            gscore = float(ass.global_score)
        except Exception:
            gscore = 20.0
    from engine.solar.hazard import group_score_adjust

    changed: List[dict] = []
    headline = ""
    headline_pct = 0.0
    for sk in sorted(set(shells_before) | set(shells_after)):
        nb = int(shells_before.get(sk, 0))
        na = int(shells_after.get(sk, 0))
        if nb == na:
            continue
        sb, _, _ = group_score_adjust(
            gscore, n_sats=nb, total_sats=tot_b, shell_key=sk
        )
        sa, _, _ = group_score_adjust(
            gscore, n_sats=na, total_sats=tot_a or 1, shell_key=sk
        )
        pct = 0.0 if nb <= 0 else round(100.0 * (na - nb) / nb, 1)
        row = {
            "shell": sk,
            "n_before": nb,
            "n_after": na,
            "score_before": sb,
            "score_after": sa,
            "score_delta": round(sa - sb, 1),
            "n_pct": pct,
        }
        changed.append(row)
        if abs(pct) >= abs(headline_pct):
            headline_pct = pct
            headline = sk
    return {
        "global_score": gscore,
        "shells": changed,
        "headline_shell": headline,
        "headline_n_pct": headline_pct,
    }


def impact_of_cooling(
    amap: Any,
    *,
    cool_sats: Optional[Sequence[str]] = None,
    or_shell: str = "",
    or_fleet: str = "",
    simulate: bool = True,
    weather: Any = None,
) -> dict:
    """What happens if these sats go cold.

    simulate=True (default): no store mutation, no version bump.
    simulate=False: cool those sats (retained if in reach) + tick. Density SoT stays.
    """
    ensure_bin_index(amap)
    targets = resolve_cool_targets(
        amap, cool_sats=cool_sats, or_shell=or_shell, or_fleet=or_fleet
    )
    target_set = set(targets)
    sat_to_cell = dict(getattr(amap, "sat_to_cell", None) or {})
    cell_to_sats = dict(getattr(amap, "cell_to_sats", None) or {})
    graph_used = False

    if reach_enabled() and getattr(amap, "_reach_session", None) is not None:
        reach_ids = session_reach(amap)
    else:
        reach_ids = {str(a.id) for a in amap.iter_sats()}
    n_sats_b, n_cells_b = _count_reach(reach_ids)

    touched: Set[Tuple[int, int]] = set()
    for aid in target_set:
        key = sat_to_cell.get(aid)
        if key is None:
            atom = amap.store.get_atom(aid)
            if atom is not None:
                key = _cell_of_sat(amap, atom)
        if key is not None:
            touched.add(key)
            cell_to_sats.setdefault(key, set()).add(aid)

    affected: List[dict] = []
    emptied: List[dict] = []
    for key in sorted(touched):
        graph_occ = occupants_from_graph(amap, key)
        if graph_occ is not None:
            occupants = graph_occ
            graph_used = True
        else:
            occupants = set(cell_to_sats.get(key, set()))
        remaining = occupants - target_set
        row = {
            "ilat": int(key[0]),
            "ilon": int(key[1]),
            "before": len(occupants),
            "after": len(remaining),
            "emptied": len(remaining) == 0,
        }
        affected.append(row)
        if row["emptied"]:
            emptied.append(row)

    emptied_keys = {(c["ilat"], c["ilon"]) for c in emptied}
    reach_after_sats = {
        a for a in reach_ids if str(a).startswith("sat:") and a not in target_set
    }
    reach_after_cells = {
        a
        for a in reach_ids
        if str(a).startswith("cell:") and parse_cell_id(str(a)) not in emptied_keys
    }
    # cells still occupied via remaining sats
    for aid in reach_after_sats:
        key = sat_to_cell.get(aid)
        if key is not None and key not in emptied_keys:
            reach_after_cells.add(cell_atom_id(*key))

    haz = _hazard_delta_estimate(amap, targets, weather=weather)
    shell_label = shell_bubble_id(or_shell) if or_shell else (
        haz.get("headline_shell") or "scope"
    )
    n_pct = haz.get("headline_n_pct") or 0.0
    src_tag = "graph" if graph_used else "index"
    line = (
        f"−{len(target_set)} sat → {len(emptied)} cell empty"
        f" · hazard {shell_label} {n_pct:.0f}%"
        f" · {src_tag}"
    )

    applied = False
    if not simulate and target_set:
        from engine.grid import _set_T

        t_tomb, _ = _thermal_thresholds()
        store = amap.store
        for aid in target_set:
            atom = store.get_atom(aid)
            if atom is None:
                continue
            _set_T(atom, t_tomb * 0.4)
            key = sat_to_cell.get(aid)
            if key is None:
                continue
            cell = store.get_atom(cell_atom_id(*key))
            if cell is not None:
                _set_T(cell, t_tomb * 0.4)
        if callable(getattr(store, "tick", None)):
            store.tick()
        amap.version = int(getattr(amap, "version", 0) or 0) + 1
        applied = True

    return {
        "simulate": bool(simulate),
        "applied": applied,
        "cool_n": len(target_set),
        "sats_sample": list(targets)[:12],
        "or_shell": shell_bubble_id(or_shell) if or_shell else "",
        "or_fleet": or_fleet or "",
        "affected_cells": affected,
        "n_affected": len(affected),
        "cells_emptied": emptied,
        "n_emptied": len(emptied),
        "reach_before": {"n_sats": n_sats_b, "n_cells": n_cells_b},
        "reach_after": {
            "n_sats": len(reach_after_sats),
            "n_cells": len(reach_after_cells),
        },
        "hazard_delta_estimate": haz,
        "line": line,
        "source": src_tag,
        "version": int(getattr(amap, "version", 0) or 0),
    }


# ── W4 resonance browse ─────────────────────────────────────────────────────


def hrr_available(store: Any = None) -> bool:
    try:
        from engine.bootstrap import ensure_paths

        ensure_paths()
        from karmazyn_kernel import HAS_HRR
    except Exception:
        return False
    if not HAS_HRR:
        return False
    if store is not None and not callable(getattr(store, "resonance", None)):
        return False
    return True


def _lexical_hits(amap: Any, query: str, k: int) -> List[Tuple[float, str]]:
    """Cheap exact/prefix match on shell, fleet, sat E/name. Cap k."""
    q = query.strip()
    qlow = q.lower()
    hits: List[Tuple[float, str]] = []
    if qlow.startswith("shell:") or (
        q.replace("shell:", "").replace("SHELL:", "").isdigit()
        and not qlow.startswith("fleet:")
    ):
        sk = shell_bubble_id(q)
        for aid in getattr(amap, "_shell_index", {}).get(sk, set()):
            hits.append((1.0, str(aid)))
    elif qlow.startswith("fleet:"):
        fk = fleet_bubble_id(q)
        for aid in getattr(amap, "_fleet_index", {}).get(fk, set()):
            hits.append((1.0, str(aid)))
    else:
        needle = qlow
        for atom in amap.iter_sats():
            e = str(getattr(atom, "E", "") or "").lower()
            v = dict(getattr(atom, "metadata", None) or {})
            meta = dict(v.get("v") or v)
            name = str(meta.get("name") or "").lower()
            shell = str(meta.get("shell") or "").lower()
            fleet = str(meta.get("fleet") or "").lower()
            blob = f"{e} {name} {shell} {fleet} {atom.id}"
            if needle in blob:
                hits.append((0.85, str(atom.id)))
            if len(hits) >= k * 4:
                break
    hits.sort(key=lambda x: -x[0])
    return hits[:k]


def studio_resonance(amap: Any, query: str, *, k: int = 20) -> dict:
    """HRR browse of named sat atoms → cells. No HRR → enabled false, lexical cells."""
    try:
        kk = max(1, min(int(k), 40))
    except (TypeError, ValueError):
        kk = 20
    q = str(query or "").strip()
    store = amap.store
    enabled = hrr_available(store)
    qlow = q.lower()
    structural = bool(
        qlow.startswith("shell:")
        or qlow.startswith("fleet:")
        or (q.replace("shell:", "").replace("SHELL:", "").isdigit())
    )
    if not q:
        return {
            "enabled": enabled,
            "mode": "off",
            "query": q,
            "hits": [],
            "cells": [],
            "n_hits": 0,
            "n_cells": 0,
        }
    ensure_bin_index(amap)
    scored: List[Tuple[float, str]] = []
    hrr_hits = 0
    if enabled and not structural:
        try:
            raw = store.resonance(q, k=kk) or []
            scored = [(float(s), str(aid)) for s, aid in raw]
            hrr_hits = len(scored)
        except Exception:
            scored = []
            enabled = False
    if structural or not scored:
        scored = _lexical_hits(amap, q, kk)
        if structural:
            mode = "scope"
        else:
            mode = "lexical"
    else:
        mode = "hrr"
        have = {aid for _s, aid in scored}
        for s, aid in _lexical_hits(amap, q, kk):
            if aid not in have:
                scored.append((s, aid))
                have.add(aid)
        scored.sort(key=lambda x: -x[0])
        scored = scored[:kk]

    sat_to_cell = getattr(amap, "sat_to_cell", None) or {}
    cells_map: Dict[Tuple[int, int], float] = {}
    hits_out: List[dict] = []
    for sim, aid in scored[:kk]:
        hits_out.append({"id": aid, "sim": round(float(sim), 4)})
        key = sat_to_cell.get(aid)
        if key is None:
            atom = store.get_atom(aid)
            if atom is not None:
                key = _cell_of_sat(amap, atom)
        if key is not None:
            prev = cells_map.get(key, 0.0)
            if sim > prev:
                cells_map[key] = float(sim)
    cells = [
        {"ilat": int(ik[0]), "ilon": int(ik[1]), "sim": round(s, 4)}
        for ik, s in sorted(cells_map.items(), key=lambda kv: -kv[1])
    ]
    return {
        "enabled": bool(enabled),
        "mode": mode if scored else "off",
        "query": q,
        "hits": hits_out,
        "cells": cells,
        "n_hits": len(hits_out),
        "n_cells": len(cells),
        "hrr_hits": hrr_hits,
    }


# ── W5 mini system-tick (fleets + layers, not O(N²) sats) ───────────────────


def _t_agg_fleet(amap: Any, fleet_key: str, reach: Optional[Set[str]]) -> dict:
    ids = set(getattr(amap, "_fleet_index", {}).get(fleet_key, set()) or [])
    in_scope = [aid for aid in ids if reach is None or aid in reach]
    n = len(in_scope)
    if n == 0:
        return {
            "n": 0,
            "n_catalog": len(ids),
            "hot_frac": 0.0,
            "warm_frac": 0.0,
            "dead_frac": 0.0,
        }
    store = amap.store
    hot = warm = dead = 0
    for aid in in_scope:
        atom = store.get_atom(aid)
        if atom is None:
            continue
        st = str(getattr(atom, "state", "") or "")
        if st == "HOT":
            hot += 1
        elif st == "WARM":
            warm += 1
        if callable(getattr(atom, "is_dead", None)) and atom.is_dead():
            dead += 1
    return {
        "n": n,
        "n_catalog": len(ids),
        "hot_frac": round(hot / n, 3),
        "warm_frac": round(warm / n, 3),
        "dead_frac": round(dead / n, 3),
    }


def get_decisions(amap: Any) -> List[dict]:
    raw = getattr(amap, "_studio_decisions", None)
    if not raw:
        return []
    return list(raw)[-10:]


def studio_system_tick(
    amap: Any,
    *,
    settle_local: int = 0,
    bump_version: bool = True,
) -> dict:
    """O(F²) on fleets+layers. Optional local Store.tick. Density dict untouched."""
    dens0 = dict(amap.density or {})
    try:
        n_settle = max(0, min(int(settle_local), 3))
    except (TypeError, ValueError):
        n_settle = 0
    store = amap.store
    if n_settle and callable(getattr(store, "tick", None)):
        for _ in range(n_settle):
            store.tick()

    reach: Optional[Set[str]] = None
    if getattr(amap, "_reach_session", None) is not None:
        reach = session_reach(amap)

    fleets = sorted(getattr(amap, "_fleet_index", {}).keys())
    if not fleets:
        fleets = ["fleet:starlink"]

    nodes = ["session:default", "layer:density", "layer:hazard"] + list(fleets)
    edges = []
    for fk in fleets:
        edges.append({"src": "session:default", "dst": fk, "kind": "protect"})
        edges.append({"src": "layer:density", "dst": fk, "kind": "cascade_soft"})
    edges.append({"src": "layer:hazard", "dst": "layer:density", "kind": "notify"})

    decisions: List[dict] = [
        {
            "node": "session:default",
            "action": "retain",
            "reason": "session root protects bound fleets",
        }
    ]
    for fk in fleets:
        agg = _t_agg_fleet(amap, fk, reach)
        if agg["n"] == 0:
            decisions.append(
                {
                    "node": fk,
                    "action": "note",
                    "reason": "empty after filter",
                    "t_agg": agg,
                }
            )
        elif agg["dead_frac"] >= 0.3:
            decisions.append(
                {
                    "node": fk,
                    "action": "cool_hint",
                    "reason": f"dead_frac={agg['dead_frac']:.0%}",
                    "t_agg": agg,
                }
            )
        else:
            decisions.append(
                {
                    "node": fk,
                    "action": "retain",
                    "reason": f"hot={agg['hot_frac']:.0%} warm={agg['warm_frac']:.0%}",
                    "t_agg": agg,
                }
            )
    n_cells = len(amap.density or {})
    decisions.append(
        {
            "node": "layer:density",
            "action": "note",
            "reason": f"{n_cells} hot-only cells (SoT)",
        }
    )
    decisions.append(
        {
            "node": "layer:hazard",
            "action": "notify",
            "reason": "weather + density overlay",
        }
    )

    prev = list(getattr(amap, "_studio_decisions", None) or [])
    amap._studio_decisions = (prev + decisions)[-10:]
    mutated = n_settle > 0
    if bump_version and mutated:
        amap.version = int(getattr(amap, "version", 0) or 0) + 1

    if dict(amap.density or {}) != dens0:
        amap.density = dens0

    return {
        "nodes": nodes,
        "edges": edges,
        "decisions": decisions,
        "log": get_decisions(amap),
        "settle_local": n_settle,
        "ticked": n_settle,
        "advisory": True,
        "density_mutated": False,
        "version": int(getattr(amap, "version", 0) or 0),
        "n_fleets": len(fleets),
    }


# ── Live root + depends_on graph (atom wow scripts cannot fake) ─────────────


def write_depends_on(amap: Any) -> int:
    """Stamp cell.v.depends_on and sat.v.feeds from the bin index. Live edges."""
    store = amap.store
    cell_to_sats = getattr(amap, "cell_to_sats", None) or {}
    sat_to_cell = getattr(amap, "sat_to_cell", None) or {}
    n = 0
    for (ilat, ilon), sats in cell_to_sats.items():
        atom = store.get_atom(cell_atom_id(int(ilat), int(ilon)))
        if atom is None:
            continue
        v = dict(atom.metadata.get("v") or {})
        v["depends_on"] = sorted(str(s) for s in sats)
        atom.metadata["v"] = v
        n += 1
    for aid, key in sat_to_cell.items():
        atom = store.get_atom(aid)
        if atom is None:
            continue
        v = dict(atom.metadata.get("v") or {})
        v["feeds"] = cell_atom_id(int(key[0]), int(key[1]))
        atom.metadata["v"] = v
    return n


def occupants_from_graph(
    amap: Any, key: Tuple[int, int]
) -> Optional[Set[str]]:
    """Read depends_on from the cell atom. None if the edge is missing."""
    atom = amap.store.get_atom(cell_atom_id(int(key[0]), int(key[1])))
    if atom is None:
        return None
    v = dict(atom.metadata.get("v") or {})
    deps = v.get("depends_on")
    if deps is None:
        return None
    return {str(x) for x in deps}


def graph_edge_count(amap: Any) -> int:
    n = 0
    for atom in amap.iter_cells():
        v = dict(atom.metadata.get("v") or {})
        deps = v.get("depends_on") or []
        n += len(deps)
    return n


def _session_bubble(amap: Any):
    sc = get_scope(amap)
    return amap.store.get_bubble(session_bubble_id(sc.session_id))


def set_live_root(amap: Any, exclusive: bool) -> dict:
    """exclusive=True: session is the only Store root. Catalog TLE stays in Python."""
    store = amap.store
    ensure_session(amap)
    session = _session_bubble(amap)
    star = store.get_bubble("starlink")
    if exclusive:
        for b in list(getattr(store, "roots", []) or []):
            if b is not session:
                store.unset_root(b)
        if session is not None:
            store.set_root(session)
        amap._live_root = True
    else:
        if star is not None:
            store.set_root(star)
        if session is not None:
            store.set_root(session)
        amap._live_root = False
    return attention_status(amap)


def rebuild_density_from_atoms(amap: Any) -> int:
    """Rebin remaining sat atoms (last lat/lon). No extra SGP4."""
    counts: Dict[Tuple[int, int], int] = {}
    for atom in amap.iter_sats():
        key = _cell_of_sat(amap, atom)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
    amap.density = counts
    if callable(getattr(amap, "_apply_density_unlocked", None)):
        amap._apply_density_unlocked(counts)
    elif callable(getattr(amap, "apply_density", None)):
        amap.apply_density(counts)
    if callable(getattr(amap, "rebuild_bin_index", None)):
        amap.rebuild_bin_index()
    write_depends_on(amap)
    shells: Dict[str, Set[str]] = {}
    fleets: Dict[str, Set[str]] = {}
    for atom in amap.iter_sats():
        v = dict(atom.metadata.get("v") or {})
        sk = str(v.get("shell") or "")
        fk = str(v.get("fleet") or "starlink")
        if sk:
            if not sk.startswith("shell:"):
                sk = f"shell:{sk}"
            shells.setdefault(sk, set()).add(str(atom.id))
        fkey = fk if fk.startswith("fleet:") else f"fleet:{fk}"
        fleets.setdefault(fkey, set()).add(str(atom.id))
    amap._shell_index = shells
    amap._shells = {k: len(v) for k, v in shells.items()}
    amap._fleet_index = fleets
    return len(counts)


def commit_attention(amap: Any) -> dict:
    """Cool atoms outside session reach and tick. Out of root → vacuum.

    In-session cold → retained TOMB (ghost). Density rebuilt from survivors.
    """
    if not getattr(amap, "_live_root", False):
        set_live_root(amap, True)
    from engine.grid import _set_T

    t_tomb, _ = _thermal_thresholds()
    store = amap.store
    reach = session_reach(amap)
    candidates: List[str] = []
    for atom in list(store.atoms()):
        aid = str(atom.id)
        if aid in reach:
            continue
        if not (aid.startswith("sat:") or aid.startswith("cell:")):
            continue
        _set_T(atom, t_tomb * 0.4)
        candidates.append(aid)
    if candidates and callable(getattr(store, "tick", None)):
        store.tick()
    vacuumed = [aid for aid in candidates if not store.has_atom(aid)]
    retained = []
    for aid in reach:
        atom = store.get_atom(aid)
        if atom is None:
            continue
        if callable(getattr(atom, "is_dead", None)) and atom.is_dead():
            retained.append(aid)
    n_cells = rebuild_density_from_atoms(amap)
    amap.version = int(getattr(amap, "version", 0) or 0) + 1
    n_sats = sum(1 for _ in amap.iter_sats())
    n_edges = graph_edge_count(amap)
    stats = {
        "live": True,
        "vacuumed": len(vacuumed),
        "vacuumed_sample": vacuumed[:12],
        "retained": len(retained),
        "remaining_sats": n_sats,
        "remaining_cells": n_cells,
        "graph_edges": n_edges,
        "version": amap.version,
        "line": (
            f"live root · vacuumed {len(vacuumed)} · retained {len(retained)}"
            f" · {n_sats} sats · graph {n_edges} deps"
        ),
    }
    amap._attention = stats
    return stats


def apply_live_scope(
    amap: Any,
    catalog: Optional[Sequence[Any]] = None,
    **scope: Any,
) -> dict:
    """Rehydrate from TLE catalog if needed, bind session, vacuum the rest."""
    if catalog:
        before = {str(a.id) for a in amap.iter_sats()}
        amap.ingest_sats(catalog, gc_missing=False)
        created = {f"sat:{s.norad}" for s in catalog} - before
        if created:
            amap.refresh(catalog, ensure=False)
    set_live_root(amap, True)
    info = set_session_scope(amap, bump_version=False, **scope)
    committed = commit_attention(amap)
    info["attention"] = committed
    info["live"] = True
    info["version"] = committed["version"]
    return info


def restore_catalog(
    amap: Any,
    catalog: Optional[Sequence[Any]] = None,
) -> dict:
    """Put starlink back as root and re-ingest the TLE catalog."""
    set_live_root(amap, False)
    if catalog:
        amap.ingest_sats(catalog, gc_missing=False)
        amap.refresh(catalog, ensure=True)
    else:
        write_depends_on(amap)
    sc = get_scope(amap)
    set_session_scope(
        amap,
        shell=sc.shell,
        fleet=sc.fleet,
        country=sc.country,
        min_count=sc.min_count,
        bump_version=False,
    )
    amap._attention = {
        "live": False,
        "vacuumed": 0,
        "retained": 0,
        "remaining_sats": sum(1 for _ in amap.iter_sats()),
        "line": "catalog root restored",
    }
    return attention_status(amap)


def attention_status(amap: Any) -> dict:
    live = bool(getattr(amap, "_live_root", False))
    roots = []
    store = amap.store
    for b in list(getattr(store, "roots", []) or []):
        roots.append(getattr(b, "label", "") or "?")
    prev = dict(getattr(amap, "_attention", None) or {})
    n_sats = sum(1 for _ in amap.iter_sats())
    return {
        "live": live,
        "roots": roots,
        "session": get_scope(amap).session_id,
        "sats": n_sats,
        "cells": len(amap.density or {}),
        "graph_edges": graph_edge_count(amap),
        "vacuumed": int(prev.get("vacuumed") or 0),
        "retained": int(prev.get("retained") or 0),
        "line": prev.get("line")
        or (
            "live root · session is the only GC root"
            if live
            else "catalog root · scripts-compatible"
        ),
        "version": int(getattr(amap, "version", 0) or 0),
    }
