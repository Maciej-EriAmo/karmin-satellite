"""
Capacity test — usable architecture budget (50k) and optional ceiling probe.

Architecture:
  ARCH_USABLE_SATS  = 50_000   ← recommended operating load (this test)
  ARCH_CEILING_SATS = 100_000  ← hard product max

Runs synthetic unique sats (no network). Writes out/capacity_report.json.

  python tests/test_capacity.py
  python -m unittest tests.test_capacity -v

Env:
  CYNOBER_CAPACITY_QUICK=1  → only 1k + 10k (CI-friendly)
  CYNOBER_CAPACITY_CEILING=1 → also attempt 100k (slow / heavy RAM)
"""
from __future__ import annotations

import json
import os
import sys
import time
import tracemalloc
import unittest
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "out" / "capacity_report.json"


def _measure(n: int, *, prop: str = "sgp4", hot_only: bool = True) -> Dict[str, Any]:
    from engine.build import build_capacity_map
    from engine.export_2d import export_report_payload
    from transform.sphere import export_sphere_data

    tracemalloc.start()
    t0 = time.perf_counter()
    store, amap, use, src = build_capacity_map(
        n, hot_only=hot_only, prop=prop, grid=5.0, backend="python"
    )
    elapsed = time.perf_counter() - t0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    summ = amap.summary()
    cons = amap.density_cell_consistency()
    snap = amap.snapshot()
    t_export0 = time.perf_counter()
    payload = export_report_payload(
        amap, src=src, using=len(use), elapsed_s=elapsed
    )
    slim = {k: v for k, v in payload.items() if k != "heatmap_png_b64"}
    export_bytes = len(json.dumps(slim, ensure_ascii=False).encode("utf-8"))
    export_ms = (time.perf_counter() - t_export0) * 1000.0

    t_sph0 = time.perf_counter()
    sphere = export_sphere_data(amap)
    sphere_ms = (time.perf_counter() - t_sph0) * 1000.0
    sphere_n = len(sphere.get("cells") or [])
    sphere_bytes = len(
        json.dumps(
            {"cells": sphere_n, "meta": sphere.get("meta")},
            ensure_ascii=False,
        ).encode("utf-8")
    )

    row = {
        "n": n,
        "src": src,
        "prop": prop,
        "hot_only": hot_only,
        "using": n,
        "elapsed_s": round(elapsed, 4),
        "prop_ms": summ.get("prop_ms"),
        "sats": summ.get("sats"),
        "cells": summ.get("cells"),
        "hot_cells": summ.get("hot_cells"),
        "prop_errors": summ.get("prop_errors"),
        "prop_error_rate": summ.get("prop_error_rate"),
        "consistency_ok": cons.get("ok"),
        "peak_tracemalloc_mb": round(peak / (1024 * 1024), 3),
        "export_json_bytes": export_bytes,
        "export_ms": round(export_ms, 2),
        "sphere_cells": sphere_n,
        "sphere_ms": round(sphere_ms, 2),
        "sphere_meta_bytes": sphere_bytes,
    }
    # release refs for GC friendliness between levels
    del store, amap, use, payload, snap, sphere
    return row


def run_capacity_suite() -> dict:
    from engine.constants import ARCH_CEILING_SATS, ARCH_USABLE_SATS

    quick = os.environ.get("CYNOBER_CAPACITY_QUICK", "").strip() in (
        "1",
        "true",
        "yes",
    )
    do_ceiling = os.environ.get("CYNOBER_CAPACITY_CEILING", "").strip() in (
        "1",
        "true",
        "yes",
    )

    if quick:
        levels = [1_000, 10_000]
    else:
        levels = [1_000, 10_000, ARCH_USABLE_SATS]  # 50k usable
        if do_ceiling:
            levels.append(ARCH_CEILING_SATS)

    rows: List[dict] = []
    for n in levels:
        print(f"[capacity] measuring n={n} …", flush=True)
        row = _measure(n, prop="sgp4", hot_only=True)
        print(
            f"  elapsed={row['elapsed_s']}s prop_ms={row['prop_ms']} "
            f"cells={row['cells']} peak_mb={row['peak_tracemalloc_mb']} "
            f"err={row['prop_errors']}",
            flush=True,
        )
        rows.append(row)

    usable_row = next((r for r in rows if r["n"] == ARCH_USABLE_SATS), None)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "architecture": {
            "ARCH_USABLE_SATS": ARCH_USABLE_SATS,
            "ARCH_CEILING_SATS": ARCH_CEILING_SATS,
            "note": "usable = recommended operating budget; ceiling = hard max",
        },
        "quick": quick,
        "ceiling_probed": do_ceiling,
        "rows": rows,
        "verdict_usable": None,
    }

    if usable_row is not None:
        # Soft acceptance for usable 50k (not lab perfection)
        ok = (
            usable_row["sats"] == ARCH_USABLE_SATS
            and usable_row["prop_errors"] == 0
            and usable_row["consistency_ok"]
            and usable_row["elapsed_s"] < 120.0  # generous wall clock
            and usable_row["peak_tracemalloc_mb"] < 4096  # 4 GB tracemalloc peak
        )
        report["verdict_usable"] = {
            "ok": ok,
            "n": ARCH_USABLE_SATS,
            "elapsed_s": usable_row["elapsed_s"],
            "peak_tracemalloc_mb": usable_row["peak_tracemalloc_mb"],
            "prop_ms": usable_row["prop_ms"],
            "cells": usable_row["cells"],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[capacity] wrote {OUT}", flush=True)
    # Optional: refresh tracked baseline when full ceiling suite ran
    if do_ceiling and not quick:
        bas = ROOT / "docs" / "capacity_baseline.json"
        bas_payload = dict(report)
        bas_payload["document"] = "capacity_baseline"
        bas_payload["see"] = "docs/ARCHITECTURE_LIMITS.md"
        bas.write_text(json.dumps(bas_payload, indent=2), encoding="utf-8")
        print(f"[capacity] updated {bas}", flush=True)
    return report


class TestCapacity(unittest.TestCase):
    def test_usable_architecture_capacity(self):
        """Full usable 50k unless CYNOBER_CAPACITY_QUICK=1."""
        report = run_capacity_suite()
        self.assertTrue(OUT.is_file())
        self.assertGreaterEqual(len(report["rows"]), 1)
        for row in report["rows"]:
            self.assertEqual(row["sats"], row["n"], row)
            self.assertEqual(row["prop_errors"], 0, row)
            self.assertTrue(row["consistency_ok"], row)

        # When not quick, require usable tier present and green
        if not report.get("quick"):
            v = report.get("verdict_usable")
            self.assertIsNotNone(v)
            self.assertTrue(v["ok"], v)


if __name__ == "__main__":
    rep = run_capacity_suite()
    print(json.dumps(rep.get("verdict_usable") or rep["rows"][-1], indent=2))
    # non-zero exit if usable measured and failed
    v = rep.get("verdict_usable")
    if v is not None and not v.get("ok"):
        raise SystemExit(1)
