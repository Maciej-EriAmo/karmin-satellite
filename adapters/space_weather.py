#!/usr/bin/env python3
"""
Public space-weather adapter (NOAA SWPC) for Cynober Studio.

Research / enthusiast tool — public indices only (no private ops data).

Sources (no API key):
  - F10.7 cm flux:     services.swpc.noaa.gov/json/f107_cm_flux.json
  - GOES X-ray 6h:     …/json/goes/primary/xrays-6-hour.json
  - Planetary Kp:      …/products/noaa-planetary-k-index.json

Offline: returns a quiet-Sun stub when network/cache fails.
Cache: out/space_weather_cache.json (TTL default 15 min).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

USER_AGENT = "CynoberStudio/1.0 (+research; public NOAA SWPC)"

URL_F107 = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
URL_XRAY = "https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json"
URL_KP = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

# Quiet-Sun reference (approximate solar-min-ish; not a prediction)
STUB_F107 = 70.0
STUB_XRAY = 1.0e-8  # A-class floor
STUB_KP = 1.0

DEFAULT_CACHE_TTL_SEC = 15 * 60
DEFAULT_TIMEOUT_SEC = 12.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_cache_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "out" / "space_weather_cache.json"


def flare_class_from_flux(flux_w_m2: float) -> Tuple[str, float]:
    """
    GOES XRS long channel (0.1–0.8 nm) → NOAA flare class letter + magnitude.

    A: 1e-8, B: 1e-7, C: 1e-6, M: 1e-5, X: 1e-4  (W/m²).
    Returns e.g. ("C", 3.2) for C3.2.
    """
    f = float(flux_w_m2) if flux_w_m2 and flux_w_m2 > 0 else 1e-9
    if f < 1e-8:
        return "A", max(0.1, f / 1e-8)
    if f < 1e-7:
        return "A", f / 1e-8
    if f < 1e-6:
        return "B", f / 1e-7
    if f < 1e-5:
        return "C", f / 1e-6
    if f < 1e-4:
        return "M", f / 1e-5
    return "X", f / 1e-4


def format_flare_class(letter: str, mag: float) -> str:
    return f"{letter}{mag:.1f}"


@dataclass
class SpaceWeatherSnapshot:
    """Normalized public indices for Studio."""

    as_of: str
    source: str = "noaa-swpc"
    mode: str = "live"  # live | cache | stub
    f107: Optional[float] = None
    f107_time: Optional[str] = None
    xray_flux: Optional[float] = None  # W/m² long channel
    xray_time: Optional[str] = None
    flare_class: str = "A0.0"
    flare_letter: str = "A"
    flare_mag: float = 0.0
    kp: Optional[float] = None
    kp_time: Optional[str] = None
    message: str = ""
    disclaimer: str = (
        "Public NOAA SWPC indices only — research proxy, not operational "
        "radiation/collision certification."
    )
    fetched_at: str = field(default_factory=_utc_now_iso)
    raw_meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def quiet_stub(*, reason: str = "offline") -> SpaceWeatherSnapshot:
    letter, mag = flare_class_from_flux(STUB_XRAY)
    return SpaceWeatherSnapshot(
        as_of=_utc_now_iso(),
        source="stub-quiet-sun",
        mode="stub",
        f107=STUB_F107,
        f107_time=None,
        xray_flux=STUB_XRAY,
        xray_time=None,
        flare_class=format_flare_class(letter, mag),
        flare_letter=letter,
        flare_mag=round(mag, 2),
        kp=STUB_KP,
        kp_time=None,
        message=f"stub: {reason}",
    )


def _http_get_json(url: str, *, timeout: float) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _pick_latest_f107(rows: List[dict]) -> Tuple[Optional[float], Optional[str]]:
    if not rows:
        return None, None
    # prefer Morning reporting if present, else last
    morning = [r for r in rows if str(r.get("reporting_schedule") or "") == "Morning"]
    use = morning[-1] if morning else rows[-1]
    try:
        return float(use["flux"]), str(use.get("time_tag") or "")
    except (KeyError, TypeError, ValueError):
        return None, None


def _pick_latest_xray(rows: List[dict]) -> Tuple[Optional[float], Optional[str]]:
    """Prefer long channel 0.1-0.8nm (1–8 Å)."""
    if not rows:
        return None, None
    long = [
        r
        for r in rows
        if str(r.get("energy") or "") in ("0.1-0.8nm", "1-8A", "1.0-8.0A")
    ]
    pool = long if long else rows
    use = pool[-1]
    try:
        flux = use.get("flux")
        if flux is None:
            flux = use.get("observed_flux")
        return float(flux), str(use.get("time_tag") or "")
    except (TypeError, ValueError):
        return None, None


def _pick_latest_kp(rows: List[Any]) -> Tuple[Optional[float], Optional[str]]:
    if not rows:
        return None, None
    # product sometimes starts with header row of strings
    data_rows = [r for r in rows if isinstance(r, dict) and "Kp" in r]
    if not data_rows:
        # alternate: list of lists ["time_tag","Kp",...]
        last = rows[-1]
        if isinstance(last, list) and len(last) >= 2:
            try:
                return float(last[1]), str(last[0])
            except (TypeError, ValueError):
                return None, None
        return None, None
    use = data_rows[-1]
    try:
        return float(use["Kp"]), str(use.get("time_tag") or "")
    except (KeyError, TypeError, ValueError):
        return None, None


def parse_swpc_bundle(
    *,
    f107_rows: Any,
    xray_rows: Any,
    kp_rows: Any,
    mode: str = "live",
) -> SpaceWeatherSnapshot:
    f107, f107_t = _pick_latest_f107(list(f107_rows or []))
    xray, xray_t = _pick_latest_xray(list(xray_rows or []))
    kp, kp_t = _pick_latest_kp(list(kp_rows or []))

    if xray is None:
        xray = STUB_XRAY
    letter, mag = flare_class_from_flux(xray)
    as_of = xray_t or f107_t or kp_t or _utc_now_iso()

    return SpaceWeatherSnapshot(
        as_of=str(as_of),
        source="noaa-swpc",
        mode=mode,
        f107=f107 if f107 is not None else STUB_F107,
        f107_time=f107_t,
        xray_flux=xray,
        xray_time=xray_t,
        flare_class=format_flare_class(letter, mag),
        flare_letter=letter,
        flare_mag=round(mag, 2),
        kp=kp if kp is not None else STUB_KP,
        kp_time=kp_t,
        message="ok" if mode == "live" else f"mode={mode}",
        raw_meta={
            "f107_n": len(f107_rows or []),
            "xray_n": len(xray_rows or []),
            "kp_n": len(kp_rows or []),
        },
    )


class SpaceWeatherClient:
    """Fetch + disk cache for NOAA SWPC public products."""

    def __init__(
        self,
        *,
        cache_path: Optional[Path] = None,
        cache_ttl_sec: float = DEFAULT_CACHE_TTL_SEC,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        allow_network: bool = True,
    ):
        self.cache_path = Path(cache_path) if cache_path else _default_cache_path()
        self.cache_ttl_sec = float(cache_ttl_sec)
        self.timeout_sec = float(timeout_sec)
        self.allow_network = bool(allow_network)

    def _read_cache(self) -> Optional[dict]:
        p = self.cache_path
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_cache(self, snap: SpaceWeatherSnapshot, bundle: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": time.time(),
            "snapshot": snap.as_dict(),
            "bundle": bundle,
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def fetch(self, *, force: bool = False) -> SpaceWeatherSnapshot:
        """Return snapshot: live → fresh cache → stub."""
        if not force:
            cached = self._read_cache()
            if cached and (time.time() - float(cached.get("saved_at") or 0)) < self.cache_ttl_sec:
                snap_d = cached.get("snapshot") or {}
                try:
                    return SpaceWeatherSnapshot(**{
                        k: snap_d[k]
                        for k in SpaceWeatherSnapshot.__dataclass_fields__
                        if k in snap_d
                    })
                except TypeError:
                    pass

        if not self.allow_network:
            cached = self._read_cache()
            if cached and cached.get("snapshot"):
                snap_d = cached["snapshot"]
                snap_d = dict(snap_d)
                snap_d["mode"] = "cache"
                snap_d["message"] = "network disabled; using cache"
                try:
                    return SpaceWeatherSnapshot(
                        **{
                            k: snap_d[k]
                            for k in SpaceWeatherSnapshot.__dataclass_fields__
                            if k in snap_d
                        }
                    )
                except TypeError:
                    pass
            return quiet_stub(reason="network disabled, no cache")

        errors: List[str] = []
        f107_rows: Any = []
        xray_rows: Any = []
        kp_rows: Any = []
        try:
            f107_rows = _http_get_json(URL_F107, timeout=self.timeout_sec)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            errors.append(f"f107:{e}")
        try:
            xray_rows = _http_get_json(URL_XRAY, timeout=self.timeout_sec)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            errors.append(f"xray:{e}")
        try:
            kp_rows = _http_get_json(URL_KP, timeout=self.timeout_sec)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            errors.append(f"kp:{e}")

        if not f107_rows and not xray_rows and not kp_rows:
            cached = self._read_cache()
            if cached and cached.get("snapshot"):
                snap_d = dict(cached["snapshot"])
                snap_d["mode"] = "cache"
                snap_d["message"] = "fetch failed; stale cache: " + "; ".join(errors)[:200]
                try:
                    return SpaceWeatherSnapshot(
                        **{
                            k: snap_d[k]
                            for k in SpaceWeatherSnapshot.__dataclass_fields__
                            if k in snap_d
                        }
                    )
                except TypeError:
                    pass
            return quiet_stub(reason="; ".join(errors)[:180] or "fetch failed")

        snap = parse_swpc_bundle(
            f107_rows=f107_rows or [],
            xray_rows=xray_rows or [],
            kp_rows=kp_rows or [],
            mode="live",
        )
        if errors:
            snap.message = "partial: " + "; ".join(errors)[:200]
        bundle = {"f107": f107_rows, "xray": xray_rows, "kp": kp_rows}
        try:
            self._write_cache(snap, bundle={k: (v[-3:] if isinstance(v, list) else v) for k, v in bundle.items()})
        except Exception:
            pass
        return snap


def get_space_weather(
    *,
    force: bool = False,
    offline: bool = False,
    cache_path: Optional[Path] = None,
) -> SpaceWeatherSnapshot:
    """Module-level helper for API / CLI."""
    client = SpaceWeatherClient(
        cache_path=cache_path,
        allow_network=not offline,
    )
    return client.fetch(force=force)
