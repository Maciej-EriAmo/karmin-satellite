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
        from adapters.space_weather import flare_class_from_flux, format_flare_class

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
        from adapters.space_weather import parse_swpc_bundle

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
        from adapters.space_weather import quiet_stub

        s = quiet_stub(reason="test")
        self.assertEqual(s.mode, "stub")
        self.assertEqual(s.source, "stub-quiet-sun")
        self.assertIn("test", s.message)

    def test_client_offline_no_cache(self):
        from adapters.space_weather import SpaceWeatherClient

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
        from engine.hazard import assess_hazard

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
        from engine.hazard import assess_hazard, short_badge

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
        from engine.hazard import assess_hazard, build_overlay, exposure_cells

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


if __name__ == "__main__":
    unittest.main()
