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

try:
    from sgp4.api import Satrec, jday as sgp4_jday

    HAS_SGP4 = True
except Exception:
    Satrec = None  # type: ignore
    sgp4_jday = None  # type: ignore
    HAS_SGP4 = False

# back-compat alias used by older code
_HAS_SGP4 = HAS_SGP4
