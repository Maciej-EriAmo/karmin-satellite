#!/usr/bin/env python3
"""
A — public SATCAT country lookup (Celestrak).

Join NORAD catalog number → country code for research filters.
No API key. Offline: fleet→country heuristic.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from engine.constants import USER_AGENT

# Public Celestrak SATCAT (CSV preferred; txt fallback)
URL_SATCAT_CSV = "https://celestrak.org/pub/satcat.csv"
URL_SATCAT_TXT = "https://celestrak.org/pub/satcat.txt"

DEFAULT_CACHE = "out/satcat_cache.json"
DEFAULT_TTL_SEC = 24 * 3600

# Offline / when SATCAT missing: fleet → country heuristic (research only)
FLEET_COUNTRY = {
    "starlink": "US",
    "oneweb": "UK",
    "iridium": "US",
    "globalstar": "US",
    "orbcomm": "US",
    "planet": "US",
    "spire": "US",
    "swarm": "US",
    "gps": "US",
    "galileo": "EU",
    "stations": "ISS",
    "visual": "INT",
    "active": "INT",
    "fy1c-debris": "CN",
    "cosmos-2251-debris": "RU",
    "iridium-33-debris": "US",
    "microsat-r-debris": "IN",
    "cosmos-1408-debris": "RU",
}


def _default_cache_path() -> Path:
    try:
        from engine.user_paths import cache_file, relocate_legacy

        relocate_legacy()
        return cache_file("satcat_cache.json")
    except Exception:
        return Path(__file__).resolve().parents[1] / "out" / "satcat_cache.json"


def _http_get(url: str, *, timeout: float = 60.0) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,text/csv,*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_satcat_csv(text: str) -> Dict[int, str]:
    """
    Parse Celestrak SATCAT CSV → {norad: country}.
    Tolerant to header variants (OBJECT_ID, NORAD_CAT_ID, COUNTRY, …).
    """
    out: Dict[int, str] = {}
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return out
    fields = {f.lower().strip(): f for f in reader.fieldnames if f}

    def _col(*names: str) -> Optional[str]:
        for n in names:
            if n in fields:
                return fields[n]
        return None

    norad_col = _col(
        "norad_cat_id", "norad", "catalog_number", "catnr", "object_number", "satno"
    )
    country_col = _col("country", "country_code", "owner", "launch_site_country")
    if not norad_col or not country_col:
        # try positional guess from first row keys
        return out
    for row in reader:
        try:
            raw_n = (row.get(norad_col) or "").strip()
            # strip alpha object designators; keep digits
            digits = "".join(ch for ch in raw_n if ch.isdigit())
            if not digits:
                continue
            norad = int(digits)
            country = (row.get(country_col) or "").strip().upper()
            if country:
                out[norad] = country[:8]
        except (TypeError, ValueError):
            continue
    return out


def parse_satcat_txt(text: str) -> Dict[int, str]:
    """
    Legacy fixed-width-ish SATCAT lines.
    Common layout: name … norad(5) … country(2) around cols — best-effort.
    """
    out: Dict[int, str] = {}
    for ln in text.splitlines():
        if len(ln) < 40:
            continue
        # try: 5-digit norad early in line, country 2-letter token
        try:
            # catalog number often at columns 14-18 (0-based varies) — scan tokens
            parts = ln.split()
            norad = None
            country = None
            for p in parts:
                if norad is None and p.isdigit() and 3 <= len(p) <= 6:
                    norad = int(p)
                elif (
                    country is None
                    and len(p) == 2
                    and p.isalpha()
                    and p.isupper()
                ):
                    country = p
            if norad is not None and country:
                out[norad] = country
        except (TypeError, ValueError):
            continue
    return out


class SatcatIndex:
    """NORAD → country code with disk cache."""

    def __init__(
        self,
        *,
        cache_path: Optional[Path] = None,
        ttl_sec: float = DEFAULT_TTL_SEC,
        allow_network: bool = True,
    ):
        self.cache_path = Path(cache_path) if cache_path else _default_cache_path()
        self.ttl_sec = float(ttl_sec)
        self.allow_network = bool(allow_network)
        self._map: Dict[int, str] = {}
        self.source: str = "empty"

    def load(self, *, force: bool = False) -> "SatcatIndex":
        if not force and self.cache_path.is_file():
            try:
                payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
                age = time.time() - float(payload.get("saved_at") or 0)
                if age < self.ttl_sec or not self.allow_network:
                    raw = payload.get("map") or {}
                    self._map = {int(k): str(v) for k, v in raw.items()}
                    self.source = f"cache:{self.cache_path.name}"
                    return self
            except Exception:
                pass
        if not self.allow_network:
            self.source = "offline-empty"
            return self
        errors: List[str] = []
        for url, parser in (
            (URL_SATCAT_CSV, parse_satcat_csv),
            (URL_SATCAT_TXT, parse_satcat_txt),
        ):
            try:
                text = _http_get(url)
                m = parser(text)
                if m:
                    self._map = m
                    self.source = f"celestrak:{url.split('/')[-1]}"
                    self._write_cache()
                    return self
                errors.append(f"{url}: empty parse")
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                errors.append(f"{url}:{e}")
        # keep stale cache if any
        if self.cache_path.is_file():
            try:
                payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
                raw = payload.get("map") or {}
                self._map = {int(k): str(v) for k, v in raw.items()}
                self.source = "cache-stale"
                return self
            except Exception:
                pass
        self.source = "failed:" + ";".join(errors)[:120]
        return self

    def _write_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": time.time(),
            "source": self.source,
            "n": len(self._map),
            "map": {str(k): v for k, v in self._map.items()},
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def annotate_sats(self, sats: Sequence[Any]) -> Tuple[int, int]:
        """
        Set sat.country from index (or fleet heuristic).
        Returns (n_from_satcat, n_from_fleet_fallback).
        """
        n_sc = 0
        n_fb = 0
        for s in sats:
            norad = int(getattr(s, "norad", 0) or 0)
            fleet = str(getattr(s, "fleet", "") or "")
            if norad in self._map:
                s.country = self._map[norad]
                n_sc += 1
            else:
                fb = FLEET_COUNTRY.get(fleet.lower())
                s.country = fb
                if fb:
                    n_fb += 1
        return n_sc, n_fb


def filter_by_country(
    sats: Sequence[Any],
    country: str,
) -> List[Any]:
    """Keep sats whose country matches (case-insensitive). Empty country → all."""
    code = (country or "").strip().upper()
    if not code or code in ("*", "ALL", "ANY"):
        return list(sats)
    out = []
    for s in sats:
        c = getattr(s, "country", None)
        if c and str(c).upper() == code:
            out.append(s)
    return out


def country_counts(sats: Iterable[Any]) -> Dict[str, int]:
    acc: Dict[str, int] = {}
    for s in sats:
        c = str(getattr(s, "country", None) or "?").upper()
        acc[c] = acc.get(c, 0) + 1
    return dict(sorted(acc.items(), key=lambda x: -x[1]))
