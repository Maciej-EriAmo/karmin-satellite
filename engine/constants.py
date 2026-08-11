"""Shared constants for Starlink engine."""
from __future__ import annotations

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

# ── Scale architecture (pure-Python Studio path) ────────────────────────────
# Kanon: docs/ARCHITECTURE_LIMITS.md  ·  baseline: docs/capacity_baseline.json
# Measured 2026-08-11: 50k ~5.7s e2e, 100k ~11.6s e2e, 0 prop errors (SGP4 hot-only).
ARCH_USABLE_SATS = 50_000  # recommended operating budget (design target)
ARCH_CEILING_SATS = 100_000  # hard max per map/session (build_map arch_cap)
# Back-compat alias (= ceiling). Do not reintroduce 12k.
ARCH_MAX_SATS = ARCH_CEILING_SATS

# CLI default sample size (dev only — NOT product max).
# 0 = entire catalog (capped at ceiling if arch_cap).
DEFAULT_LIMIT = 400

try:
    from sgp4.api import Satrec, jday as sgp4_jday

    HAS_SGP4 = True
except Exception:
    Satrec = None  # type: ignore
    sgp4_jday = None  # type: ignore
    HAS_SGP4 = False

# back-compat alias used by older code
_HAS_SGP4 = HAS_SGP4
