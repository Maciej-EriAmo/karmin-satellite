# -*- coding: utf-8 -*-
"""Cache i dane Karmin Satellite — LOCALAPPDATA\\KarminSatellite."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List


def data_home() -> Path:
    raw = (
        os.environ.get("KARMIN_SATELLITE_DATA_HOME")
        or os.environ.get("CYNOBER_STUDIO_DATA_HOME")  # legacy alias
        or ""
    ).strip()
    if raw:
        return Path(raw).expanduser()
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        primary = Path(local) / "KarminSatellite"
        legacy = Path(local) / "CynoberStudio"
        if not primary.exists() and legacy.is_dir():
            try:
                legacy.rename(primary)
            except OSError:
                return legacy
        return primary
    return Path.home() / ".local" / "share" / "karmin-satellite"


def cache_dir() -> Path:
    p = data_home() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_file(name: str) -> Path:
    return cache_dir() / name


def relocate_legacy(*, repo: Path | None = None) -> Dict[str, Any]:
    dest = cache_dir()
    moved: List[str] = []
    if repo is None:
        repo = Path(__file__).resolve().parents[1]
    out = repo / "out"
    names = (
        "satcat_cache.json",
        "space_weather_cache.json",
    )
    if out.is_dir():
        for name in names:
            src, dst = out / name, dest / name
            if src.is_file() and not dst.is_file():
                shutil.copy2(src, dst)
                moved.append(name)
                try:
                    src.unlink()
                except OSError:
                    pass
        for src in out.glob("*_cache.json"):
            dst = dest / src.name
            if not dst.is_file():
                shutil.copy2(src, dst)
                moved.append(src.name)
            try:
                src.unlink()
            except OSError:
                pass
    readme = data_home() / "README.txt"
    if not readme.is_file():
        readme.write_text(
            "Karmin Satellite data home — cache poza katalogiem projektu.\n",
            encoding="utf-8",
        )
    return {"home": str(data_home()), "moved": moved}
