"""
Karmin Satellite — 50k SLA contract (design target = ARCH_USABLE_SATS).

Canonical numbers live here + docs/SLA_50K.md.
Baseline measurements: docs/capacity_baseline.json · docs/ARCHITECTURE_LIMITS.md.

Hard limits = merge / acceptance blockers.
Target limits = product design budget (what we design UX against).
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

# ── Scale anchors (mirror engine.constants) ─────────────────────────────────
SLA_USABLE_SATS = 50_000
SLA_CEILING_SATS = 100_000
SLA_DEFAULT_SAMPLE = 400  # CLI dev sample — NOT product max

# ── Cold full pipeline @ usable (ingest + refresh + export meta + sphere) ───
# Measured ~5.7 s / ~148 MB tracemalloc (2026-08-11).
SLA_E2E_USABLE_S_TARGET = 10.0
SLA_E2E_USABLE_S_HARD = 30.0

SLA_PROP_MS_USABLE_TARGET = 5_000.0
SLA_PROP_MS_USABLE_HARD = 15_000.0

SLA_PEAK_MB_USABLE_TARGET = 256.0  # tracemalloc peak design
SLA_PEAK_MB_USABLE_HARD = 1024.0  # merge-block

SLA_EXPORT_JSON_BYTES_TARGET = 200_000  # ~200 KB density JSON
SLA_EXPORT_JSON_BYTES_HARD = 500_000  # 500 KB acceptance

SLA_HOT_CELLS_SYNTHETIC_MAX = 5_000  # synthetic demo saturates ~2k @5°
SLA_HOT_CELLS_P95_UI = 8_000  # real Starlink UI budget (cells, not sats)

# ── Live feed (full SGP4 rebin) ─────────────────────────────────────────────
SLA_LIVE_INTERVAL_COMFORT_S = 900.0  # 15 min — recommended @50k
SLA_LIVE_INTERVAL_MIN_S = 60.0  # below → warn (jitter / contention)
SLA_LIVE_INTERVAL_FORBIDDEN_S = 5.0  # full SGP4 @ usable is NOT supported

# ── Host RAM planning (free headroom, not process RSS alone) ────────────────
SLA_RAM_HEADROOM_USABLE_MB = 512
SLA_RAM_HEADROOM_CEILING_MB = 1024

# ── API shape rules ─────────────────────────────────────────────────────────
# HTTP studio responses scale with cells, never O(N sats) position dumps.
SLA_API_INCLUDE_FULL_SAT_POSITIONS = False
SLA_FORBIDDEN_API_KEYS = frozenset(
    {
        "sat_positions",
        "positions",
        "all_sats",
        "sats_full",
        "tle_all",
    }
)

SLA_DOC = "docs/SLA_50K.md"
SLA_LIMITS_DOC = "docs/ARCHITECTURE_LIMITS.md"
SLA_BASELINE = "docs/capacity_baseline.json"
SLA_VERSION = "1.0.0"


def sla_public_dict() -> Dict[str, Any]:
    """Machine-readable SLA for /api/sla and tooling (EN keys + PL notes)."""
    return {
        "version": SLA_VERSION,
        "design_sats": SLA_USABLE_SATS,
        "ceiling_sats": SLA_CEILING_SATS,
        "default_sample": SLA_DEFAULT_SAMPLE,
        "cold_e2e_usable_s": {
            "target": SLA_E2E_USABLE_S_TARGET,
            "hard": SLA_E2E_USABLE_S_HARD,
        },
        "prop_ms_usable": {
            "target": SLA_PROP_MS_USABLE_TARGET,
            "hard": SLA_PROP_MS_USABLE_HARD,
        },
        "peak_tracemalloc_mb_usable": {
            "target": SLA_PEAK_MB_USABLE_TARGET,
            "hard": SLA_PEAK_MB_USABLE_HARD,
        },
        "export_json_bytes_usable": {
            "target": SLA_EXPORT_JSON_BYTES_TARGET,
            "hard": SLA_EXPORT_JSON_BYTES_HARD,
        },
        "hot_cells": {
            "synthetic_max": SLA_HOT_CELLS_SYNTHETIC_MAX,
            "p95_ui": SLA_HOT_CELLS_P95_UI,
        },
        "live_interval_s": {
            "comfort": SLA_LIVE_INTERVAL_COMFORT_S,
            "min_warn": SLA_LIVE_INTERVAL_MIN_S,
            "forbidden_full_sgp4": SLA_LIVE_INTERVAL_FORBIDDEN_S,
        },
        "ram_headroom_mb": {
            "usable": SLA_RAM_HEADROOM_USABLE_MB,
            "ceiling": SLA_RAM_HEADROOM_CEILING_MB,
        },
        "api": {
            "include_full_sat_positions": SLA_API_INCLUDE_FULL_SAT_POSITIONS,
            "forbidden_keys": sorted(SLA_FORBIDDEN_API_KEYS),
            "scale_with": "hot_cells",
            "note_en": "JSON payloads must scale with cells (~2–8k), not N sats.",
            "note_pl": "Payloady JSON skalują się z komórkami (~2–8k), nie z N satów.",
        },
        "docs": {
            "sla": SLA_DOC,
            "limits": SLA_LIMITS_DOC,
            "baseline": SLA_BASELINE,
        },
        "plane": {
            "prop": "sgp4",
            "hot_only": True,
            "grid_deg": 5.0,
            "backend": "python",
        },
    }


def evaluate_live_interval(interval_sec: float) -> Dict[str, Any]:
    """Classify feeder interval vs 50k SLA (does not hard-fail demos)."""
    iv = float(interval_sec)
    if iv < SLA_LIVE_INTERVAL_FORBIDDEN_S:
        level = "forbidden"
        ok = False
        msg_en = (
            f"interval {iv}s < {SLA_LIVE_INTERVAL_FORBIDDEN_S}s: "
            "full SGP4 rebin at usable scale is not supported."
        )
        msg_pl = (
            f"interval {iv}s < {SLA_LIVE_INTERVAL_FORBIDDEN_S}s: "
            "pełny SGP4 @ usable nie jest wspierany."
        )
    elif iv < SLA_LIVE_INTERVAL_MIN_S:
        level = "warn"
        ok = True
        msg_en = (
            f"interval {iv}s < comfort min {SLA_LIVE_INTERVAL_MIN_S}s — "
            "expect UI jitter / CPU contention at 50k."
        )
        msg_pl = (
            f"interval {iv}s < min komfortu {SLA_LIVE_INTERVAL_MIN_S}s — "
            "przy 50k spodziewaj się jitteru UI / CPU."
        )
    elif iv < SLA_LIVE_INTERVAL_COMFORT_S:
        level = "ok_tight"
        ok = True
        msg_en = (
            f"interval {iv}s is OK but below comfort "
            f"({SLA_LIVE_INTERVAL_COMFORT_S}s / 15 min recommended @50k)."
        )
        msg_pl = (
            f"interval {iv}s OK, ale poniżej komfortu "
            f"({SLA_LIVE_INTERVAL_COMFORT_S}s / 15 min zalecane @50k)."
        )
    else:
        level = "ok"
        ok = True
        msg_en = f"interval {iv}s meets 50k comfort SLA."
        msg_pl = f"interval {iv}s spełnia komfortowe SLA 50k."
    return {
        "ok": ok,
        "level": level,
        "interval_sec": iv,
        "message_en": msg_en,
        "message_pl": msg_pl,
    }


def evaluate_capacity_row(
    row: Mapping[str, Any],
    *,
    n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Score one capacity measurement row against hard SLA (usable tier).

    For n != usable, only structural checks (errors/consistency) apply as hard;
    timing budgets are evaluated when n == usable (or n is None and row n matches).
    """
    nn = int(n if n is not None else row.get("n") or 0)
    failures: List[str] = []
    warnings: List[str] = []

    if row.get("prop_errors", 0) not in (0, 0.0, None):
        failures.append(f"prop_errors={row.get('prop_errors')}")
    if row.get("consistency_ok") is False:
        failures.append("consistency_ok=false")
    if row.get("sats") is not None and row.get("n") is not None:
        if int(row["sats"]) != int(row["n"]):
            failures.append(f"sats!=n ({row['sats']}!={row['n']})")

    is_usable = nn == SLA_USABLE_SATS
    elapsed = float(row.get("elapsed_s") or 0.0)
    peak = float(row.get("peak_tracemalloc_mb") or 0.0)
    prop_ms = row.get("prop_ms")
    export_b = row.get("export_json_bytes")
    cells = row.get("cells")

    if is_usable:
        if elapsed >= SLA_E2E_USABLE_S_HARD:
            failures.append(
                f"elapsed_s={elapsed} >= hard {SLA_E2E_USABLE_S_HARD}"
            )
        elif elapsed >= SLA_E2E_USABLE_S_TARGET:
            warnings.append(
                f"elapsed_s={elapsed} >= target {SLA_E2E_USABLE_S_TARGET}"
            )

        if peak >= SLA_PEAK_MB_USABLE_HARD:
            failures.append(
                f"peak_mb={peak} >= hard {SLA_PEAK_MB_USABLE_HARD}"
            )
        elif peak >= SLA_PEAK_MB_USABLE_TARGET:
            warnings.append(
                f"peak_mb={peak} >= target {SLA_PEAK_MB_USABLE_TARGET}"
            )

        if prop_ms is not None:
            pm = float(prop_ms)
            if pm >= SLA_PROP_MS_USABLE_HARD:
                failures.append(
                    f"prop_ms={pm} >= hard {SLA_PROP_MS_USABLE_HARD}"
                )
            elif pm >= SLA_PROP_MS_USABLE_TARGET:
                warnings.append(
                    f"prop_ms={pm} >= target {SLA_PROP_MS_USABLE_TARGET}"
                )

        if export_b is not None:
            eb = int(export_b)
            if eb >= SLA_EXPORT_JSON_BYTES_HARD:
                failures.append(
                    f"export_json_bytes={eb} >= hard {SLA_EXPORT_JSON_BYTES_HARD}"
                )
            elif eb >= SLA_EXPORT_JSON_BYTES_TARGET:
                warnings.append(
                    f"export_json_bytes={eb} >= target {SLA_EXPORT_JSON_BYTES_TARGET}"
                )

        if cells is not None and int(cells) > SLA_HOT_CELLS_SYNTHETIC_MAX:
            failures.append(
                f"cells={cells} > synthetic max {SLA_HOT_CELLS_SYNTHETIC_MAX}"
            )

    return {
        "ok": len(failures) == 0,
        "n": nn,
        "is_usable_tier": is_usable,
        "failures": failures,
        "warnings": warnings,
        "elapsed_s": elapsed,
        "peak_tracemalloc_mb": peak,
    }


def assert_api_payload_shape(
    payload: Mapping[str, Any],
    *,
    path: str = "payload",
) -> List[str]:
    """
    Return list of SLA violations for an API JSON object.
    Does not raise — caller decides.
    """
    issues: List[str] = []
    if not isinstance(payload, Mapping):
        return [f"{path}: not a mapping"]

    for key in SLA_FORBIDDEN_API_KEYS:
        if key in payload:
            issues.append(f"{path}: forbidden key {key!r} (O(N) sat dump)")

    # Nested "data" common in Studio responses
    data = payload.get("data")
    if isinstance(data, Mapping):
        for key in SLA_FORBIDDEN_API_KEYS:
            if key in data:
                issues.append(
                    f"{path}.data: forbidden key {key!r} (O(N) sat dump)"
                )
        # density must be cell-list shaped when present
        dens = data.get("density")
        if dens is not None and not isinstance(dens, list):
            issues.append(f"{path}.data.density: expected list of cells")
        elif isinstance(dens, list) and dens:
            sample = dens[0]
            if isinstance(sample, Mapping) and "norad" in sample:
                issues.append(
                    f"{path}.data.density: looks like per-sat rows (has norad)"
                )
    return issues
