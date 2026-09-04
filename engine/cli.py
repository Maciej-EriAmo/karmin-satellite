"""CLI entry — subcommands keep solar/map syntax clean.

  python main.py weather [--offline] [--force]
  python main.py predict [--offline] [--force] [--prop MIN]
  python main.py hazard  [map opts] [--offline]
  python main.py studio  [map opts]
  python main.py         [map opts]          # one-shot map (default)

Solar modules live in ``engine.solar`` (not flag soup on the map command).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence

from engine.bootstrap import ensure_paths

ensure_paths()

from engine.build import build_map
from engine.export_2d import export_report_payload, render_heatmap_png, write_html_report
from engine.lua_bridge import run_lua_tool_name

# Solar domain (inside engine)
from engine.solar import (
    assess_from_amap,
    assess_geo_from_amap,
    collect_solar_for_map,
    get_space_weather,
    get_space_weather_bundle,
    predict_horizons,
    short_badge,
    short_geo_line,
    short_horizon_line,
)

SOLAR_CMDS = frozenset({"weather", "predict", "hazard", "report", "geo"})
TOP_CMDS = frozenset(
    {
        "weather",
        "predict",
        "hazard",
        "report",
        "geo",
        "fleets",
        "timeline",
        "studio",
        "run",
        "help",
    }
)


def _json_out(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _add_solar_net_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--offline",
        action="store_true",
        help="cache/stub only (no network)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="bypass weather cache TTL",
    )


def _add_map_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--limit",
        type=int,
        default=400,
        help="ile satelitów (0 = cały katalog; ceiling=100k, usable=50k)",
    )
    ap.add_argument(
        "--no-arch-cap",
        action="store_true",
        help="nie tnij do ARCH_CEILING_SATS=100000",
    )
    ap.add_argument("--grid", type=float, default=5.0)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--heatmap", type=str, default="out/starlink_heat.png")
    ap.add_argument("--no-heatmap", action="store_true")
    ap.add_argument("--offline-demo", action="store_true")
    ap.add_argument(
        "--fleet",
        type=str,
        default="starlink",
        help="H7 fleet id or merge: starlink | oneweb | starlink,oneweb",
    )
    ap.add_argument(
        "--country",
        type=str,
        default=None,
        help="A: filter by SATCAT/heuristic country code (e.g. US, UK)",
    )
    ap.add_argument(
        "--no-satcat",
        action="store_true",
        help="skip SATCAT country annotation",
    )
    ap.add_argument("--cache", type=str, default="out/starlink_tle_cache.txt")
    ap.add_argument("--lua", action="store_true", help=":tool starlink (izolowany Store)")
    ap.add_argument("--lua-hot", action="store_true", help="starlink_hot.lua")
    ap.add_argument(
        "--lua-shared",
        action="store_true",
        help="Lua na tym samym Store co katalog",
    )
    ap.add_argument(
        "--lua-copy-sats",
        action="store_true",
        help="przy isolate: skopiuj też atomy sat",
    )
    ap.add_argument("--ticks", type=int, default=0)
    ap.add_argument(
        "--backend", choices=("python", "native", "default"), default="python"
    )
    ap.add_argument(
        "--prop",
        choices=("auto", "sgp4", "approx"),
        default="auto",
        help="propagator (domyślnie auto)",
    )
    ap.add_argument("--hot-only", action="store_true", help="tylko komórki count>0")
    ap.add_argument("--full-grid", action="store_true", help="pełna siatka atomów")
    ap.add_argument("--live", type=int, default=0, help="liczba odświeżeń live")
    ap.add_argument("--hz", type=float, default=1.0, help="częstotliwość live refresh")
    ap.add_argument(
        "--html",
        nargs="?",
        const="out/starlink_report.html",
        default=None,
        help="zapisz HTML report",
    )
    ap.add_argument("--open-html", action="store_true")
    ap.add_argument(
        "--snapshot-dir",
        type=str,
        default="out/snapshots",
        help="katalog snapshotów",
    )
    ap.add_argument(
        "--snapshot-retention-days",
        type=int,
        default=7,
        help="retencja snapshotów w dniach (0 = bez prune)",
    )
    ap.add_argument(
        "--snapshot-list",
        action="store_true",
        help="wypisz lokalne snapshoty i wyjdź",
    )
    ap.add_argument(
        "--snapshot-save",
        nargs="?",
        const="__auto__",
        default=None,
        help="zapisz snapshot po build (opcjonalne id)",
    )
    ap.add_argument(
        "--snapshot-load",
        type=str,
        default=None,
        help="wczytaj snapshot zamiast TLE build",
    )
    ap.add_argument(
        "--rpc-health",
        action="store_true",
        help="sprawdź most Cynober RPC i wyjdź",
    )
    ap.add_argument(
        "--rpc-push",
        nargs="?",
        const="__auto__",
        default=None,
        help="wyślij snapshot na Cynober DB",
    )
    ap.add_argument(
        "--rpc-pull",
        type=str,
        default=None,
        help="pobierz snapshot z Cynober RPC",
    )
    ap.add_argument(
        "--rpc-include-sats",
        action="store_true",
        help="przy --rpc-push dołącz TLE satów",
    )
    ap.add_argument("--rpc-host", type=str, default=None)
    ap.add_argument("--rpc-port", type=int, default=None)
    ap.add_argument("--rpc-profile", type=str, default=None)
    ap.add_argument("--rpc-world", type=str, default=None)


def _add_studio_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--host", type=str, default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open-browser", action="store_true")
    ap.add_argument(
        "--studio-mode",
        choices=("2d", "3d"),
        default="2d",
        help="domyślny widok: 2d heatmap lub 3d globe",
    )
    ap.add_argument(
        "--live-feed",
        action="store_true",
        help="cykliczny refresh w tle",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=900.0,
        help="interwał live-feed w sekundach",
    )
    ap.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=12.0,
        help="TTL cache TLE przy reload (godziny)",
    )


def _resolve_hot_only(args: argparse.Namespace) -> bool:
    if args.full_grid:
        return False
    if args.hot_only:
        return True
    return args.limit == 0 or args.limit >= 1000


def _build_or_load(args: argparse.Namespace):
    from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map

    snap_store = SnapshotStore(
        Path(args.snapshot_dir),
        retention_days=int(args.snapshot_retention_days),
    )
    hot_only = _resolve_hot_only(args)
    t0 = time.perf_counter()
    if args.snapshot_load:
        payload = snap_store.load_raw(args.snapshot_load)
        store, amap, use, src = load_snapshot_into_map(
            payload, backend=args.backend
        )
        print(f"loaded snapshot={args.snapshot_load}  dens={len(amap.density)}")
    else:
        store, amap, use, src = build_map(
            limit=args.limit,
            grid=args.grid,
            hot_only=hot_only,
            prop=args.prop,
            offline_demo=args.offline_demo,
            cache=args.cache,
            backend=args.backend,
            minutes=args.minutes,
            arch_cap=not bool(args.no_arch_cap),
            fleet=str(getattr(args, "fleet", None) or "starlink"),
            country=getattr(args, "country", None),
            satcat=not bool(getattr(args, "no_satcat", False)),
        )
    dt = time.perf_counter() - t0
    return store, amap, use, src, snap_store, dt


def _print_map_summary(amap, use, src, args, dt: float) -> None:
    summ = amap.summary()
    fleet = str(getattr(args, "fleet", None) or "starlink")
    print(
        f"TLE source={src}  fleet={fleet}  using={len(use)}  grid={args.grid}°  "
        f"prop={summ['prop']} sgp4={summ['sgp4']} hot_only={summ['hot_only']}"
    )
    print("---")
    print(
        f"sats={summ['sats']}  cells={summ['cells']}  "
        f"hot_cells={summ['hot_cells']}  warm={summ['warm_cells']}"
    )
    if summ.get("fleets"):
        print(f"fleets={summ['fleets']}")
    if summ.get("countries"):
        print(f"countries={summ['countries']}")
    print(f"shells={summ['shells']}")
    print(f"max_cell={summ['max_cell']}")
    print(
        f"prop_ms={summ['prop_ms']:.1f}  prop_errors={summ['prop_errors']}  "
        f"state_changes={summ['state_changes']}"
    )
    print(f"store={summ['store']}")
    print(f"elapsed={dt:.2f}s")


def cmd_weather(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="main.py weather",
        description="Public NOAA SWPC space weather (engine.solar)",
    )
    _add_solar_net_args(ap)
    args = ap.parse_args(list(argv))
    snap = get_space_weather(force=bool(args.force), offline=bool(args.offline))
    print(_json_out(snap.as_dict()))
    return 0


def cmd_predict(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="main.py predict",
        description="H3 horizon forecasts 1h/6h/24h (engine.solar.predict)",
    )
    _add_solar_net_args(ap)
    ap.add_argument(
        "--prop",
        type=float,
        default=None,
        metavar="MIN",
        dest="prop_minutes",
        help="optional forward-prop context minutes (stored in JSON)",
    )
    args = ap.parse_args(list(argv))
    wx, series = get_space_weather_bundle(
        force=bool(args.force), offline=bool(args.offline)
    )
    pred = predict_horizons(
        wx, series=series, prop_minutes=args.prop_minutes
    )
    print(short_horizon_line(pred))
    print(_json_out(pred.as_dict()))
    return 0


def cmd_hazard(argv: Sequence[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="main.py hazard",
        description="Solar hazard proxy on map (engine.solar.hazard)",
    )
    _add_map_args(ap)
    _add_solar_net_args(ap)
    ap.add_argument(
        "--with-predict",
        action="store_true",
        help="also print H3 horizons after hazard",
    )
    args = ap.parse_args(list(argv))
    try:
        store, amap, use, src, _snap_store, dt = _build_or_load(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: --offline-demo / --snapshot-load", file=sys.stderr)
        return 2
    for _ in range(max(0, args.ticks)):
        store.tick()
    _print_map_summary(amap, use, src, args, dt)

    wx, series = get_space_weather_bundle(
        force=bool(args.force), offline=bool(args.offline)
    )
    haz = assess_from_amap(amap, wx)
    print("--- hazard ---")
    print(short_badge(haz))
    print(_json_out(haz.as_dict()))
    if args.with_predict:
        pred = predict_horizons(wx, series=series)
        print("--- predict ---")
        print(short_horizon_line(pred))
        print(_json_out(pred.as_dict()))
    return 0


def cmd_report(argv: Sequence[str]) -> int:
    """H4: HazardReport JSON/MD + optional snapshot with solar meta."""
    ap = argparse.ArgumentParser(
        prog="main.py report",
        description="H4 HazardReport JSON/MD (engine.solar.report)",
    )
    _add_map_args(ap)
    _add_solar_net_args(ap)
    ap.add_argument(
        "--no-predict",
        action="store_true",
        help="skip H3 horizons in report",
    )
    ap.add_argument(
        "--json",
        nargs="?",
        const="out/hazard_report.json",
        default=None,
        metavar="PATH",
        help="write JSON report (default out/hazard_report.json)",
    )
    ap.add_argument(
        "--md",
        nargs="?",
        const="out/hazard_report.md",
        default=None,
        metavar="PATH",
        help="write Markdown report (default out/hazard_report.md)",
    )
    ap.add_argument(
        "--print-md",
        action="store_true",
        help="print Markdown to stdout (default: print JSON)",
    )
    ap.add_argument(
        "--save-snapshot",
        action="store_true",
        help="also save map snapshot with solar meta attached",
    )
    args = ap.parse_args(list(argv))
    try:
        store, amap, use, src, snap_store, dt = _build_or_load(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: --offline-demo / --snapshot-load", file=sys.stderr)
        return 2
    for _ in range(max(0, args.ticks)):
        store.tick()
    _print_map_summary(amap, use, src, args, dt)

    report = collect_solar_for_map(
        amap,
        offline=bool(args.offline),
        force=bool(args.force),
        with_predict=not bool(args.no_predict),
        src=src,
    )
    print("--- report ---")
    print(report.badge)
    if report.horizon_line:
        print(report.horizon_line)

    if args.print_md:
        print(report.as_markdown())
    else:
        print(_json_out(report.as_dict()))

    if args.json is not None:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"json: {path.resolve()}")
    if args.md is not None:
        path = Path(args.md)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.as_markdown(), encoding="utf-8")
        print(f"md: {path.resolve()}")

    if args.save_snapshot or args.snapshot_save is not None:
        sid = None
        if args.snapshot_save is not None and args.snapshot_save != "__auto__":
            sid = args.snapshot_save
        meta = snap_store.save(
            amap,
            snapshot_id=sid,
            src=src,
            using=len(use),
            solar=report.solar_meta(),
        )
        print(
            f"snapshot-save: {meta.snapshot_id}  solar=yes  "
            f"cells={meta.cells_count} → {meta.path}"
        )
    return 0


def cmd_timeline(argv: Sequence[str]) -> int:
    """B: snapshot timeline + optional compare."""
    ap = argparse.ArgumentParser(
        prog="main.py timeline",
        description="B snapshot timeline / density compare",
    )
    ap.add_argument(
        "--snapshot-dir",
        type=str,
        default="out/snapshots",
        help="snapshot directory",
    )
    ap.add_argument("--limit", type=int, default=30, help="max frames")
    ap.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        default=None,
        help="compare two snapshot ids",
    )
    args = ap.parse_args(list(argv))
    from adapters.snapshot_store import SnapshotStore
    from engine.analytics import compare_density, timeline_from_store

    store = SnapshotStore(Path(args.snapshot_dir), retention_days=0)
    if args.compare:
        a_id, b_id = args.compare
        pa, pb = store.load_raw(a_id), store.load_raw(b_id)
        print("--- compare ---")
        print(_json_out(compare_density(pa, pb)))
        return 0
    rows = timeline_from_store(store, limit=int(args.limit))
    print(f"--- timeline n={len(rows)} dir={store.root} ---")
    for r in rows:
        print(
            f"{r.get('created_at', ''):22}  {r.get('snapshot_id', ''):28}  "
            f"cells={r.get('cells', '—')}  Σ={r.get('sum_count', '—')}  "
            f"max={r.get('max_count', '—')}  haz={r.get('hazard_score', '—')}"
        )
    print(_json_out({"n": len(rows), "frames": rows}))
    return 0


def cmd_fleets(argv: Sequence[str]) -> int:
    """H7: list public catalog fleets."""
    ap = argparse.ArgumentParser(
        prog="main.py fleets",
        description="H7 list public Celestrak fleets",
    )
    ap.parse_args(list(argv))
    from engine.catalogs import list_fleets

    rows = list_fleets()
    print(f"public fleets ({len(rows)}) — Celestrak GP, no API key")
    for r in rows:
        print(f"  {r['id']:12}  {r['label']:20}  {r['note']}")
    print()
    print("usage:  python main.py --fleet oneweb --limit 200")
    print("merge:  python main.py --fleet starlink,oneweb --limit 400")
    print("studio: python main.py studio --fleet iridium --offline-demo --limit 40")
    return 0


def cmd_geo(argv: Sequence[str]) -> int:
    """H5: altitude bands + sunlit fraction."""
    ap = argparse.ArgumentParser(
        prog="main.py geo",
        description="H5 alt-band + sunlit fraction (engine.solar.geo)",
    )
    _add_map_args(ap)
    args = ap.parse_args(list(argv))
    try:
        store, amap, use, src, _snap, dt = _build_or_load(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: --offline-demo / --snapshot-load", file=sys.stderr)
        return 2
    for _ in range(max(0, args.ticks)):
        store.tick()
    _print_map_summary(amap, use, src, args, dt)
    geo = assess_geo_from_amap(amap)
    print("--- geo ---")
    print(short_geo_line(geo))
    print(_json_out(geo.as_dict()))
    return 0


def _run_rpc_and_snapshots(args: argparse.Namespace, snap_store) -> Optional[int]:
    """Handle early-exit snapshot/rpc ops. Returns exit code or None to continue."""
    if args.rpc_health:
        from adapters.cynober_rpc import CynoberRpcBridge, CynoberRpcError, rpc_status_dict

        print(_json_out(rpc_status_dict()))
        try:
            with CynoberRpcBridge.from_env(
                host=args.rpc_host,
                port=args.rpc_port,
                profile=args.rpc_profile,
                world=args.rpc_world,
            ) as br:
                h = br.health()
                print(_json_out(h))
                return 0 if h.get("status") == "ok" else 1
        except CynoberRpcError as e:
            print(f"rpc-health: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"rpc-health: {e}", file=sys.stderr)
            return 2

    if args.rpc_pull:
        from adapters.cynober_rpc import CynoberRpcBridge, CynoberRpcError

        try:
            with CynoberRpcBridge.from_env(
                host=args.rpc_host,
                port=args.rpc_port,
                profile=args.rpc_profile,
                world=args.rpc_world,
            ) as br:
                payload = br.pull_payload(args.rpc_pull)
            sid = str(payload.get("snapshot_id") or args.rpc_pull)
            path = snap_store._path(sid)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(
                f"rpc-pull: {sid}  cells={len(payload.get('density') or [])} → {path}"
            )
            return 0
        except CynoberRpcError as e:
            print(f"rpc-pull: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"rpc-pull: {e}", file=sys.stderr)
            return 2

    if args.snapshot_list:
        items = snap_store.list()
        if not items:
            print(f"(brak snapshotów w {snap_store.root})")
            return 0
        for m in items:
            print(
                f"{m.snapshot_id}  cells={m.cells_count} sats={m.sats_count} "
                f"v={m.version}  {m.created_at}  src={m.src}"
            )
        return 0
    return None


def cmd_run(argv: Sequence[str], *, studio: bool = False) -> int:
    prog = "main.py studio" if studio else "main.py"
    desc = (
        "Karmin Satellite HTTP UI"
        if studio
        else "One-shot Starlink map build (default command)"
    )
    ap = argparse.ArgumentParser(prog=prog, description=desc)
    _add_map_args(ap)
    if studio:
        _add_studio_args(ap)
    else:
        # allow legacy ``--studio`` on default run for one release
        ap.add_argument(
            "--studio",
            action="store_true",
            help=argparse.SUPPRESS,
        )
        _add_studio_args(ap)

    args = ap.parse_args(list(argv))
    want_studio = studio or bool(getattr(args, "studio", False))

    from adapters.snapshot_store import SnapshotStore

    snap_store = SnapshotStore(
        Path(args.snapshot_dir),
        retention_days=int(args.snapshot_retention_days),
    )
    early = _run_rpc_and_snapshots(args, snap_store)
    if early is not None:
        return early

    try:
        store, amap, use, src, snap_store, dt = _build_or_load(args)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: --offline-demo / --snapshot-load", file=sys.stderr)
        return 2

    for _ in range(max(0, args.ticks)):
        store.tick()
    _print_map_summary(amap, use, src, args, dt)

    last_snap_id: Optional[str] = None
    if args.snapshot_save is not None:
        sid = None if args.snapshot_save == "__auto__" else args.snapshot_save
        meta = snap_store.save(
            amap,
            snapshot_id=sid,
            src=src,
            using=len(use),
            attach_solar=True,
            solar_offline=bool(getattr(args, "offline_demo", False)),
        )
        last_snap_id = meta.snapshot_id
        print(
            f"snapshot-save: {meta.snapshot_id}  cells={meta.cells_count} "
            f"→ {meta.path}"
        )

    if args.rpc_push is not None:
        from adapters.cynober_rpc import CynoberRpcBridge, CynoberRpcError

        push_id = None if args.rpc_push == "__auto__" else args.rpc_push
        if push_id is None:
            if last_snap_id:
                push_id = last_snap_id
            else:
                meta = snap_store.save(
                    amap,
                    src=src,
                    using=len(use),
                    include_sats=bool(args.rpc_include_sats),
                )
                push_id = meta.snapshot_id
                print(f"snapshot-save (for rpc): {push_id} → {meta.path}")
        try:
            with CynoberRpcBridge.from_env(
                host=args.rpc_host,
                port=args.rpc_port,
                profile=args.rpc_profile,
                world=args.rpc_world,
            ) as br:
                result = br.push_from_local_store(
                    snap_store,
                    push_id,
                    include_sats=bool(args.rpc_include_sats),
                )
            print(
                f"rpc-push: {result.snapshot_id}  atom={result.atom_id}  "
                f"bytes={result.bytes_sent}  cells={result.cells}  "
                f"world={result.world or '-'}"
            )
        except CynoberRpcError as e:
            print(f"rpc-push: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"rpc-push: {e}", file=sys.stderr)
            return 2

    if want_studio:
        from ui.app import StudioState, run_studio

        state = StudioState(
            amap=amap,
            catalog=list(use),
            src=src,
            using=len(use),
            limit=int(args.limit or 0),
            offline_demo=bool(args.offline_demo),
            cache=args.cache,
            cache_ttl_hours=float(args.cache_ttl_hours),
            studio_mode=str(args.studio_mode or "2d"),
            fleet=str(getattr(args, "fleet", None) or "starlink"),
            country=str(getattr(args, "country", None) or ""),
        )
        if args.live_feed:
            state.attach_feeder(
                interval_sec=float(args.interval),
                reload_tle=not bool(args.offline_demo),
                refresh_first=False,
            )
            print(
                f"live-feed ON  interval={args.interval}s  "
                f"reload_tle={not args.offline_demo}"
            )
        return run_studio(
            state,
            host=args.host,
            port=args.port,
            open_browser=bool(args.open_browser),
        )

    heat_path: Optional[Path] = None
    if not args.no_heatmap:
        heat_path = render_heatmap_png(amap, Path(args.heatmap))
        print(f"heatmap: {heat_path.resolve()}")

    if args.live > 0:
        period = 1.0 / max(args.hz, 0.05)
        print(f"--- live {args.live}× @ {args.hz} Hz ---")
        for i in range(args.live):
            time.sleep(period)
            info = amap.refresh(use)
            if not args.no_heatmap:
                render_heatmap_png(amap, Path(args.heatmap))
            print(
                f"  [{i+1}/{args.live}] bins={info['bins']} hot={info['hot']} "
                f"prop_ms={info['prop_ms']:.1f} err={info['errors']}"
            )
            if not args.no_heatmap:
                heat_path = Path(args.heatmap)

    if args.html:
        if heat_path is None and not args.no_heatmap and Path(args.heatmap).is_file():
            heat_path = Path(args.heatmap)
        if heat_path is None and not args.no_heatmap:
            heat_path = render_heatmap_png(amap, Path(args.heatmap))
        payload = export_report_payload(
            amap,
            src=src,
            using=len(use),
            elapsed_s=dt,
            heatmap_path=heat_path,
        )
        html_path = write_html_report(payload, Path(args.html))
        json_side = html_path.with_suffix(".json")
        print(f"html: {html_path.resolve()}")
        print(f"json: {json_side.resolve()}")
        if args.open_html:
            try:
                import webbrowser

                webbrowser.open(html_path.resolve().as_uri())
            except Exception as e:
                print(f"open-html: {e}", file=sys.stderr)

    if args.lua or args.lua_hot:
        tool = "starlink_hot" if args.lua_hot else "starlink"
        isolated = not args.lua_shared
        print(f"--- lua :tool {tool}  isolate={isolated} ---")
        try:
            lua_out = run_lua_tool_name(
                store,
                tool,
                amap=amap,
                isolated=isolated,
                copy_sats=args.lua_copy_sats,
            )
            print(lua_out)
        except Exception as e:
            print(f"Lua tool error: {e}", file=sys.stderr)
            return 1
        if lua_out.startswith("(brak") or lua_out.startswith("(Lua bridge"):
            print("Lua tool unavailable — not a successful run.", file=sys.stderr)
            return 1
        cat_after = store.stats() if callable(getattr(store, "stats", None)) else {}
        print(
            f"catalog after lua: total={cat_after.get('total')} "
            f"alive={cat_after.get('alive')} bubbles={cat_after.get('bubbles')}"
        )

    print("OK plan: multi-task Store = sats + cells + bubbles + heat + optional Lua")
    return 0


def _print_top_help() -> int:
    print(
        """Karmin Satellite

Usage:
  python main.py weather [--offline] [--force]
  python main.py predict [--offline] [--force] [--prop MIN]
  python main.py hazard  [map opts] [--offline] [--with-predict]
  python main.py report  [map opts] [--offline] [--json] [--md] [--save-snapshot]
  python main.py geo     [map opts]              # H5 alt-band + sunlit
  python main.py fleets                          # H7 list public catalogs
  python main.py timeline [--compare A B]        # B snapshot timeline
  python main.py studio  [map opts] [--fleet F] [--country US] [--open-browser]
  python main.py         [map opts]              # one-shot map (default)
  python main.py run     [map opts]              # same as default

Solar (engine.solar):
  weather   NOAA SWPC F10.7 / X-ray / Kp
  predict   H3 horizons 1h / 6h / 24h
  hazard    group scores on a built map
  report    H4 HazardReport JSON/MD + optional snapshot solar meta
  geo       H5 altitude bands + sunlit fraction
  fleets    H7 public Celestrak fleet list
  timeline  B snapshot density timeline / compare

Map / studio (examples):
  python main.py --offline-demo --limit 40 --no-heatmap
  python main.py --fleet oneweb --limit 200
  python main.py --fleet starlink --country US --limit 200
  python main.py --fleet starlink,oneweb --limit 400
  python main.py studio --offline-demo --limit 40 --open-browser
  python main.py hazard --offline-demo --limit 40 --offline
  python main.py report --offline-demo --limit 40 --offline --md --json
  python main.py geo --offline-demo --limit 40 --no-heatmap
  python main.py fleets
  python main.py timeline
  python main.py timeline --compare snap_A snap_B
"""
    )
    return 0


def _split_command(argv: Optional[Sequence[str]]) -> tuple[str, List[str]]:
    """Return (command, rest). Default command is 'run'."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        return "help", args
    if args[0] in TOP_CMDS:
        return args[0], args[1:]
    # bare map flags → run
    return "run", args


def main(argv: Optional[Sequence[str]] = None) -> int:
    cmd, rest = _split_command(argv)
    if cmd == "help":
        return _print_top_help()
    if cmd == "weather":
        return cmd_weather(rest)
    if cmd == "predict":
        return cmd_predict(rest)
    if cmd == "hazard":
        return cmd_hazard(rest)
    if cmd == "report":
        return cmd_report(rest)
    if cmd == "geo":
        return cmd_geo(rest)
    if cmd == "fleets":
        return cmd_fleets(rest)
    if cmd == "timeline":
        return cmd_timeline(rest)
    if cmd == "studio":
        return cmd_run(rest, studio=True)
    if cmd == "run":
        return cmd_run(rest, studio=False)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
