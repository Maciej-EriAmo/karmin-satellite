#!/usr/bin/env python3
"""
H3 — horizon forecasts (1h / 6h / 24h) from public SWPC indices.

Research heuristic only:
  - X-ray flux: exponential decay toward quiet + optional short-term trend
  - Kp: geometric relaxation toward quiet + optional trend
  - F10.7: near-constant on short horizons; mild mean-reversion at 24h
  - Scores via the same combine_global / severity as H1 hazard

NOT an operational solar forecast or radiation certification.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from engine.solar.hazard import combine_global, severity_for_score

# Canonical horizons (hours)
DEFAULT_HORIZONS_H: Tuple[float, ...] = (1.0, 6.0, 24.0)

# Quiet baselines (align with engine.solar.weather stubs)
QUIET_XRAY = 1.0e-8
QUIET_KP = 1.0
QUIET_F107 = 70.0

# Component half-lives for elevated activity (hours) — research knobs
XRAY_HALF_LIFE_H = {
    "A": 12.0,
    "B": 8.0,
    "C": 4.0,
    "M": 2.5,
    "X": 1.5,
}
KP_HALF_LIFE_H = 8.0
F107_MEAN_REVERT_TAU_H = 72.0  # slow; only visible at 24h


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    t = str(s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _exp_toward(current: float, baseline: float, hours: float, half_life_h: float) -> float:
    """Exponential relaxation of (current - baseline) toward baseline."""
    if half_life_h <= 0:
        return baseline
    decay = math.pow(0.5, float(hours) / float(half_life_h))
    return baseline + (float(current) - baseline) * decay


def _linear_trend_per_hour(
    series: Sequence[Tuple[float, float]],
) -> Optional[float]:
    """
    series: list of (hours_ago_negative_or_epoch_hours, value) sorted by time.
    Returns slope in value units per hour, or None if too short.
    Uses last up to 12 points; simple least-squares on relative hours.
    """
    pts = [(float(t), float(v)) for t, v in series if v is not None]
    if len(pts) < 2:
        return None
    pts = pts[-12:]
    t0 = pts[0][0]
    xs = [p[0] - t0 for p in pts]
    ys = [p[1] for p in pts]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x < 1e-12:
        return 0.0
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / var_x


def _weather_dict(weather: Any) -> dict:
    if hasattr(weather, "as_dict"):
        return weather.as_dict()
    return dict(weather or {})


def _flare_from_flux(flux: float) -> Tuple[str, float, str]:
    from engine.solar.weather import flare_class_from_flux, format_flare_class

    letter, mag = flare_class_from_flux(float(flux))
    return letter, float(mag), format_flare_class(letter, mag)


@dataclass
class HorizonForecast:
    horizon_h: float
    label: str
    at: str
    flare_class: str
    flare_letter: str
    flare_mag: float
    f107: float
    kp: float
    xray_flux: float
    global_score: float
    severity: str
    drivers: List[str] = field(default_factory=list)
    trend_note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PredictAssessment:
    as_of: str
    now_score: float
    now_severity: str
    weather_now: dict
    horizons: List[HorizonForecast]
    method: str
    series_used: Dict[str, int]
    prop_minutes: Optional[float] = None
    disclaimer: str = (
        "Public-index horizon proxy (decay + short trend) — "
        "not an operational solar forecast or radiation certification."
    )
    version: str = "predict-v1"

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "now_score": self.now_score,
            "now_severity": self.now_severity,
            "weather_now": self.weather_now,
            "horizons": [h.as_dict() for h in self.horizons],
            "method": self.method,
            "series_used": self.series_used,
            "prop_minutes": self.prop_minutes,
            "disclaimer": self.disclaimer,
            "version": self.version,
        }


def normalize_series(
    series: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, List[Tuple[float, float]]]:
    """
    Accept flexible series shapes → {xray|kp|f107: [(hours_from_now, value), ...]}
    hours_from_now is ≤ 0 for history (0 = now).
    """
    now = now or _utc_now()
    out: Dict[str, List[Tuple[float, float]]] = {"xray": [], "kp": [], "f107": []}
    if not series:
        return out

    def _ingest(key: str, rows: Any) -> None:
        if not rows:
            return
        for r in rows:
            if isinstance(r, dict):
                t = _parse_iso(r.get("time_tag") or r.get("t") or r.get("time"))
                val = r.get("flux") if key == "xray" else r.get(key if key != "xray" else "flux")
                if key == "xray":
                    val = r.get("flux", r.get("value"))
                elif key == "kp":
                    val = r.get("Kp", r.get("kp", r.get("value")))
                elif key == "f107":
                    val = r.get("flux", r.get("f107", r.get("value")))
                if t is None or val is None:
                    continue
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                hours = (t - now).total_seconds() / 3600.0
                out[key].append((hours, v))
            elif isinstance(r, (list, tuple)) and len(r) >= 2:
                # [hours_from_now, value] or [iso, value]
                a, b = r[0], r[1]
                try:
                    if isinstance(a, (int, float)):
                        out[key].append((float(a), float(b)))
                    else:
                        t = _parse_iso(str(a))
                        if t is None:
                            continue
                        hours = (t - now).total_seconds() / 3600.0
                        out[key].append((hours, float(b)))
                except (TypeError, ValueError):
                    continue
        out[key].sort(key=lambda p: p[0])

    if isinstance(series, dict):
        _ingest("xray", series.get("xray") or series.get("xrays"))
        _ingest("kp", series.get("kp"))
        _ingest("f107", series.get("f107"))
    return out


def project_indices(
    *,
    xray: float,
    kp: float,
    f107: float,
    flare_letter: str,
    hours: float,
    series_n: Optional[Dict[str, List[Tuple[float, float]]]] = None,
) -> Tuple[float, float, float, List[str]]:
    """
    Project indices forward `hours`. Returns (xray, kp, f107, notes).
    """
    notes: List[str] = []
    h = max(0.0, float(hours))
    letter = (flare_letter or "A").upper()[:1]
    half = XRAY_HALF_LIFE_H.get(letter, 4.0)

    # --- X-ray: decay + optional log-space trend (capped) ---
    x_decay = _exp_toward(xray, QUIET_XRAY, h, half)
    x_proj = x_decay
    sn = series_n or {}
    x_series = sn.get("xray") or []
    if len(x_series) >= 3 and h <= 6.0:
        # trend in log10(flux)
        log_pts = [(t, math.log10(max(v, 1e-10))) for t, v in x_series if v > 0]
        slope = _linear_trend_per_hour(log_pts)
        if slope is not None:
            # only use mild slopes; flares don't extrapolate forever
            slope = _clamp(slope, -0.35, 0.15)  # dex per hour
            log_now = math.log10(max(xray, 1e-10))
            x_trend = 10 ** (log_now + slope * h)
            # blend: more weight to decay as horizon grows
            w_trend = 0.55 * math.exp(-h / 4.0)
            x_proj = (1.0 - w_trend) * x_decay + w_trend * x_trend
            notes.append(f"xray_trend:{slope:+.3f}dex/h")
    else:
        notes.append(f"xray_decay:t½={half}h")
    x_proj = _clamp(x_proj, QUIET_XRAY * 0.5, 1.0e-3)

    # --- Kp ---
    k_decay = _exp_toward(kp, QUIET_KP, h, KP_HALF_LIFE_H)
    k_proj = k_decay
    k_series = sn.get("kp") or []
    if len(k_series) >= 2 and h <= 12.0:
        slope_k = _linear_trend_per_hour(k_series)
        if slope_k is not None:
            slope_k = _clamp(slope_k, -0.8, 0.5)
            k_trend = kp + slope_k * h
            w = 0.4 * math.exp(-h / 6.0)
            k_proj = (1.0 - w) * k_decay + w * k_trend
            notes.append(f"kp_trend:{slope_k:+.2f}/h")
    else:
        notes.append(f"kp_decay:t½={KP_HALF_LIFE_H}h")
    k_proj = _clamp(k_proj, 0.0, 9.0)

    # --- F10.7 (slow) ---
    if h < 12.0:
        f_proj = float(f107)
        notes.append("f107:hold")
    else:
        # mild mean reversion toward mid-cycle-ish 100 (or keep elevated)
        target = 0.5 * (float(f107) + 100.0)
        f_proj = _exp_toward(float(f107), target, h, F107_MEAN_REVERT_TAU_H)
        notes.append("f107:slow_revert")
    f_proj = _clamp(f_proj, 50.0, 350.0)

    return x_proj, k_proj, f_proj, notes


def predict_horizons(
    weather: Any,
    *,
    horizons_h: Sequence[float] = DEFAULT_HORIZONS_H,
    series: Optional[Dict[str, Any]] = None,
    prop_minutes: Optional[float] = None,
    now: Optional[datetime] = None,
) -> PredictAssessment:
    """
    Build 1h/6h/24h (or custom) horizon forecasts from a weather snapshot.

    `series` optional: {"xray":[{time_tag,flux},...], "kp":[...], "f107":[...]}
    `prop_minutes` recorded for optional orbital forward-prop context (density
    not re-scored here — shell scores follow global solar projection).
    """
    w = _weather_dict(weather)
    t_now = now or _parse_iso(w.get("as_of") or w.get("fetched_at")) or _utc_now()

    letter = str(w.get("flare_letter") or "A")
    mag = float(w.get("flare_mag") or 0.0)
    if not w.get("flare_letter") and w.get("flare_class"):
        fc = str(w["flare_class"])
        letter = fc[:1] if fc else "A"
        try:
            mag = float(fc[1:]) if len(fc) > 1 else 0.0
        except ValueError:
            mag = 0.0

    xray = float(w.get("xray_flux") if w.get("xray_flux") is not None else QUIET_XRAY)
    f107 = float(w.get("f107") if w.get("f107") is not None else QUIET_F107)
    kp = float(w.get("kp") if w.get("kp") is not None else QUIET_KP)

    now_score, now_drivers = combine_global(
        flare_letter=letter,
        flare_mag=mag,
        f107=f107,
        kp=kp,
    )
    now_sev = severity_for_score(now_score, flare_letter=letter, kp=kp)

    sn = normalize_series(series, now=t_now)
    series_used = {k: len(v) for k, v in sn.items()}
    has_trend = any(n >= 2 for n in series_used.values())
    method = "decay+trend" if has_trend else "decay"

    forecasts: List[HorizonForecast] = []
    for h in horizons_h:
        hh = float(h)
        label = f"{int(hh)}h" if hh == int(hh) else f"{hh}h"
        x_p, k_p, f_p, notes = project_indices(
            xray=xray,
            kp=kp,
            f107=f107,
            flare_letter=letter,
            hours=hh,
            series_n=sn,
        )
        fl, fm, fclass = _flare_from_flux(x_p)
        score, drivers = combine_global(
            flare_letter=fl,
            flare_mag=fm,
            f107=f_p,
            kp=k_p,
        )
        sev = severity_for_score(score, flare_letter=fl, kp=k_p)
        at = _iso(t_now + timedelta(hours=hh))
        forecasts.append(
            HorizonForecast(
                horizon_h=hh,
                label=label,
                at=at,
                flare_class=fclass,
                flare_letter=fl,
                flare_mag=round(fm, 2),
                f107=round(f_p, 1),
                kp=round(k_p, 2),
                xray_flux=float(f"{x_p:.3e}"),
                global_score=score,
                severity=sev,
                drivers=list(drivers) + notes,
                trend_note="; ".join(notes),
            )
        )

    weather_now = {
        "flare_class": w.get("flare_class") or f"{letter}{mag:.1f}",
        "flare_letter": letter,
        "flare_mag": mag,
        "f107": f107,
        "kp": kp,
        "xray_flux": xray,
        "mode": w.get("mode"),
        "source": w.get("source"),
        "as_of": w.get("as_of") or _iso(t_now),
    }

    return PredictAssessment(
        as_of=_iso(t_now),
        now_score=now_score,
        now_severity=now_sev,
        weather_now=weather_now,
        horizons=forecasts,
        method=method,
        series_used=series_used,
        prop_minutes=float(prop_minutes) if prop_minutes is not None else None,
    )


def short_horizon_line(pred: PredictAssessment) -> str:
    """One-line CLI / badge summary."""
    parts = [f"now={pred.now_score:.0f}/{pred.now_severity}"]
    for h in pred.horizons:
        parts.append(f"{h.label}={h.global_score:.0f}/{h.severity}")
    return " · ".join(parts)
