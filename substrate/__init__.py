"""
Karmin Satellite substrate — pure-Python thermal atom engine.

Vendored from KarmazynOs kernel (atom / store / reach-GC).
Standalone: no native Rust DLL required.
Optional re-link to KarmazynOs later via KARMAZYN_OS / shared protocol.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

__version__ = "0.1.0"
__all__ = [
    "open_store",
    "T_HOT",
    "T_INIT",
    "T_MAX",
    "T_WARM",
    "T_TOMB",
    "state_for_T",
]


def __getattr__(name: str):
    # Lazy re-export so `from substrate import open_store` works
    if name in __all__ or name in {
        "Atom",
        "Store",
        "PythonStore",
        "HAS_HRR",
    }:
        from karmazyn_kernel import (  # noqa: WPS433
            T_HOT,
            T_INIT,
            T_MAX,
            T_TOMB,
            T_WARM,
            open_store,
            state_for_T,
        )
        import karmazyn_kernel as _k

        mapping = {
            "open_store": open_store,
            "T_HOT": T_HOT,
            "T_INIT": T_INIT,
            "T_MAX": T_MAX,
            "T_WARM": T_WARM,
            "T_TOMB": T_TOMB,
            "state_for_T": state_for_T,
            "Atom": getattr(_k, "Atom", None),
            "Store": getattr(_k, "Store", None),
            "PythonStore": getattr(_k, "PythonStore", None),
            "HAS_HRR": getattr(_k, "HAS_HRR", False),
        }
        if name in mapping:
            return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
