#!/usr/bin/env python3
"""
Cynober Studio — entry point
============================
Standalone product: thermal atom substrate + Starlink engine.

  python main.py --offline-demo --limit 40 --hot-only
  python main.py --limit 400 --prop sgp4 --html
  python main.py --offline-demo --limit 40 --studio --open-browser
  python main.py --offline-demo --limit 40 --studio --live-feed --interval 30
  python main.py --help

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
