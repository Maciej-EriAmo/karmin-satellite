"""TLE catalog: parse, fetch, cache, offline demo. H7 multi-fleet aware."""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

from engine.catalogs import default_cache_path, get_fleet, parse_fleet_list
from engine.constants import CELESTRAK_URLS, HAS_SGP4, Satrec, USER_AGENT

# Default inclinations for offline multi-fleet demos
_DEMO_INC = {
    "starlink": 53.0,
    "oneweb": 87.0,
    "iridium": 86.4,
    "globalstar": 52.0,
    "orbcomm": 45.0,
    "planet": 97.0,
    "spire": 97.0,
    "swarm": 45.0,
    "gps": 55.0,
    "galileo": 56.0,
    "stations": 51.6,
    "visual": 60.0,
    "active": 50.0,
}


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
    fleet: str = "starlink"
    country: Optional[str] = None  # A: SATCAT / fleet heuristic
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


def parse_tle_catalog(text: str, *, fleet: str = "starlink") -> List[TleSat]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: List[TleSat] = []
    fid = (fleet or "starlink").strip().lower() or "starlink"
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
                fleet=fid,
            )
        )
        i += 3
    return out


def fetch_celestrak_urls(urls: Sequence[str], timeout: float = 60.0) -> Tuple[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"}
    errors: List[str] = []
    for url in urls:
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


def fetch_starlink_tle(timeout: float = 60.0) -> Tuple[str, str]:
    """Back-compat: Starlink supplemental + group fallbacks."""
    return fetch_celestrak_urls(CELESTRAK_URLS, timeout=timeout)


def fetch_fleet_tle(fleet_id: str, timeout: float = 60.0) -> Tuple[str, str]:
    spec = get_fleet(fleet_id)
    return fetch_celestrak_urls(spec.urls(), timeout=timeout)


def demo_tle_blob(n: int = 12, *, fleet: str = "starlink") -> str:
    """Synthetic TLE catalog of size n (unique norad 1..n for capacity tests)."""
    parts: List[str] = []
    n = max(0, int(n))
    fid = (fleet or "starlink").strip().lower() or "starlink"
    prefix = fid.upper().replace("-", "")[:12]
    inc0 = float(_DEMO_INC.get(fid, 50.0))
    # fleet-offset NORAD so multi-fleet offline merge keeps both fleets
    base = (sum(ord(c) for c in fid) % 40) * 2000
    for i in range(n):
        norad = (base + i) % 99999 + 1
        name = f"{prefix}-DEMO-{i:06d}"
        inc = inc0 + (i % 5) * 0.1
        raan = (i * 0.37) % 360.0
        ma = (i * 17.0) % 360.0
        nn = 15.06 + (i % 97) * 0.001
        l1 = f"1 {norad:05d}U 00000A   26001.00000000  .00000000  00000-0  00000-0 0  9990"
        l2 = (
            f"2 {norad:05d} {inc:8.4f} {raan:8.4f} 0001000 "
            f"000.0000 {ma:8.4f} {nn:11.8f}"
        )
        parts.extend([name, l1, l2])
    return "\n".join(parts) + "\n"


def build_demo_catalog(n: int, *, fleet: str = "starlink") -> List[TleSat]:
    """Unique synthetic sats for capacity (norad = 1..n, works past 5-digit TLE field)."""
    out: List[TleSat] = []
    n = max(0, int(n))
    fid = (fleet or "starlink").strip().lower() or "starlink"
    prefix = fid.upper().replace("-", "")[:12]
    inc0 = float(_DEMO_INC.get(fid, 50.0))
    for i in range(n):
        norad = i + 1
        tle_num = norad % 100000
        name = f"{prefix}-DEMO-{i:06d}"
        inc = inc0 + (i % 17) * 0.5
        raan = (i * 0.37) % 360.0
        ma = (i * 17.0) % 360.0
        nn = 15.06 + (i % 97) * 0.001
        l1 = f"1 {tle_num:05d}U 00000A   26001.00000000  .00000000  00000-0  00000-0 0  9990"
        l2 = (
            f"2 {tle_num:05d} {inc:8.4f} {raan:8.4f} 0001000 "
            f"000.0000 {ma:8.4f} {nn:11.8f}"
        )
        out.append(
            TleSat(
                name=name,
                line1=l1,
                line2=l2,
                norad=norad,
                inclination_deg=inc,
                raan_deg=raan,
                mean_anomaly_deg=ma,
                mean_motion_rev_per_day=nn,
                ecc=0.0001,
                fleet=fid,
            )
        )
    return out


def load_tle_text(
    *,
    offline_demo: bool,
    cache: Path,
    limit_hint: int,
    cache_ttl_hours: float = 12.0,
    fleet: str = "starlink",
) -> Tuple[str, str]:
    """Load one fleet TLE text (cache / network / offline demo)."""
    fid = (fleet or "starlink").strip().lower() or "starlink"
    if offline_demo:
        return (
            demo_tle_blob(max(12, limit_hint or 12), fleet=fid),
            f"offline-demo:{fid}",
        )
    ttl = max(0.0, float(cache_ttl_hours)) * 3600.0
    if cache.is_file() and cache.stat().st_size > 100:
        age = time.time() - cache.stat().st_mtime
        if ttl <= 0 or age < ttl:
            return (
                cache.read_text(encoding="utf-8", errors="replace"),
                f"cache:{cache.name} ({age / 3600:.1f}h)",
            )
    try:
        if fid == "starlink":
            raw, url = fetch_starlink_tle()
        else:
            raw, url = fetch_fleet_tle(fid)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw, encoding="utf-8")
        return raw, f"celestrak:{fid}:{url.split('?')[0].split('/')[-1]}"
    except Exception as e:
        if cache.is_file():
            return (
                cache.read_text(encoding="utf-8", errors="replace"),
                f"cache-fallback:{fid} ({e})",
            )
        raise


def load_catalog(
    *,
    fleets: Optional[Sequence[str]] = None,
    fleet: str = "starlink",
    offline_demo: bool = False,
    cache: Optional[Path] = None,
    cache_dir: Path = Path("out"),
    limit_hint: int = 12,
    cache_ttl_hours: float = 12.0,
    per_fleet_limit: Optional[int] = None,
) -> Tuple[List[TleSat], str]:
    """
    H7: load one or more fleets, tag sats with ``fleet``, optional merge.

    ``fleet``: single id or comma-separated ``starlink,oneweb``.
    ``fleets``: explicit list overrides ``fleet``.
    """
    ids = list(fleets) if fleets else parse_fleet_list(fleet)
    all_sats: List[TleSat] = []
    srcs: List[str] = []
    seen_norad: set = set()

    for fid in ids:
        cpath = (
            Path(cache)
            if cache is not None and len(ids) == 1
            else cache_dir / get_fleet(fid).cache_basename()
        )
        # legacy default starlink cache name
        if fid == "starlink" and cache is not None and len(ids) == 1:
            cpath = Path(cache)
        elif fid == "starlink" and not cpath.is_file():
            legacy = cache_dir / "starlink_tle_cache.txt"
            if legacy.is_file():
                cpath = legacy

        raw, src = load_tle_text(
            offline_demo=offline_demo,
            cache=cpath,
            limit_hint=limit_hint,
            cache_ttl_hours=cache_ttl_hours,
            fleet=fid,
        )
        chunk = parse_tle_catalog(raw, fleet=fid)
        if per_fleet_limit is not None and per_fleet_limit > 0:
            chunk = chunk[: int(per_fleet_limit)]
        for sat in chunk:
            # multi-fleet: keep first NORAD wins (avoid double-count)
            if sat.norad in seen_norad and len(ids) > 1:
                continue
            seen_norad.add(sat.norad)
            all_sats.append(sat)
        srcs.append(src)

    src_s = " | ".join(srcs) if len(srcs) > 1 else (srcs[0] if srcs else "empty")
    if len(ids) > 1:
        src_s = f"multi:{','.join(ids)} · {src_s}"
    return all_sats, src_s

