"""Optional KarmazynOs Lua projection / tools."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from engine.bootstrap import ensure_paths

ensure_paths()
from karmazyn_kernel import (  # noqa: E402
    T_HOT,
    T_WARM,
    open_store,
    state_for_T,
)

from engine.constants import S_CELL, S_SAT
from engine.map import StarlinkAtomMap

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
