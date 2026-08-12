"""Compatibility shim — prefer ``engine.solar``."""
from __future__ import annotations

from engine.solar.hazard import *  # noqa: F403
from engine.solar.hazard import (  # noqa: F401
    HazardAssessment,
    HazardGroup,
    assess_from_amap,
    assess_hazard,
    base_score_for_shell,
    build_overlay,
    combine_global,
    exposure_cells,
    severity_for_score,
    short_badge,
)
