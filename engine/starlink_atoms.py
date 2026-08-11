#!/usr/bin/env python3
"""
starlink_atoms — compatibility facade for Cynober Studio engine.

Implementation lives in split modules:
  bootstrap, constants, tle, prop, grid, map, export_2d, build, lua_bridge, cli

  python -m engine.starlink_atoms --offline-demo --limit 40 --hot-only
  python main.py --studio --studio-mode 3d
"""
from __future__ import annotations

from engine.bootstrap import ensure_paths

ensure_paths()

from engine.build import build_map
from engine.cli import main
from engine.constants import (
    CELESTRAK_URLS,
    HAS_SGP4,
    MU_EARTH,
    R_EARTH,
    S_CELL,
    S_SAT,
    USER_AGENT,
)
from engine.export_2d import export_report_payload, render_heatmap_png, write_html_report
from engine.grid import cell_id, density_to_T, latlon_to_bin, t_to_rgb
from engine.lua_bridge import project_starlink_view, run_lua_tool_name
from engine.map import StarlinkAtomMap
from engine.prop import (
    position_approx,
    position_of,
    position_sgp4,
    resolve_prop_mode,
)
from engine.tle import (
    TleSat,
    demo_tle_blob,
    fetch_starlink_tle,
    load_tle_text,
    parse_tle_catalog,
)

# back-compat
_HAS_SGP4 = HAS_SGP4

__all__ = [
    "StarlinkAtomMap",
    "TleSat",
    "build_map",
    "main",
    "parse_tle_catalog",
    "load_tle_text",
    "fetch_starlink_tle",
    "demo_tle_blob",
    "position_of",
    "position_sgp4",
    "position_approx",
    "resolve_prop_mode",
    "cell_id",
    "latlon_to_bin",
    "density_to_T",
    "t_to_rgb",
    "export_report_payload",
    "render_heatmap_png",
    "write_html_report",
    "project_starlink_view",
    "run_lua_tool_name",
    "S_SAT",
    "S_CELL",
    "HAS_SGP4",
    "_HAS_SGP4",
    "CELESTRAK_URLS",
    "USER_AGENT",
    "MU_EARTH",
    "R_EARTH",
]


if __name__ == "__main__":
    raise SystemExit(main())
