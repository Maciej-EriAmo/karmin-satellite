"""Unit tests for public NOAA space weather + hazard (no network required)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "substrate"))
sys.path.insert(0, str(ROOT))


class TestFlareClass(unittest.TestCase):
    def test_classes(self):
        from engine.solar import flare_class_from_flux, format_flare_class

        letter, mag = flare_class_from_flux(3.2e-6)
        self.assertEqual(letter, "C")
        self.assertAlmostEqual(mag, 3.2, places=1)
        self.assertEqual(format_flare_class(letter, mag), "C3.2")

        letter, mag = flare_class_from_flux(2.0e-5)
        self.assertEqual(letter, "M")

        letter, mag = flare_class_from_flux(1.5e-4)
        self.assertEqual(letter, "X")

        letter, mag = flare_class_from_flux(5e-8)
        self.assertEqual(letter, "A")


class TestParseBundle(unittest.TestCase):
    def test_parse_live_shape(self):
        from engine.solar import parse_swpc_bundle

        f107 = [
            {
                "time_tag": "2026-08-01T12:00:00",
                "flux": 142.0,
                "reporting_schedule": "Morning",
            }
        ]
        xray = [
            {
                "time_tag": "2026-08-12T10:00:00Z",
                "flux": 4.0e-6,
                "energy": "0.1-0.8nm",
            }
        ]
        kp = [{"time_tag": "2026-08-12T09:00:00", "Kp": 3.67}]
        snap = parse_swpc_bundle(
            f107_rows=f107, xray_rows=xray, kp_rows=kp, mode="live"
        )
        self.assertEqual(snap.mode, "live")
        self.assertEqual(snap.f107, 142.0)
        self.assertEqual(snap.flare_letter, "C")
        self.assertAlmostEqual(snap.kp, 3.67)
        self.assertTrue(snap.flare_class.startswith("C"))
        d = snap.as_dict()
        self.assertIn("disclaimer", d)


class TestStubAndOffline(unittest.TestCase):
    def test_quiet_stub(self):
        from engine.solar import quiet_stub

        s = quiet_stub(reason="test")
        self.assertEqual(s.mode, "stub")
        self.assertEqual(s.source, "stub-quiet-sun")
        self.assertIn("test", s.message)

    def test_client_offline_no_cache(self):
        from engine.solar import SpaceWeatherClient

        client = SpaceWeatherClient(
            cache_path=ROOT / "out" / "_test_wx_missing.json",
            allow_network=False,
        )
        # ensure missing
        if client.cache_path.is_file():
            client.cache_path.unlink()
        snap = client.fetch()
        self.assertEqual(snap.mode, "stub")


class TestHazard(unittest.TestCase):
    def test_calm_info(self):
        from engine.solar import assess_hazard

        weather = {
            "as_of": "2026-08-12T00:00:00Z",
            "flare_letter": "B",
            "flare_mag": 1.0,
            "flare_class": "B1.0",
            "f107": 75.0,
            "kp": 1.5,
            "mode": "stub",
            "source": "test",
        }
        h = assess_hazard(
            weather, shells={"shell:53": 40, "shell:70": 10}, total_sats=50
        )
        self.assertEqual(h.severity, "INFO")
        self.assertLess(h.global_score, 55)
        self.assertEqual(h.groups[0].kind, "constellation")
        shells = [g for g in h.groups if g.kind == "shell"]
        self.assertEqual(len(shells), 2)
        # high-inc shell score >= mid
        s70 = next(g for g in shells if g.group_id == "shell:70")
        s53 = next(g for g in shells if g.group_id == "shell:53")
        self.assertGreaterEqual(s70.score, s53.score)

    def test_m_class_watch(self):
        from engine.solar import assess_hazard, short_badge

        weather = {
            "as_of": "t",
            "flare_letter": "M",
            "flare_mag": 2.0,
            "flare_class": "M2.0",
            "f107": 160.0,
            "kp": 5.0,
            "mode": "live",
            "source": "noaa-swpc",
        }
        h = assess_hazard(weather, shells={"shell:53": 100}, total_sats=100)
        self.assertIn(h.severity, ("WATCH", "WARNING"))
        badge = short_badge(h)
        self.assertIn("M2", badge)
        self.assertIn("stress=", badge)

    def test_exposure_overlay(self):
        from engine.solar import assess_hazard, build_overlay, exposure_cells

        dens = [
            {"ilat": 10, "ilon": 20, "count": 1},
            {"ilat": 11, "ilon": 21, "count": 10},
        ]
        cells = exposure_cells(dens, base_score=50.0)
        self.assertEqual(len(cells), 2)
        self.assertGreater(cells[1]["exposure"], cells[0]["exposure"])
        self.assertLessEqual(cells[1]["exposure"], 50.0)

        weather = {
            "as_of": "t",
            "flare_letter": "C",
            "flare_mag": 2.0,
            "flare_class": "C2.0",
            "f107": 120.0,
            "kp": 3.0,
            "mode": "stub",
            "source": "test",
        }
        h = assess_hazard(weather, shells={"shell:53": 40}, total_sats=40)
        ov = build_overlay(h, dens, shell="all")
        self.assertIn("cells", ov)
        self.assertEqual(ov["n_cells"], 2)
        self.assertGreater(ov["max_exposure"], 0)


class TestPredictH3(unittest.TestCase):
    def test_calm_decay_horizons(self):
        from engine.solar import predict_horizons, short_horizon_line

        weather = {
            "as_of": "2026-08-12T12:00:00+00:00",
            "flare_letter": "B",
            "flare_mag": 1.0,
            "flare_class": "B1.0",
            "f107": 75.0,
            "kp": 1.5,
            "xray_flux": 1.5e-7,
            "mode": "stub",
            "source": "test",
        }
        p = predict_horizons(weather)
        self.assertEqual(len(p.horizons), 3)
        labels = [h.label for h in p.horizons]
        self.assertEqual(labels, ["1h", "6h", "24h"])
        self.assertEqual(p.method, "decay")
        # calm stays calm / INFO-ish
        for h in p.horizons:
            self.assertLess(h.global_score, 55)
            self.assertIn(h.severity, ("INFO", "WATCH"))
        line = short_horizon_line(p)
        self.assertIn("1h=", line)
        self.assertIn("24h=", line)
        d = p.as_dict()
        self.assertEqual(d["version"], "predict-v1")
        self.assertIn("disclaimer", d)

    def test_elevated_relaxes_over_time(self):
        from engine.solar import predict_horizons

        weather = {
            "as_of": "2026-08-12T12:00:00+00:00",
            "flare_letter": "M",
            "flare_mag": 3.0,
            "flare_class": "M3.0",
            "f107": 180.0,
            "kp": 6.0,
            "xray_flux": 3.0e-5,
            "mode": "live",
            "source": "test",
        }
        p = predict_horizons(weather)
        h1 = p.horizons[0].global_score
        h24 = p.horizons[2].global_score
        # storm component should ease by 24h under pure decay
        self.assertGreater(p.now_score, h24)
        self.assertGreaterEqual(h1, h24 - 1.0)

    def test_series_enables_trend_method(self):
        from engine.solar import predict_horizons

        weather = {
            "as_of": "2026-08-12T12:00:00+00:00",
            "flare_letter": "C",
            "flare_mag": 2.0,
            "flare_class": "C2.0",
            "f107": 120.0,
            "kp": 3.0,
            "xray_flux": 2.0e-6,
            "mode": "live",
            "source": "test",
        }
        series = {
            "xray": [
                {"time_tag": "2026-08-12T09:00:00+00:00", "flux": 1.0e-6},
                {"time_tag": "2026-08-12T10:00:00+00:00", "flux": 1.5e-6},
                {"time_tag": "2026-08-12T11:00:00+00:00", "flux": 2.0e-6},
            ],
            "kp": [
                {"time_tag": "2026-08-12T06:00:00+00:00", "Kp": 2.0},
                {"time_tag": "2026-08-12T09:00:00+00:00", "Kp": 3.0},
            ],
        }
        p = predict_horizons(weather, series=series)
        self.assertEqual(p.method, "decay+trend")
        self.assertGreaterEqual(p.series_used.get("xray", 0), 3)

    def test_series_from_bundle(self):
        from engine.solar import series_from_bundle

        bundle = {
            "xray": [
                {"time_tag": "t1", "flux": 1e-6, "energy": "0.1-0.8nm"},
                {"time_tag": "t2", "flux": 2e-6, "energy": "0.1-0.8nm"},
            ],
            "kp": [["time_tag", "Kp"], ["t0", "1.0"], ["t1", "2.5"]],
            "f107": [{"time_tag": "d1", "flux": 140.0}],
        }
        s = series_from_bundle(bundle)
        self.assertEqual(len(s["xray"]), 2)
        self.assertGreaterEqual(len(s["kp"]), 1)
        self.assertEqual(s["f107"][0]["flux"], 140.0)


class TestGeoH5(unittest.TestCase):
    def test_sunlit_and_bands(self):
        from datetime import datetime, timezone

        from engine.solar import (
            assess_geo_from_positions,
            is_sunlit,
            solar_elevation_deg,
        )

        noon = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        # equator, subsolar-ish at lon~0 at noon
        elev = solar_elevation_deg(0.0, 0.0, noon)
        self.assertGreater(elev, 50.0)
        self.assertTrue(is_sunlit(0.0, 0.0, 550.0, noon))
        # night side
        self.assertFalse(is_sunlit(0.0, 180.0, 550.0, noon))

        rows = [
            {"lat": 0.0, "lon": 0.0, "alt_km": 540.0, "shell": "shell:53"},
            {"lat": 10.0, "lon": 5.0, "alt_km": 560.0, "shell": "shell:53"},
            {"lat": 0.0, "lon": 180.0, "alt_km": 550.0, "shell": "shell:70"},
            {"lat": -20.0, "lon": 170.0, "alt_km": 340.0, "shell": "shell:70"},
        ]
        geo = assess_geo_from_positions(rows, when=noon)
        self.assertEqual(geo.n_with_pos, 4)
        self.assertEqual(geo.version, "geo-v1")
        self.assertGreater(geo.sunlit, 0)
        self.assertLess(geo.sunlit, 4)
        self.assertTrue(any(b.n_sats > 0 for b in geo.bands))
        d = geo.as_dict()
        self.assertIn("bands", d)
        self.assertIn("shells", d)
        self.assertEqual(len(d["shells"]), 2)

    def test_geo_from_amap(self):
        from engine.build import build_map
        from engine.solar import assess_geo_from_amap, short_geo_line

        _, amap, _, _ = build_map(
            limit=25,
            hot_only=True,
            offline_demo=True,
            backend="python",
            cache="out/starlink_tle_cache.txt",
        )
        geo = assess_geo_from_amap(amap)
        self.assertGreater(geo.n_with_pos, 0)
        self.assertIsNotNone(geo.median_alt_km)
        line = short_geo_line(geo)
        self.assertIn("sunlit=", line)


class TestHazardReportH4(unittest.TestCase):
    def test_report_json_md_and_solar_meta(self):
        from engine.solar import assess_hazard, build_hazard_report, predict_horizons

        weather = {
            "as_of": "2026-08-12T12:00:00+00:00",
            "flare_letter": "C",
            "flare_mag": 1.5,
            "flare_class": "C1.5",
            "f107": 110.0,
            "kp": 2.0,
            "xray_flux": 1.5e-6,
            "mode": "stub",
            "source": "test",
        }
        h = assess_hazard(
            weather, shells={"shell:53": 40, "shell:70": 10}, total_sats=50
        )
        pred = predict_horizons(weather)
        report = build_hazard_report(
            weather,
            h,
            predict=pred,
            map_summary={"sats": 50, "cells": 100, "hot_cells": 40},
            src="test",
        )
        d = report.as_dict()
        self.assertEqual(d["version"], "hazard-report-v1")
        self.assertIn("groups", d)
        self.assertEqual(len(d["groups"]), 3)  # constellation + 2 shells
        self.assertIn("predict", d)
        md = report.as_markdown()
        self.assertIn("# Cynober Studio", md)
        self.assertIn("## Groups", md)
        self.assertIn("## Horizons", md)
        solar = report.solar_meta()
        self.assertIn("weather", solar)
        self.assertIn("hazard", solar)
        self.assertIn("predict", solar)
        self.assertEqual(solar["hazard"]["severity"], h.severity)


if __name__ == "__main__":
    unittest.main()
