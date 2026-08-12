"""Compatibility shim — prefer ``engine.solar``."""
from __future__ import annotations

from engine.solar.predict import *  # noqa: F403
from engine.solar.predict import (  # noqa: F401
    DEFAULT_HORIZONS_H,
    HorizonForecast,
    PredictAssessment,
    predict_horizons,
    short_horizon_line,
)
