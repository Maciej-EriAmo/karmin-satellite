"""CLI entry for engine (one-shot + studio flags)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from engine.bootstrap import ensure_paths

ensure_paths()

from engine.build import build_map
from engine.export_2d import export_report_payload, render_heatmap_png, write_html_report
from engine.lua_bridge import run_lua_tool_name

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Cynober Studio — Starlink thermal atoms (engine + optional UI)"
    )
    ap.add_argument("--limit", type=int, default=400, help="0 = cały katalog")
    ap.add_argument("--grid", type=float, default=5.0)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--heatmap", type=str, default="out/starlink_heat.png")
    ap.add_argument("--no-heatmap", action="store_true")
    ap.add_argument("--offline-demo", action="store_true")
    ap.add_argument("--cache", type=str, default="out/starlink_tle_cache.txt")
    ap.add_argument("--lua", action="store_true", help=":tool starlink (izolowany Store widoku)")
    ap.add_argument("--lua-hot", action="store_true", help="starlink_hot.lua")
    ap.add_argument(
        "--lua-shared",
        action="store_true",
        help="Lua na tym samym Store co katalog (stary tryb; miesza stats)",
    )
    ap.add_argument(
        "--lua-copy-sats",
        action="store_true",
        help="przy isolate: skopiuj też atomy sat (ciężkie; domyślnie tylko meta+cells)",
    )
    ap.add_argument("--ticks", type=int, default=0)
    ap.add_argument("--backend", choices=("python", "native", "default"), default="python")
    ap.add_argument(
        "--prop",
        choices=("auto", "sgp4", "approx"),
        default="auto",
        help="Faza 1: sgp4 (domyślnie auto)",
    )
    ap.add_argument(
        "--hot-only",
        action="store_true",
        help="Faza 2: tylko atomy komórek z count>0",
    )
    ap.add_argument(
        "--full-grid",
        action="store_true",
        help="wymusza pełną siatkę atomów (Faza 0)",
    )
    ap.add_argument("--live", type=int, default=0, help="liczba odświeżeń live (Faza 1)")
    ap.add_argument("--hz", type=float, default=1.0, help="częstotliwość live refresh")
    ap.add_argument(
        "--html",
        nargs="?",
        const="out/starlink_report.html",
        default=None,
        help="zapisz stronę HTML z wynikami i wizualizacją (domyślnie out/starlink_report.html)",
    )
    ap.add_argument(
        "--open-html",
        action="store_true",
        help="po --html otwórz w domyślnej przeglądarce",
    )
    ap.add_argument(
        "--studio",
        action="store_true",
        help="uruchom Cynober Studio HTTP UI (2D heatmap + API)",
    )
    ap.add_argument("--host", type=str, default="127.0.0.1", help="Studio bind host")
    ap.add_argument("--port", type=int, default=8765, help="Studio HTTP port")
    ap.add_argument(
        "--open-browser",
        action="store_true",
        help="po --studio otwórz przeglądarkę",
    )
    ap.add_argument(
        "--studio-mode",
        choices=("2d", "3d"),
        default="2d",
        help="domyślny widok Studio: 2d heatmap lub 3d globe",
    )
    ap.add_argument(
        "--live-feed",
        action="store_true",
        help="Faza 3: cykliczny refresh w tle (wymaga --studio lub działa z --live-feed-cli)",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=900.0,
        help="interwał live-feed w sekundach (domyślnie 900 = 15 min)",
    )
    ap.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=12.0,
        help="TTL cache TLE przy reload (godziny; 0 = zawsze bierz cache jeśli jest)",
    )
    ap.add_argument(
        "--snapshot-dir",
        type=str,
        default="out/snapshots",
        help="katalog snapshotów (Faza 5)",
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
        help="zapisz snapshot po build (opcjonalne id; domyślnie auto)",
    )
    ap.add_argument(
        "--snapshot-load",
        type=str,
        default=None,
        help="wczytaj snapshot zamiast TLE build (id bez .json)",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    from adapters.snapshot_store import SnapshotStore, load_snapshot_into_map

    snap_store = SnapshotStore(
        Path(args.snapshot_dir),
        retention_days=int(args.snapshot_retention_days),
    )

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

    if args.full_grid:
        hot_only = False
    elif args.hot_only:
        hot_only = True
    else:
        # auto: pełny katalog / duże limity → hot-only (Faza 2)
        hot_only = args.limit == 0 or args.limit >= 1000

    t0 = time.perf_counter()
    try:
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
            )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Hint: --offline-demo / --snapshot-load", file=sys.stderr)
        return 2

    for _ in range(max(0, args.ticks)):
        store.tick()

    summ = amap.summary()
    dt = time.perf_counter() - t0
    print(
        f"TLE source={src}  using={len(use)}  grid={args.grid}°  "
        f"prop={summ['prop']} sgp4={summ['sgp4']} hot_only={summ['hot_only']}"
    )
    print("---")
    print(
        f"sats={summ['sats']}  cells={summ['cells']}  "
        f"hot_cells={summ['hot_cells']}  warm={summ['warm_cells']}"
    )
    print(f"shells={summ['shells']}")
    print(f"max_cell={summ['max_cell']}")
    print(
        f"prop_ms={summ['prop_ms']:.1f}  prop_errors={summ['prop_errors']}  "
        f"state_changes={summ['state_changes']}"
    )
    print(f"store={summ['store']}")
    print(f"elapsed={dt:.2f}s")

    if args.snapshot_save is not None:
        sid = None if args.snapshot_save == "__auto__" else args.snapshot_save
        meta = snap_store.save(
            amap,
            snapshot_id=sid,
            src=src,
            using=len(use),
        )
        print(
            f"snapshot-save: {meta.snapshot_id}  cells={meta.cells_count} "
            f"→ {meta.path}"
        )

    if args.studio:
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
        # po live heatmapa może być świeższa
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
            print(
                run_lua_tool_name(
                    store,
                    tool,
                    amap=amap,
                    isolated=isolated,
                    copy_sats=args.lua_copy_sats,
                )
            )
        except Exception as e:
            print(f"Lua tool error: {e}", file=sys.stderr)
            return 1
        # katalog nienaruszony przez heap Lua
        cat_after = store.stats() if callable(getattr(store, "stats", None)) else {}
        print(
            f"catalog after lua: total={cat_after.get('total')} "
            f"alive={cat_after.get('alive')} bubbles={cat_after.get('bubbles')}"
        )

    print("OK plan: multi-task Store = sats + cells + bubbles + heat + optional Lua")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
