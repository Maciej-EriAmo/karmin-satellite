"""Path + substrate bootstrap for engine modules."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SUBSTRATE = ROOT / "substrate"


def ensure_paths() -> Path:
    if str(_SUBSTRATE) not in sys.path:
        sys.path.insert(0, str(_SUBSTRATE))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault("KARMAZYN_SUBSTRATE", "python")
    return ROOT


ensure_paths()
