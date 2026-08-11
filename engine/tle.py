"""TLE catalog: parse, fetch, cache, offline demo."""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Tuple

from engine.constants import CELESTRAK_URLS, HAS_SGP4, Satrec, USER_AGENT

@dataclass
class TleSat:
    name: str
    line1: str
    line2: str
    norad: int
    inclination_deg: float
    raan_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_per_day: float
    ecc: float
    _satrec: Any = field(default=None, repr=False, compare=False)

    @property
    def shell_key(self) -> str:
        return f"shell:{int(round(self.inclination_deg))}"

    def ensure_satrec(self) -> Any:
        if not HAS_SGP4:
            return None
        if self._satrec is None:
            self._satrec = Satrec.twoline2rv(self.line1, self.line2)
        return self._satrec


def parse_tle_catalog(text: str) -> List[TleSat]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[TleSat] = []
    i = 0
    while i + 2 < len(lines):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if not (l1.startswith("1 ") and l2.startswith("2 ")):
            i += 1
            continue
        try:
            norad = int(l1[2:7])
            inc = float(l2[8:16])
            raan = float(l2[17:25])
            ecc = float("0." + l2[26:33].strip())
            ma = float(l2[43:51])
            n = float(l2[52:63])
        except (ValueError, IndexError):
            i += 3
            continue
        out.append(
            TleSat(
                name=name,
                line1=l1,
                line2=l2,
                norad=norad,
                inclination_deg=inc,
                raan_deg=raan,
                mean_anomaly_deg=ma,
                mean_motion_rev_per_day=n,
                ecc=ecc,
            )
        )
        i += 3
    return out


def fetch_starlink_tle(timeout: float = 60.0) -> Tuple[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"}
    errors: List[str] = []
    for url in CELESTRAK_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            if "1 " in text and "2 " in text:
                return text, url
            errors.append(f"{url}: empty/invalid")
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("Celestrak fetch failed: " + " | ".join(errors))


def demo_tle_blob(n: int = 12) -> str:
    parts: List[str] = []
    for i in range(n):
        norad = 50000 + i
        name = f"STARLINK-DEMO-{i:04d}"
        inc = 53.0 + (i % 5) * 0.1
        raan = (i * 30.0) % 360.0
        ma = (i * 17.0) % 360.0
        nn = 15.06 + (i % 7) * 0.01
        l1 = f"1 {norad:05d}U 00000A   26001.00000000  .00000000  00000-0  00000-0 0  9990"
        l2 = (
            f"2 {norad:05d} {inc:8.4f} {raan:8.4f} 0001000 "
            f"000.0000 {ma:8.4f} {nn:11.8f}"
        )
        parts.extend([name, l1, l2])
    return "\n".join(parts) + "\n"


def load_tle_text(
    *,
    offline_demo: bool,
    cache: Path,
    limit_hint: int,
    cache_ttl_hours: float = 12.0,
) -> Tuple[str, str]:
    if offline_demo:
        return demo_tle_blob(max(12, limit_hint or 12)), "offline-demo"
    raw = None
    src = ""
    ttl = max(0.0, float(cache_ttl_hours)) * 3600.0
    if cache.is_file() and cache.stat().st_size > 100:
        age = time.time() - cache.stat().st_mtime
        if ttl <= 0 or age < ttl:
            return (
                cache.read_text(encoding="utf-8", errors="replace"),
                f"cache:{cache} ({age / 3600:.1f}h)",
            )
    try:
        raw, url = fetch_starlink_tle()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw, encoding="utf-8")
        return raw, f"celestrak:{url.split('/')[-1]}"
    except Exception as e:
        if cache.is_file():
            return (
                cache.read_text(encoding="utf-8", errors="replace"),
                f"cache-fallback ({e})",
            )
        raise

