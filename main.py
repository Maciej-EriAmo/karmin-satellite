#!/usr/bin/env python3
"""
Karmin Satellite — entry point
============================
Standalone product: thermal atom substrate + Starlink engine + solar context.

  python main.py weather [--offline] [--force]
  python main.py predict [--offline] [--force]
  python main.py hazard  --offline-demo --limit 40
  python main.py report  --offline-demo --limit 40 --offline --md --json
  python main.py geo     --offline-demo --limit 40 --no-heatmap
  python main.py fleets
  python main.py --fleet oneweb --limit 200
  python main.py studio  --fleet starlink --offline-demo --limit 40 --open-browser
  python main.py         --offline-demo --limit 40 --hot-only
  python main.py --help

Solar: engine/solar/ · fleets: engine/catalogs.py (H7 Celestrak).
KarmazynOs is optional (env KARMAZYN_OS for Lua tools later).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_SUB = ROOT / "substrate"
if str(_SUB) not in sys.path:
    sys.path.insert(0, str(_SUB))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.starlink_atoms import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
