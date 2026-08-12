"""
Solar context package (public NOAA SWPC + research hazard/predict).

Inside the engine — not bolted-on CLI flags.

  from engine.solar import get_space_weather, assess_from_amap, predict_horizons
"""
from __future__ import annotations

from engine.solar.hazard import (
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
from engine.solar.predict import (
    DEFAULT_HORIZONS_H,
    HorizonForecast,
    PredictAssessment,
    predict_horizons,
    short_horizon_line,
)
from engine.solar.geo import (
    DEFAULT_ALT_BANDS,
    GeoContext,
    assess_geo_from_amap,
    assess_geo_from_positions,
    is_sunlit,
    short_geo_line,
    solar_elevation_deg,
)
from engine.solar.report import (
    HazardReport,
    build_hazard_report,
    collect_solar_for_map,
)
from engine.solar.weather import (
    SpaceWeatherClient,
    SpaceWeatherSnapshot,
    flare_class_from_flux,
    format_flare_class,
    get_space_weather,
    get_space_weather_bundle,
    parse_swpc_bundle,
    quiet_stub,
    series_from_bundle,
)

__all__ = [
    "DEFAULT_ALT_BANDS",
    "DEFAULT_HORIZONS_H",
    "GeoContext",
    "HazardAssessment",
    "HazardGroup",
    "HazardReport",
    "HorizonForecast",
    "PredictAssessment",
    "SpaceWeatherClient",
    "SpaceWeatherSnapshot",
    "assess_from_amap",
    "assess_geo_from_amap",
    "assess_geo_from_positions",
    "assess_hazard",
    "base_score_for_shell",
    "build_hazard_report",
    "build_overlay",
    "collect_solar_for_map",
    "combine_global",
    "exposure_cells",
    "flare_class_from_flux",
    "format_flare_class",
    "get_space_weather",
    "get_space_weather_bundle",
    "is_sunlit",
    "parse_swpc_bundle",
    "predict_horizons",
    "quiet_stub",
    "series_from_bundle",
    "severity_for_score",
    "short_badge",
    "short_geo_line",
    "short_horizon_line",
    "solar_elevation_deg",
]
