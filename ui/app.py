#!/usr/bin/env python3
"""
Cynober Studio HTTP server (stdlib only).

  GET  /              → 2D heatmap UI
  GET  /static/*      → css/js
  GET  /api/version   → {version, sla_version, design_sats}
  GET  /api/sla       → 50k SLA contract (engine/sla.py)
  GET  /api/data      → snapshot() + meta  (cells-scale; no O(N) sat dumps)
  GET  /api/filter    → filter_density(shell, min_count)
  POST /api/refresh   → refresh catalog (optional minutes)
  GET  /api/summary   → summary()
  GET  /api/feeder    → live feeder status
  POST /api/feeder/stop → stop feeder
  GET  /api/sphere    → S2b sphere quads (3D)
  GET  /api/weather   → public NOAA SWPC space weather (F10.7, X-ray, Kp)
  GET  /api/hazard    → solar hazard proxy global + per shell
                      · ?grid=1&shell=&min_count= → 2D exposure overlay cells
"""
from __future__ import annotations

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
    meta: dict = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)
    feeder: Any = None  # Optional[LiveFeeder]
    studio_mode: str = "2d"  # 2d | 3d (default UI hint)
    snapshot_dir: str = "out/snapshots"
    snapshot_retention_days: int = 7

    def refresh_catalog(
        self,
        *,
        minutes: float = 0.0,
        reload_tle: bool = False,
    ) -> dict:
        """Refresh positions; optionally re-fetch / re-parse TLE text."""
        with self.lock:
            if reload_tle:
                from engine.starlink_atoms import load_tle_text, parse_tle_catalog

                raw, src = load_tle_text(
                    offline_demo=self.offline_demo,
                    cache=Path(self.cache),
                    limit_hint=self.limit or self.using or 12,
                    cache_ttl_hours=self.cache_ttl_hours,
                )
                catalog = parse_tle_catalog(raw)
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
            return self.refresh_catalog(
                minutes=0.0,
                reload_tle=reload_tle and not self.offline_demo,
            )

        # offline: still cycle refresh (SGP4 time advances with wall clock)
        if self.offline_demo:
            def _refresh_offline() -> dict:
                return self.refresh_catalog(minutes=0.0, reload_tle=False)

            fn = _refresh_offline
        else:
            fn = _refresh

        from engine.sla import evaluate_live_interval

        sla_iv = evaluate_live_interval(interval_sec)
        if sla_iv["level"] == "forbidden":
            log.warning("feeder SLA: %s", sla_iv["message_en"])
        elif sla_iv["level"] == "warn":
            log.warning("feeder SLA: %s", sla_iv["message_en"])
        self.feeder = LiveFeeder(
            fn,
            interval_sec=interval_sec,
            max_fails=max_fails,
            name="studio-feeder",
            refresh_first=refresh_first,
        )
        self.feeder.start()
        # attach last SLA classification for /api/feeder consumers
        try:
            self.feeder.sla_interval = sla_iv  # type: ignore[attr-defined]
        except Exception:
            pass
        return self.feeder

    def stop_feeder(self) -> dict:
        if self.feeder is None:
            return {"running": False, "message": "no feeder"}
        self.feeder.stop()
        return self.feeder.status()


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
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
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


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

                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "version": state.amap.get_export_version(),
                        "sla_version": SLA_VERSION,
                        "design_sats": SLA_USABLE_SATS,
                        "sla_path": "/api/sla",
                    },
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
            if path == "/api/data":
                from engine.sla import assert_api_payload_shape

                snap = state.amap.snapshot()
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

                payload = {
                    "status": "ok",
                    "data": {
                        **snap,
                        "nlat": nlat,
                        "nlon": nlon,
                        "tle_source": state.src,
                        "using": state.using,
                        "limit": state.limit,
                        "project": "Cynober Studio",
                        "feeder": feeder_st,
                        "design_sats": SLA_USABLE_SATS,
                    },
                }
                issues = assert_api_payload_shape(payload, path="/api/data")
                if issues:
                    log.error("SLA API shape violation: %s", issues)
                    payload["sla_shape_ok"] = False
                    payload["sla_shape_issues"] = issues
                else:
                    payload["sla_shape_ok"] = True
                _json_response(self, 200, payload)
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
                from adapters.space_weather import get_space_weather

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
                from adapters.space_weather import get_space_weather
                from engine.hazard import (
                    assess_from_amap,
                    build_overlay,
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

                data = export_sphere_data(state.amap)
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
                # Lightweight density analytics for Studio (cells-scale, SLA-safe)
                dens = list((state.amap.density or {}).items())
                counts = sorted(int(c) for _, c in dens)
                total = sum(counts)
                max_c = counts[-1] if counts else 0
                hot = None
                for (ilat, ilon), c in dens:
                    if int(c) == max_c:
                        hot = {"ilat": ilat, "ilon": ilon, "count": int(c)}
                        break
                top = sorted(
                    (
                        {"ilat": ilat, "ilon": ilon, "count": int(c)}
                        for (ilat, ilon), c in dens
                    ),
                    key=lambda x: -x["count"],
                )[:12]

                def _pct(p: float) -> int:
                    if not counts:
                        return 0
                    i = min(
                        len(counts) - 1,
                        max(0, int(round((p / 100.0) * (len(counts) - 1)))),
                    )
                    return int(counts[i])

                summ = state.amap.summary()
                _json_response(
                    self,
                    200,
                    {
                        "status": "ok",
                        "data": {
                            "cells": len(counts),
                            "sum_count": total,
                            "max_count": max_c,
                            "hotspot": hot,
                            "p50": _pct(50),
                            "p90": _pct(90),
                            "top_cells": top,
                            "shells": summ.get("shells") or {},
                            "version": summ.get("version"),
                            "src": state.src,
                            "using": state.using,
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
                meta = store.save(
                    state.amap,
                    snapshot_id=sid,
                    src=state.src,
                    using=state.using,
                )
                _json_response(
                    self, 200, {"status": "ok", "data": meta.as_dict()}
                )
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
    print(f"Cynober Studio  {url}")
    print(f"  TLE={state.src}  sats={state.using}  limit={state.limit}  version={state.amap.version}")
    if state.feeder is not None:
        print(f"  feeder: interval={state.feeder.interval_sec}s running={state.feeder.running}")
    print("  API: /api/version  /api/data  /api/filter  /api/feeder  POST /api/refresh")
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


def build_and_run(
    *,
    limit: int = 400,
    grid: float = 5.0,
    hot_only: bool = True,
    prop: str = "auto",
    offline_demo: bool = False,
    cache: str = "out/starlink_tle_cache.txt",
    backend: str = "python",
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    live_feed: bool = False,
    interval_sec: float = 900.0,
) -> int:
    from engine.starlink_atoms import build_map

    store, amap, use, src = build_map(
        limit=limit,
        grid=grid,
        hot_only=hot_only,
        prop=prop,
        offline_demo=offline_demo,
        cache=cache,
        backend=backend,
    )
    state = StudioState(
        amap=amap,
        catalog=list(use),
        src=src,
        using=len(use),
        limit=int(limit or 0),
        offline_demo=offline_demo,
        cache=cache,
        meta={"store": type(store).__name__},
    )
    if live_feed:
        state.attach_feeder(
            interval_sec=interval_sec,
            reload_tle=not offline_demo,
            refresh_first=False,
        )
    return run_studio(state, host=host, port=port, open_browser=open_browser)
