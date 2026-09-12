#!/usr/bin/env python3
"""
H4 — HazardReport (JSON + Markdown) for group solar context.

Research document assembled from engine.solar weather / hazard / optional predict.
Attachable to snapshot payloads under key ``solar``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DEFAULT_DISCLAIMER = (
    "Public NOAA SWPC indices + geometric LEO density only. "
    "Research / education / hobby — not mission operations or radiation certification."
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if isinstance(obj, dict):
        return dict(obj)
    return {}


@dataclass
class HazardReport:
    """Portable group hazard document (research proxy)."""

    as_of: str
    title: str = "Karmin Satellite — Solar Hazard Report"
    weather: dict = field(default_factory=dict)
    hazard: dict = field(default_factory=dict)
    predict: Optional[dict] = None
    map: dict = field(default_factory=dict)
    groups: List[dict] = field(default_factory=list)
    badge: str = ""
    horizon_line: str = ""
    disclaimer: str = DEFAULT_DISCLAIMER
    version: str = "hazard-report-v1"

    def as_dict(self) -> dict:
        d = {
            "as_of": self.as_of,
            "title": self.title,
            "weather": self.weather,
            "hazard": self.hazard,
            "map": self.map,
            "groups": list(self.groups),
            "badge": self.badge,
            "horizon_line": self.horizon_line,
            "disclaimer": self.disclaimer,
            "version": self.version,
        }
        if self.predict is not None:
            d["predict"] = self.predict
        return d

    def as_markdown(self) -> str:
        """Human-readable MD report."""
        w = self.weather or {}
        h = self.hazard or {}
        lines: List[str] = [
            f"# {self.title}",
            "",
            f"**as_of:** {self.as_of}  ",
            f"**version:** `{self.version}`  ",
            f"**badge:** {self.badge or '—'}  ",
            "",
            "## Disclaimer",
            "",
            self.disclaimer,
            "",
            "## Weather (public NOAA SWPC)",
            "",
            "| Index | Value |",
            "|-------|-------|",
            f"| Flare | {w.get('flare_class') or w.get('flare_letter') or '—'} |",
            f"| F10.7 | {w.get('f107') if w.get('f107') is not None else '—'} |",
            f"| Kp | {w.get('kp') if w.get('kp') is not None else '—'} |",
            f"| X-ray flux | {w.get('xray_flux') if w.get('xray_flux') is not None else '—'} |",
            f"| Mode | {w.get('mode') or '—'} |",
            f"| Source | {w.get('source') or '—'} |",
            "",
            "## Global hazard",
            "",
            f"- **score:** {h.get('global_score', '—')}",
            f"- **severity:** {h.get('severity', '—')}",
            f"- **drivers:** {', '.join(h.get('drivers') or []) or '—'}",
            "",
            "## Groups",
            "",
        ]
        if not self.groups:
            lines.append("_no groups_")
        else:
            lines.append("| Group | Kind | n | share | score | severity |")
            lines.append("|-------|------|---|-------|-------|----------|")
            for g in self.groups:
                share = g.get("share")
                share_s = f"{float(share) * 100:.0f}%" if share is not None else "—"
                lines.append(
                    f"| `{g.get('group_id', '—')}` | {g.get('kind', '—')} | "
                    f"{g.get('n_sats', '—')} | {share_s} | "
                    f"{g.get('score', '—')} | {g.get('severity', '—')} |"
                )
        lines.append("")

        if self.predict:
            p = self.predict
            lines.extend(
                [
                    "## Horizons (H3)",
                    "",
                    f"**now:** {p.get('now_score', '—')} / {p.get('now_severity', '—')}  ",
                    f"**method:** {p.get('method', '—')}  ",
                    f"**line:** {self.horizon_line or p.get('badge') or '—'}  ",
                    "",
                    "| Horizon | Flare | Kp | F10.7 | Score | Severity |",
                    "|---------|-------|----|-------|-------|----------|",
                ]
            )
            for hz in p.get("horizons") or []:
                lines.append(
                    f"| {hz.get('label', '—')} | {hz.get('flare_class', '—')} | "
                    f"{hz.get('kp', '—')} | {hz.get('f107', '—')} | "
                    f"{hz.get('global_score', '—')} | {hz.get('severity', '—')} |"
                )
            lines.append("")

        m = self.map or {}
        if m:
            lines.extend(
                [
                    "## Map context",
                    "",
                    f"- **sats:** {m.get('sats', '—')}",
                    f"- **cells / hot:** {m.get('cells', '—')} / {m.get('hot_cells', '—')}",
                    f"- **src:** {m.get('src', '—')}",
                    f"- **shells:** {m.get('shells', '—')}",
                    "",
                ]
            )

        lines.extend(["---", f"_generated {_utc_iso()}_", ""])
        return "\n".join(lines)

    def solar_meta(self) -> dict:
        """Compact block for snapshot payload ``solar`` key."""
        out: Dict[str, Any] = {
            "report_version": self.version,
            "as_of": self.as_of,
            "weather": self.weather,
            "hazard": {
                "global_score": (self.hazard or {}).get("global_score"),
                "severity": (self.hazard or {}).get("severity"),
                "drivers": (self.hazard or {}).get("drivers"),
                "badge": self.badge,
                "groups": self.groups,
            },
            "disclaimer": self.disclaimer,
        }
        if self.predict is not None:
            # slim predict for disk
            p = self.predict
            out["predict"] = {
                "now_score": p.get("now_score"),
                "now_severity": p.get("now_severity"),
                "method": p.get("method"),
                "horizon_line": self.horizon_line,
                "horizons": [
                    {
                        "label": h.get("label"),
                        "global_score": h.get("global_score"),
                        "severity": h.get("severity"),
                        "flare_class": h.get("flare_class"),
                        "kp": h.get("kp"),
                        "f107": h.get("f107"),
                    }
                    for h in (p.get("horizons") or [])
                ],
            }
        return out


def build_hazard_report(
    weather: Any,
    assessment: Any,
    *,
    predict: Any = None,
    map_summary: Optional[dict] = None,
    src: str = "",
    badge: str = "",
) -> HazardReport:
    """Assemble report from weather snapshot + hazard assessment (+ optional predict)."""
    w = _as_dict(weather)
    # weather block may already be nested in assessment
    if not w and hasattr(assessment, "weather"):
        w = dict(assessment.weather or {})
    h = _as_dict(assessment)
    # keep hazard dict without huge weather duplicate if present
    haz_view = {
        "as_of": h.get("as_of"),
        "global_score": h.get("global_score"),
        "severity": h.get("severity"),
        "drivers": h.get("drivers") or [],
        "version": h.get("version"),
    }
    groups = list(h.get("groups") or [])
    if not groups and hasattr(assessment, "groups"):
        groups = [
            g.as_dict() if hasattr(g, "as_dict") else dict(g)
            for g in (assessment.groups or [])
        ]

    pred = _as_dict(predict) if predict is not None else None
    horizon_line = ""
    if pred:
        from engine.solar.predict import short_horizon_line
        from engine.solar.predict import PredictAssessment

        if isinstance(predict, PredictAssessment):
            horizon_line = short_horizon_line(predict)
        else:
            parts = [f"now={pred.get('now_score')}/{pred.get('now_severity')}"]
            for hz in pred.get("horizons") or []:
                parts.append(
                    f"{hz.get('label')}={hz.get('global_score')}/{hz.get('severity')}"
                )
            horizon_line = " · ".join(parts)

    if not badge:
        from engine.solar.hazard import short_badge
        from engine.solar.hazard import HazardAssessment

        if isinstance(assessment, HazardAssessment):
            badge = short_badge(assessment)
        else:
            badge = (
                f"{(w.get('flare_class') or '?')} · "
                f"stress={h.get('global_score', '—')} · {h.get('severity', '')}"
            )

    msum = dict(map_summary or {})
    map_block = {
        "sats": msum.get("sats"),
        "cells": msum.get("cells"),
        "hot_cells": msum.get("hot_cells"),
        "shells": msum.get("shells"),
        "src": src or msum.get("src") or "",
        "prop": msum.get("prop"),
        "version": msum.get("version"),
    }

    weather_view = {
        "flare_class": w.get("flare_class"),
        "flare_letter": w.get("flare_letter"),
        "flare_mag": w.get("flare_mag"),
        "f107": w.get("f107"),
        "kp": w.get("kp"),
        "xray_flux": w.get("xray_flux"),
        "mode": w.get("mode"),
        "source": w.get("source"),
        "as_of": w.get("as_of") or w.get("fetched_at"),
    }

    return HazardReport(
        as_of=str(
            h.get("as_of")
            or w.get("as_of")
            or w.get("fetched_at")
            or _utc_iso()
        ),
        weather=weather_view,
        hazard=haz_view,
        predict=pred,
        map=map_block,
        groups=groups,
        badge=badge,
        horizon_line=horizon_line,
        disclaimer=str(
            h.get("disclaimer") or w.get("disclaimer") or DEFAULT_DISCLAIMER
        ),
    )


def collect_solar_for_map(
    amap: Any,
    *,
    offline: bool = False,
    force: bool = False,
    with_predict: bool = True,
    src: str = "",
) -> HazardReport:
    """One-shot: fetch weather, assess map, optional predict → report."""
    from engine.solar.hazard import assess_from_amap, short_badge
    from engine.solar.predict import predict_horizons
    from engine.solar.weather import get_space_weather_bundle

    wx, series = get_space_weather_bundle(force=force, offline=offline)
    assessment = assess_from_amap(amap, wx)
    pred = None
    if with_predict:
        pred = predict_horizons(wx, series=series)
    summary = amap.summary() if amap is not None and hasattr(amap, "summary") else {}
    return build_hazard_report(
        wx,
        assessment,
        predict=pred,
        map_summary=summary,
        src=src,
        badge=short_badge(assessment),
    )
