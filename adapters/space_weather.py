"""Compatibility shim — prefer ``engine.solar.weather``."""
from __future__ import annotations

from engine.solar.weather import *  # noqa: F403
from engine.solar.weather import (  # noqa: F401
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
