"""Faza 0 bench: offline limits → out/bench.json."""
from __future__ import annotations

import json
import sys
import time
import tracemalloc
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "out" / "bench.json"


def run_bench(limits=(12, 40, 120)) -> dict:
    from engine.starlink_atoms import build_map, export_report_payload

    rows = []
    for limit in limits:
        tracemalloc.start()
        t0 = time.perf_counter()
        store, amap, use, src = build_map(
            limit=limit,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache=str(ROOT / "out" / "starlink_tle_cache.txt"),
        )
        elapsed = time.perf_counter() - t0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        summ = amap.summary()
        cons = amap.density_cell_consistency()
        payload = export_report_payload(amap, src=src, using=len(use), elapsed_s=elapsed)
        # strip huge fields for size estimate of API-ish payload
        slim = {k: v for k, v in payload.items() if k != "heatmap_png_b64"}
        export_bytes = len(json.dumps(slim, ensure_ascii=False).encode("utf-8"))
        rows.append(
            {
                "limit": limit,
                "using": len(use),
                "src": src,
                "elapsed_s": round(elapsed, 4),
                "prop_ms": summ.get("prop_ms"),
                "sats": summ.get("sats"),
                "cells": summ.get("cells"),
                "hot_cells": summ.get("hot_cells"),
                "prop_errors": summ.get("prop_errors"),
                "prop_error_rate": summ.get("prop_error_rate"),
                "version": summ.get("version"),
                "consistency_ok": cons.get("ok"),
                "peak_tracemalloc_mb": round(peak / (1024 * 1024), 3),
                "export_json_bytes": export_bytes,
            }
        )
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": "python",
        "mode": "offline-demo",
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


class TestBench(unittest.TestCase):
    def test_bench_offline(self):
        report = run_bench()
        self.assertTrue(OUT.is_file())
        self.assertGreaterEqual(len(report["rows"]), 1)
        for row in report["rows"]:
            self.assertTrue(row["consistency_ok"], row)
            self.assertEqual(row["prop_errors"], 0)
            self.assertLess(row["elapsed_s"], 30.0)


if __name__ == "__main__":
    rep = run_bench()
    print(json.dumps(rep, indent=2))
