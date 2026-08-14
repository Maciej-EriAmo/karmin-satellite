#!/usr/bin/env python3
"""
Cynober Studio HTTP server (stdlib only).

  GET  /              → 2D heatmap UI
  GET  /static/*      → css/js
  GET  /api/version   → {version, sla_version, design_sats}
  GET  /api/sla       → 50k SLA contract (engine/sla.py)
  GET  /api/data      → snapshot() + meta  (cells-scale; no O(N) sat dumps)
                      · ?reach=1 → density only in session reach (view)
  GET  /api/reach     → session reach status (counts; no sat dump)
  POST /api/session   → set_session_scope (rebuild session bindings)
  GET  /api/ghost     → retained/cold layer in session reach (W2)
  POST /api/ghost/demo → cool a sample in reach (makes ghost visible)
  POST /api/impact    → impact_of_cooling (simulate=true default)
  GET  /api/resonance → W4 HRR/lexical browse (?q=&k=20)
  POST /api/system_tick → W5 mini tick + decisions
  GET  /api/decisions → last decision log
  GET  /api/attention → live root status (session-only GC)
  POST /api/attention → {live} | {commit} | {restore}
  GET  /api/export    → download JSON/MD file (?format=json|md&reach=1&sats=1)
  GET  /api/filter    → filter_density(shell, min_count)
  POST /api/refresh   → refresh catalog (optional minutes)
  GET  /api/summary   → summary()
  GET  /api/feeder    → live feeder status
  POST /api/feeder/stop → stop feeder
  GET  /api/sphere    → S2b sphere quads (3D)
  GET  /api/weather   → public NOAA SWPC (engine.solar)
  GET  /api/hazard    → solar hazard proxy global + per shell
                      · ?grid=1&shell=&min_count= → 2D exposure overlay cells
  GET  /api/predict   → H3 horizon forecasts 1h/6h/24h (engine.solar.predict)
  GET  /api/report    → H4 HazardReport JSON (+ ?md=1 Markdown body)
  GET  /api/geo       → H5 altitude bands + sunlit fraction
  GET  /api/fleets    → H7 public catalog list
  POST /api/fleet     → {fleet, country?} switch catalog (rebuild map)
  GET  /api/timeline  → B snapshot timeline metrics
  GET  /api/timeline/compare?a=&b= → density delta between snapshots
  GET  /api/alert     → EM storm watch (Kp/flare now or 6h) + crowding counts
"""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import sys
import threading
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = Path(__file__).resolve().parent
STATIC_DIR = UI_DIR / "static"
TEMPLATE_DIR = UI_DIR / "templates"

_SUB = ROOT / "substrate"
if str(_SUB) not in sys.path:
    sys.path.insert(0, str(_SUB))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

log = logging.getLogger("cynober.studio")
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [cynober.studio] %(message)s",
    )


@dataclass
class StudioState:
    """Shared runtime for HTTP handlers (thread-safe via amap locks)."""

    amap: Any
    catalog: List[Any]
    src: str = ""
    using: int = 0
    limit: int = 0  # 0 = entire catalog; preserved across reload_tle (Q2 fix)
    offline_demo: bool = False
    cache: str = "out/starlink_tle_cache.txt"
    cache_ttl_hours: float = 12.0
    fleet: str = "starlink"  # H7: id or starlink,oneweb
    country: str = ""  # A: SATCAT country filter (e.g. US)
    meta: dict = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    feeder: Any = None  # Optional[LiveFeeder]
    studio_mode: str = "2d"  # 2d | 3d (default UI hint)
    snapshot_dir: str = "out/snapshots"
    snapshot_retention_days: int = 7
    reach_mode: str = ""  # empty = env CYNOBER_REACH_MODE

    def refresh_catalog(
        self,
        *,
        minutes: float = 0.0,
        reload_tle: bool = False,
    ) -> dict:
        """Refresh positions; optionally re-fetch / re-parse TLE text."""
        with self.lock:
            if reload_tle:
                from engine.satcat import SatcatIndex, filter_by_country
                from engine.tle import load_catalog

                catalog, src = load_catalog(
                    fleet=self.fleet or "starlink",
                    offline_demo=self.offline_demo,
                    cache=Path(self.cache),
                    cache_dir=Path(self.cache).parent if self.cache else Path("out"),
                    limit_hint=self.limit or self.using or 12,
                    cache_ttl_hours=self.cache_ttl_hours,
                )
                idx = SatcatIndex(allow_network=not self.offline_demo).load()
                idx.annotate_sats(catalog)
                if self.country:
                    before = len(catalog)
                    catalog = filter_by_country(catalog, self.country)
                    src = (
                        f"{src} · country={self.country.strip().upper()} "
                        f"({len(catalog)}/{before})"
                    )
                if self.limit and self.limit > 0:
                    catalog = catalog[: self.limit]
                self.catalog = catalog
                self.src = src
                self.using = len(catalog)
            info = self.amap.refresh(self.catalog, minutes=minutes, ensure=True)
            info["src"] = self.src
            info["using"] = self.using
            info["limit"] = self.limit
            return info

    def attach_feeder(
        self,
        *,
        interval_sec: float = 900.0,
        reload_tle: bool = True,
        max_fails: int = 3,
        refresh_first: bool = False,
    ) -> Any:
        from engine.live_feeder import LiveFeeder

        if self.feeder is not None and getattr(self.feeder, "running", False):
            self.feeder.stop()

        def _refresh() -> dict:
            # offline: still cycle (SGP4 advances with wall clock); never re-fetch TLE
            return self.refresh_catalog(
                minutes=0.0,
                reload_tle=reload_tle and not self.offline_demo,
            )

        from engine.sla import evaluate_live_interval

        sla_iv = evaluate_live_interval(interval_sec)
        if sla_iv["level"] in ("forbidden", "warn"):
            log.warning("feeder SLA: %s", sla_iv["message_en"])
        self.feeder = LiveFeeder(
            _refresh,
            interval_sec=interval_sec,
            max_fails=max_fails,
            name="studio-feeder",
            refresh_first=refresh_first,
        )
        self.feeder.start()
        self.feeder.sla_interval = sla_iv  # type: ignore[attr-defined]
        return self.feeder

    def stop_feeder(self) -> dict:
        if self.feeder is None:
            return {"running": False, "message": "no feeder"}
        self.feeder.stop()
        return self.feeder.status()


def _json_response(
    handler: BaseHTTPRequestHandler,
    code: int,
    payload: dict,
    *,
    etag: Optional[str] = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if etag:
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "private, max-age=0, must-revalidate")
    else:
        handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _download_response(
    handler: BaseHTTPRequestHandler,
    body: bytes,
    *,
    filename: str,
    content_type: str,
) -> None:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename)
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Disposition", f'attachment; filename="{safe}"')
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"invalid json body: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("json body must be an object")
    return data


def create_handler(state: StudioState):
    class StudioHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._dispatch_get()
            except Exception as e:
                traceback.print_exc()
                _json_response(
                    self,
                    500,
                    {"status": "error", "message": str(e), "data": None},
                )

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._dispatch_post()
            except ValueError as e:
                _json_response(
                    self,
                    400,
                    {"status": "error", "message": str(e), "data": None},
                )
            except Exception as e:
                traceback.print_exc()
                _json_response(
                    self,
                    500,
                    {"status": "error", "message": str(e), "data": None},
                )

        def _dispatch_get(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            qs = parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self._serve_index()
                return
            if path.startswith("/static/"):
                self._serve_static(path[len("/static/") :])
                return
            if path == "/api/version":
                from engine.sla import SLA_USABLE_SATS, SLA_VERSION

                ver = int(state.amap.get_export_version())
                etag = f'W/"v{ver}"'
                inm = (self.headers.get("If-None-Match") or "").strip()
                if inm and inm == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return
                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "version": ver,
                        "sla_version": SLA_VERSION,
                        "design_sats": SLA_USABLE_SATS,
                        "sla_path": "/api/sla",
                        "fleet": state.fleet,
                        "country": state.country or "",
                    },
                    etag=etag,
                )
                return
            if path == "/api/sla":
                from engine.sla import sla_public_dict

                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": sla_public_dict(),
                        "using": state.using,
                        "limit": state.limit,
                        "map_version": state.amap.get_export_version(),
                    },
                )
                return
            if path == "/api/summary":
                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": state.amap.summary(),
                        "src": state.src,
                        "using": state.using,
                        "limit": state.limit,
                    },
                )
                return
            if path == "/api/reach":
                from engine.reach_studio import reach_status

                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": reach_status(state.amap, state=state)},
                )
                return
            if path == "/api/resonance":
                from engine.reach_studio import studio_resonance

                q = (qs.get("q") or qs.get("query") or [""])[0]
                try:
                    k = int((qs.get("k") or ["20"])[0])
                except ValueError:
                    k = 20
                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": studio_resonance(state.amap, q, k=k),
                    },
                )
                return
            if path == "/api/attention":
                from engine.reach_studio import attention_status

                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": attention_status(state.amap),
                    },
                )
                return
            if path == "/api/decisions":
                from engine.reach_studio import get_decisions

                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": {
                            "log": get_decisions(state.amap),
                            "version": state.amap.get_export_version(),
                        },
                    },
                )
                return
            if path == "/api/ghost":
                from engine.reach_studio import collect_ghost

                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": collect_ghost(state.amap, state=state)},
                )
                return
            if path == "/api/export":
                from datetime import datetime, timezone

                from engine.reach_studio import (
                    build_export_payload,
                    export_as_markdown,
                    reach_enabled,
                )

                fmt = (qs.get("format") or ["json"])[0].strip().lower()
                if fmt not in ("json", "md", "markdown"):
                    fmt = "json"
                want_reach = (qs.get("reach") or ["0"])[0] in ("1", "true", "yes")
                include_sats = (qs.get("sats") or ["0"])[0] in ("1", "true", "yes")
                use_reach = bool(want_reach and reach_enabled(state))
                payload = build_export_payload(
                    state.amap,
                    state=state,
                    reach_only=use_reach,
                    include_sats=include_sats,
                    src=state.src,
                    using=state.using,
                    fleet=state.fleet,
                    country=state.country or "",
                )
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                fleet = (state.fleet or "map").replace(",", "-")[:24]
                if fmt in ("md", "markdown"):
                    body = export_as_markdown(payload).encode("utf-8")
                    _download_response(
                        self,
                        body,
                        filename=f"cynober_{fleet}_{stamp}.md",
                        content_type="text/markdown; charset=utf-8",
                    )
                else:
                    body = json.dumps(payload, ensure_ascii=False, indent=2).encode(
                        "utf-8"
                    )
                    _download_response(
                        self,
                        body,
                        filename=f"cynober_{fleet}_{stamp}.json",
                        content_type="application/json; charset=utf-8",
                    )
                return
            if path == "/api/data":
                from engine.sla import assert_api_payload_shape
                from engine.reach_studio import reach_enabled, reach_status

                want_reach = (qs.get("reach") or ["0"])[0] in (
                    "1",
                    "true",
                    "yes",
                )
                use_reach = bool(want_reach and reach_enabled(state))
                snap = state.amap.snapshot(reach_only=use_reach)
                import math

                deg = float(snap.get("grid_deg") or state.amap.grid_deg)
                nlat = int(math.ceil(180.0 / deg))
                nlon = int(math.ceil(360.0 / deg))
                feeder_st = (
                    state.feeder.status() if state.feeder is not None else None
                )
                if state.feeder is not None and hasattr(state.feeder, "sla_interval"):
                    if isinstance(feeder_st, dict):
                        feeder_st = dict(feeder_st)
                        feeder_st["sla"] = getattr(state.feeder, "sla_interval", None)
                from engine.sla import SLA_USABLE_SATS

                summ = state.amap.summary()
                data_body = {
                    **snap,
                    "nlat": nlat,
                    "nlon": nlon,
                    "tle_source": state.src,
                    "using": state.using,
                    "limit": state.limit,
                    "fleet": state.fleet,
                    "country": state.country or "",
                    "countries": summ.get("countries") or {},
                    "fleets": summ.get("fleets") or {},
                    "project": "Cynober Studio",
                    "feeder": feeder_st,
                    "design_sats": SLA_USABLE_SATS,
                }
                if use_reach:
                    rst = reach_status(state.amap, state=state)
                    data_body["reach"] = {
                        "session": rst.get("session"),
                        "mode": rst.get("mode"),
                        "n_sats": rst.get("n_sats"),
                        "n_cells": rst.get("n_cells"),
                        "n_reach": rst.get("n_reach"),
                        "scope": rst.get("scope"),
                    }
                payload = {
                    "status": "ok",
                    "data": data_body,
                }
                issues = assert_api_payload_shape(payload, path="/api/data")
                if issues:
                    log.error("SLA API shape violation: %s", issues)
                    payload["sla_shape_ok"] = False
                    payload["sla_shape_issues"] = issues
                else:
                    payload["sla_shape_ok"] = True
                ver = int(state.amap.get_export_version())
                _json_response(self, 200, payload, etag=f'W/"data-v{ver}"')
                return
            if path == "/api/filter":
                shell = (qs.get("shell") or ["all"])[0]
                try:
                    min_count = int((qs.get("min_count") or ["1"])[0])
                except ValueError:
                    min_count = 1
                filtered = state.amap.filter_density(
                    shell=shell, min_count=min_count
                )
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": filtered},
                )
                return
            if path == "/api/weather":
                from engine.solar import get_space_weather

                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
                offline = (qs.get("offline") or ["0"])[0] in ("1", "true", "yes")
                snap = get_space_weather(force=force, offline=offline)
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": snap.as_dict()},
                )
                return
            if path == "/api/hazard":
                from engine.solar import (
                    assess_from_amap,
                    build_overlay,
                    get_space_weather,
                    short_badge,
                )

                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
                offline = (qs.get("offline") or ["0"])[0] in ("1", "true", "yes")
                want_grid = (qs.get("grid") or ["0"])[0] in ("1", "true", "yes")
                shell = (qs.get("shell") or ["all"])[0]
                try:
                    min_count = int((qs.get("min_count") or ["1"])[0])
                except ValueError:
                    min_count = 1
                weather = get_space_weather(force=force, offline=offline)
                assessment = assess_from_amap(state.amap, weather)
                payload = assessment.as_dict()
                payload["badge"] = short_badge(assessment)
                if want_grid:
                    if shell not in ("all", "*", ""):
                        dens_src = state.amap.filter_density(
                            shell=shell, min_count=min_count
                        )
                        dens = dens_src.get("density") or []
                    else:
                        dens = [
                            {"ilat": k[0], "ilon": k[1], "count": int(v)}
                            for k, v in (state.amap.density or {}).items()
                            if int(v) >= min_count
                        ]
                    payload["overlay"] = build_overlay(
                        assessment,
                        dens,
                        shell=shell,
                        min_count=min_count,
                    )
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": payload},
                )
                return
            if path == "/api/predict":
                from engine.solar import (
                    get_space_weather_bundle,
                    predict_horizons,
                    short_horizon_line,
                )

                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
                offline = (qs.get("offline") or ["0"])[0] in ("1", "true", "yes")
                prop_raw = (qs.get("prop_minutes") or qs.get("minutes") or [None])[0]
                prop_minutes = None
                if prop_raw not in (None, ""):
                    try:
                        prop_minutes = float(prop_raw)
                    except ValueError:
                        prop_minutes = None
                weather, series = get_space_weather_bundle(
                    force=force, offline=offline
                )
                pred = predict_horizons(
                    weather,
                    series=series,
                    prop_minutes=prop_minutes,
                )
                payload = pred.as_dict()
                payload["badge"] = short_horizon_line(pred)
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": payload},
                )
                return
            if path == "/api/report":
                from engine.solar import collect_solar_for_map

                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
                offline = (qs.get("offline") or ["0"])[0] in ("1", "true", "yes")
                with_predict = (qs.get("predict") or ["1"])[0] not in (
                    "0",
                    "false",
                    "no",
                )
                want_md = (qs.get("md") or ["0"])[0] in ("1", "true", "yes")
                report = collect_solar_for_map(
                    state.amap,
                    force=force,
                    offline=offline,
                    with_predict=with_predict,
                    src=state.src,
                )
                data = report.as_dict()
                if want_md:
                    data["markdown"] = report.as_markdown()
                data["solar"] = report.solar_meta()
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": data},
                )
                return
            if path == "/api/feeder":
                if state.feeder is None:
                    _json_response(
                        self,
                        200,
                        {
                            "status": "ok",
                            "data": {"running": False, "message": "no feeder"},
                        },
                    )
                else:
                    _json_response(
                        self,
                        200,
                        {"status": "ok", "data": state.feeder.status()},
                    )
                return
            if path == "/api/sphere":
                from transform.sphere import export_sphere_data

                layer = (qs.get("layer") or ["density"])[0]
                shell = (qs.get("shell") or ["all"])[0]
                try:
                    min_count = int((qs.get("min_count") or ["1"])[0])
                except ValueError:
                    min_count = 1
                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes")
                offline = (qs.get("offline") or ["0"])[0] in ("1", "true", "yes")
                assessment = None
                layer_l = (layer or "density").lower()
                if layer_l in (
                    "radiation",
                    "intensity",
                    "hazard",
                    "blend",
                    "rad",
                    "solar",
                ):
                    try:
                        from engine.solar import assess_from_amap, get_space_weather

                        wx = get_space_weather(force=force, offline=offline)
                        assessment = assess_from_amap(state.amap, wx)
                    except Exception as e:
                        log.warning("sphere solar: %s", e)
                        assessment = None
                data = export_sphere_data(
                    state.amap,
                    layer=layer,
                    assessment=assessment,
                    shell=shell,
                    min_count=min_count,
                )
                data["tle_source"] = state.src
                data["using"] = state.using
                data["project"] = "Cynober Studio"
                _json_response(self, 200, {"status": "ok", "data": data})
                return
            if path == "/api/snapshots":
                from adapters.snapshot_store import SnapshotStore

                store = SnapshotStore(
                    Path(state.snapshot_dir),
                    retention_days=state.snapshot_retention_days,
                )
                items = [m.as_dict() for m in store.list()]
                _json_response(self, 200, {"status": "ok", "data": items})
                return
            if path == "/api/analyze":
                from engine.analytics import amap_density_analytics

                payload = amap_density_analytics(state.amap)
                payload.update(
                    {
                        "src": state.src,
                        "using": state.using,
                        "fleet": state.fleet,
                        "country": state.country or "",
                    }
                )
                # H5: attach geo summary when positions available
                if (qs.get("geo") or ["1"])[0] not in ("0", "false", "no"):
                    try:
                        from engine.solar import assess_geo_from_amap, short_geo_line

                        geo = assess_geo_from_amap(state.amap)
                        payload["geo"] = geo.as_dict()
                        payload["geo_badge"] = short_geo_line(geo)
                    except Exception as e:
                        log.warning("analyze geo: %s", e)
                _json_response(self, 200, {"status": "ok", "data": payload})
                return
            if path == "/api/timeline":
                from adapters.snapshot_store import SnapshotStore
                from engine.analytics import compare_density, timeline_from_store

                store = SnapshotStore(
                    Path(state.snapshot_dir),
                    retention_days=state.snapshot_retention_days,
                )
                a_id = (qs.get("a") or qs.get("compare_a") or [None])[0]
                b_id = (qs.get("b") or qs.get("compare_b") or [None])[0]
                if a_id and b_id:
                    try:
                        pa, pb = store.load_raw(str(a_id)), store.load_raw(str(b_id))
                        data = compare_density(pa, pb)
                        _json_response(self, 200, {"status": "ok", "data": data})
                    except Exception as e:
                        log.warning("timeline compare: %s", e)
                        _json_response(
                            self, 404, {"status": "error", "message": str(e)}
                        )
                    return
                try:
                    limit = int((qs.get("limit") or ["40"])[0])
                except ValueError:
                    limit = 40
                frames = timeline_from_store(store, limit=limit)
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": {"n": len(frames), "frames": frames}},
                )
                return
            if path == "/api/geo":
                from engine.solar import assess_geo_from_amap, short_geo_line

                geo = assess_geo_from_amap(state.amap)
                data = geo.as_dict()
                data["badge"] = short_geo_line(geo)
                _json_response(self, 200, {"status": "ok", "data": data})
                return
            if path == "/api/alert":
                from engine.event_alert import assess_event_alert

                offline = (qs.get("offline") or ["0"])[0] in ("1", "true", "yes")
                weather = None
                predict = None
                try:
                    from engine.solar import (
                        assess_from_amap,
                        get_space_weather,
                        predict_horizons,
                    )

                    wx = get_space_weather(offline=offline)
                    weather = assess_from_amap(state.amap, wx)
                    predict = predict_horizons(wx)
                except Exception as e:
                    log.warning("alert weather: %s", e)
                data = assess_event_alert(
                    state.amap, weather=weather, predict=predict
                )
                _json_response(self, 200, {"status": "ok", "data": data})
                return
            if path == "/api/fleets":
                from engine.catalogs import (
                    curated_fleet_ids,
                    list_fleets,
                    parse_fleet_list,
                )

                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": {
                            "fleets": list_fleets(),
                            "current": state.fleet,
                            "current_ids": parse_fleet_list(state.fleet),
                            "all_curated": curated_fleet_ids(include_active=False),
                            "limit": state.limit,
                        },
                    },
                )
                return
            if path == "/api/health":
                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "service": "cynober-studio",
                        "version": state.amap.get_export_version(),
                        "studio_mode": state.studio_mode,
                        "feeder": bool(
                            state.feeder is not None
                            and getattr(state.feeder, "running", False)
                        ),
                    },
                )
                return
            if path in ("/api/rpc", "/api/rpc/status"):
                from adapters.cynober_rpc import rpc_status_dict

                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": rpc_status_dict()},
                )
                return
            if path == "/api/rpc/health":
                from adapters.cynober_rpc import (
                    CynoberRpcBridge,
                    CynoberRpcError,
                    rpc_status_dict,
                )

                base = rpc_status_dict()
                if not base.get("available"):
                    _json_response(
                        self,
                        200,
                        {
                            "status": "unavailable",
                            "data": base,
                            "message": "cynober_client not available",
                        },
                    )
                    return
                try:
                    with CynoberRpcBridge.from_env() as br:
                        h = br.health()
                    _json_response(self, 200, {"status": "ok", "data": h})
                except (CynoberRpcError, Exception) as e:
                    _json_response(
                        self,
                        200,
                        {
                            "status": "error",
                            "data": base,
                            "message": str(e),
                        },
                    )
                return

            _json_response(self, 404, {"status": "error", "message": "not found"})

        def _dispatch_post(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/api/attention":
                from engine.reach_studio import (
                    apply_live_scope,
                    attention_status,
                    commit_attention,
                    restore_catalog,
                    set_live_root,
                )

                body = _read_json_body(self)
                with state.lock:
                    if body.get("restore") or body.get("live") in (
                        False,
                        0,
                        "0",
                        "false",
                        "no",
                    ):
                        info = restore_catalog(state.amap, state.catalog)
                    elif body.get("commit"):
                        if not getattr(state.amap, "_live_root", False):
                            set_live_root(state.amap, True)
                        info = commit_attention(state.amap)
                    elif body.get("live") in (True, 1, "1", "true", "yes"):
                        info = set_live_root(state.amap, True)
                    else:
                        info = attention_status(state.amap)
                _json_response(self, 200, {"status": "ok", "data": info})
                return
            if path == "/api/system_tick":
                from engine.reach_studio import studio_system_tick

                body = _read_json_body(self)
                try:
                    settle = int(body.get("settle_local") or 0)
                except (TypeError, ValueError):
                    settle = 0
                with state.lock:
                    info = studio_system_tick(
                        state.amap, settle_local=settle
                    )
                _json_response(self, 200, {"status": "ok", "data": info})
                return
            if path == "/api/impact":
                from engine.reach_studio import impact_of_cooling

                body = _read_json_body(self)
                simulate = body.get("simulate", True) not in (
                    False,
                    0,
                    "0",
                    "false",
                    "no",
                )
                cool_sats = body.get("cool_sats") or body.get("sats") or None
                if isinstance(cool_sats, str):
                    cool_sats = [cool_sats]
                or_shell = str(body.get("or_shell") or body.get("shell") or "")
                or_fleet = str(body.get("or_fleet") or body.get("fleet") or "")
                weather = None
                try:
                    from engine.solar import get_space_weather

                    weather = get_space_weather(offline=True)
                except Exception:
                    weather = None
                with state.lock:
                    info = impact_of_cooling(
                        state.amap,
                        cool_sats=cool_sats,
                        or_shell=or_shell,
                        or_fleet=or_fleet,
                        simulate=bool(simulate),
                        weather=weather,
                    )
                _json_response(self, 200, {"status": "ok", "data": info})
                return
            if path == "/api/ghost/demo":
                from engine.reach_studio import demo_cool_in_reach, reach_enabled

                if not reach_enabled(state):
                    _json_response(
                        self,
                        200,
                        {
                            "status": "ok",
                            "data": {"enabled": False, "mode": "off", "cooled": 0},
                        },
                    )
                    return
                body = _read_json_body(self)
                try:
                    n = int(body.get("n") or 8)
                except (TypeError, ValueError):
                    n = 8
                with state.lock:
                    info = demo_cool_in_reach(state.amap, n=n)
                _json_response(self, 200, {"status": "ok", "data": info})
                return
            if path == "/api/session":
                from engine.reach_studio import (
                    reach_enabled,
                    reach_status,
                    set_session_scope,
                )

                if not reach_enabled(state):
                    _json_response(
                        self,
                        200,
                        {
                            "status": "ok",
                            "data": reach_status(state.amap, state=state),
                        },
                    )
                    return
                body = _read_json_body(self)
                shell = str(body.get("shell") or "all")
                fleet = str(body.get("fleet") or "")
                country = str(body.get("country") or "")
                try:
                    min_count = int(body.get("min_count") or 1)
                except (TypeError, ValueError):
                    min_count = 1
                with state.lock:
                    if getattr(state.amap, "_live_root", False):
                        from engine.reach_studio import apply_live_scope

                        info = apply_live_scope(
                            state.amap,
                            state.catalog,
                            shell=shell,
                            fleet=fleet,
                            country=country,
                            min_count=min_count,
                        )
                    else:
                        info = set_session_scope(
                            state.amap,
                            shell=shell,
                            fleet=fleet,
                            country=country,
                            min_count=min_count,
                        )
                info["enabled"] = True
                info["mode"] = reach_status(state.amap, state=state).get("mode")
                _json_response(self, 200, {"status": "ok", "data": info})
                return
            if path == "/api/refresh":
                body = _read_json_body(self)
                minutes = float(body.get("minutes") or 0.0)
                reload_tle = bool(body.get("reload_tle") or False)
                info = state.refresh_catalog(
                    minutes=minutes, reload_tle=reload_tle
                )
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": info},
                )
                return
            if path == "/api/fleet":
                # H7/A: switch fleet (+ optional country) and rebuild map
                body = _read_json_body(self)
                fleet = str(body.get("fleet") or body.get("id") or "").strip()
                if not fleet:
                    _json_response(
                        self,
                        400,
                        {"status": "error", "message": "fleet required"},
                    )
                    return
                country = str(body.get("country") or "").strip() or None
                try:
                    from engine.build import build_map

                    limit = int(
                        body.get("limit")
                        if body.get("limit") is not None
                        else state.limit
                    )
                    store, amap, use, src = build_map(
                        limit=limit,
                        hot_only=True,
                        offline_demo=bool(state.offline_demo),
                        cache=state.cache,
                        backend="python",
                        fleet=fleet,
                        country=country,
                        satcat=True,
                    )
                    state.amap = amap
                    state.catalog = list(use)
                    state.src = src
                    state.using = len(use)
                    state.limit = limit
                    state.fleet = fleet
                    state.country = country or ""
                    log.info(
                        "fleet switch fleet=%s country=%s using=%s",
                        fleet,
                        country,
                        state.using,
                    )
                    _json_response(
                        self,
                        200,
                        {
                            "status": "ok",
                            "data": {
                                "fleet": fleet,
                                "country": state.country,
                                "src": src,
                                "using": state.using,
                                "limit": state.limit,
                                "version": amap.get_export_version(),
                                "summary": amap.summary(),
                            },
                        },
                    )
                except Exception as e:
                    log.exception("fleet switch failed")
                    _json_response(
                        self,
                        502,
                        {"status": "error", "message": str(e)},
                    )
                return
            if path == "/api/feeder/stop":
                info = state.stop_feeder()
                _json_response(self, 200, {"status": "ok", "data": info})
                return
            if path == "/api/feeder/start":
                body = _read_json_body(self)
                interval = float(body.get("interval_sec") or body.get("interval") or 900)
                reload_tle = body.get("reload_tle")
                if reload_tle is None:
                    reload_tle = not state.offline_demo
                feeder = state.attach_feeder(
                    interval_sec=interval,
                    reload_tle=bool(reload_tle),
                    refresh_first=bool(body.get("refresh_first") or False),
                )
                _json_response(
                    self,
                    200,
                    {"status": "ok", "data": feeder.status()},
                )
                return
            if path == "/api/rpc/push":
                from adapters.cynober_rpc import CynoberRpcBridge, CynoberRpcError
                from adapters.snapshot_store import SnapshotStore

                body = _read_json_body(self)
                store = SnapshotStore(
                    Path(state.snapshot_dir),
                    retention_days=state.snapshot_retention_days,
                )
                sid = body.get("snapshot_id") or body.get("id")
                include_sats = bool(body.get("include_sats") or False)
                try:
                    if not sid:
                        meta = store.save(
                            state.amap,
                            src=state.src,
                            using=state.using,
                            include_sats=include_sats,
                        )
                        sid = meta.snapshot_id
                    with CynoberRpcBridge.from_env(
                        host=body.get("host"),
                        port=body.get("port"),
                        profile=body.get("profile"),
                        world=body.get("world"),
                    ) as br:
                        result = br.push_from_local_store(
                            store, sid, include_sats=include_sats
                        )
                    _json_response(
                        self, 200, {"status": "ok", "data": result.as_dict()}
                    )
                except FileNotFoundError as e:
                    _json_response(
                        self, 404, {"status": "error", "message": str(e)}
                    )
                except (CynoberRpcError, Exception) as e:
                    _json_response(
                        self, 502, {"status": "error", "message": str(e)}
                    )
                return
            if path == "/api/rpc/pull":
                from adapters.cynober_rpc import CynoberRpcBridge, CynoberRpcError
                from adapters.snapshot_store import SnapshotStore

                body = _read_json_body(self)
                sid = body.get("snapshot_id") or body.get("id")
                if not sid:
                    _json_response(
                        self,
                        400,
                        {"status": "error", "message": "snapshot_id required"},
                    )
                    return
                try:
                    with CynoberRpcBridge.from_env(
                        host=body.get("host"),
                        port=body.get("port"),
                        profile=body.get("profile"),
                        world=body.get("world"),
                    ) as br:
                        payload = br.pull_payload(str(sid))
                    store = SnapshotStore(
                        Path(state.snapshot_dir),
                        retention_days=state.snapshot_retention_days,
                    )
                    out_id = str(payload.get("snapshot_id") or sid)
                    path_out = store._path(out_id)
                    path_out.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    applied = False
                    if body.get("apply", True):
                        from adapters.snapshot_store import load_snapshot_into_map

                        _store, amap, use, src = load_snapshot_into_map(payload)
                        with state.lock:
                            state.amap = amap
                            state.catalog = list(use)
                            state.src = src
                            state.using = len(use)
                        applied = True
                    _json_response(
                        self,
                        200,
                        {
                            "status": "ok",
                            "data": {
                                "snapshot_id": out_id,
                                "cells": len(payload.get("density") or []),
                                "path": str(path_out),
                                "applied": applied,
                                "version": getattr(state.amap, "version", 0),
                            },
                        },
                    )
                except (CynoberRpcError, Exception) as e:
                    _json_response(
                        self, 502, {"status": "error", "message": str(e)}
                    )
                return
            if path == "/api/snapshot/save":
                from adapters.snapshot_store import SnapshotStore

                body = _read_json_body(self)
                store = SnapshotStore(
                    Path(state.snapshot_dir),
                    retention_days=state.snapshot_retention_days,
                )
                sid = body.get("snapshot_id") or body.get("id")
                # H4: attach solar meta by default (opt-out: solar=false)
                attach_solar = body.get("solar", True) not in (
                    False,
                    0,
                    "0",
                    "false",
                    "no",
                )
                solar_offline = body.get("solar_offline", False) in (
                    True,
                    1,
                    "1",
                    "true",
                    "yes",
                )
                meta = store.save(
                    state.amap,
                    snapshot_id=sid,
                    src=state.src,
                    using=state.using,
                    attach_solar=bool(attach_solar),
                    solar_offline=bool(solar_offline),
                    solar_with_predict=body.get("predict", True)
                    not in (False, 0, "0", "false", "no"),
                )
                out = meta.as_dict()
                out["solar_attached"] = bool(attach_solar)
                _json_response(self, 200, {"status": "ok", "data": out})
                return
            if path == "/api/snapshot/load":
                from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map

                body = _read_json_body(self)
                sid = body.get("snapshot_id") or body.get("id")
                if not sid:
                    _json_response(
                        self,
                        400,
                        {"status": "error", "message": "snapshot_id required"},
                    )
                    return
                store = SnapshotStore(
                    Path(state.snapshot_dir),
                    retention_days=state.snapshot_retention_days,
                )
                payload = store.load_raw(str(sid))
                _store, amap, use, src = load_snapshot_into_map(payload)
                with state.lock:
                    state.amap = amap
                    state.catalog = list(use)
                    state.src = src
                    state.using = len(use)
                    if state.limit and state.limit > 0:
                        pass  # keep limit field
                # bump version so UI poll reloads after load
                if getattr(amap, "version", 0) == 0:
                    amap.version = 1
                else:
                    amap.version = int(amap.version) + 1
                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": {
                            "snapshot_id": sid,
                            "version": amap.version,
                            "cells": len(amap.density),
                            "sats": state.using,
                            "src": src,
                            "applied": True,
                        },
                    },
                )
                return
            _json_response(self, 404, {"status": "error", "message": "not found"})

        def _serve_index(self) -> None:
            path = TEMPLATE_DIR / "index.html"
            if not path.is_file():
                _json_response(
                    self, 500, {"status": "error", "message": "index.html missing"}
                )
                return
            # inject default mode from server if no ?mode= in URL (client still owns toggle)
            text = path.read_text(encoding="utf-8")
            if state.studio_mode == "3d" and "mode=3d" not in (self.path or ""):
                # soft default: badge only; client URL param wins
                text = text.replace(
                    'const mode = (params.get("mode") || "2d")',
                    'const mode = (params.get("mode") || "3d")',
                )
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _serve_static(self, rel: str) -> None:
            rel = rel.replace("\\", "/").lstrip("/")
            if ".." in rel.split("/"):
                _json_response(self, 403, {"status": "error", "message": "forbidden"})
                return
            path = (STATIC_DIR / rel).resolve()
            if not str(path).startswith(str(STATIC_DIR.resolve())):
                _json_response(self, 403, {"status": "error", "message": "forbidden"})
                return
            if not path.is_file():
                _json_response(self, 404, {"status": "error", "message": "not found"})
                return
            data = path.read_bytes()
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return StudioHandler


def run_studio(
    state: StudioState,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
) -> int:
    """Blocking studio server. Stops feeder on exit."""
    handler = create_handler(state)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    log.info("Studio listening %s", url)
    print(f"Cynober Studio  {url}")
    print(
        f"  TLE={state.src}  fleet={state.fleet}  country={state.country or '—'}  "
        f"sats={state.using}  limit={state.limit}  version={state.amap.version}"
    )
    if state.feeder is not None:
        print(f"  feeder: interval={state.feeder.interval_sec}s running={state.feeder.running}")
    print(
        "  API: /api/version  /api/data  /api/reach  /api/timeline  /api/fleets  "
        "/api/filter  /api/feeder  POST /api/refresh|/api/fleet|/api/session"
    )
    print("  Ctrl+C to stop")
    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception as e:
            print(f"open browser: {e}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStudio stopped.")
    finally:
        state.stop_feeder()
        httpd.server_close()
    return 0
