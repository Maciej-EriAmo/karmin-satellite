# Karmin Satellite

Visual research studio for thermal atoms on public satellite catalogs (Starlink and multi-fleet).  
**License:** [MIT](LICENSE).

> Formerly **Cynober Studio** (`cynober_studio`). Repo: [Maciej-EriAmo/karmin-satellite](https://github.com/Maciej-EriAmo/karmin-satellite).  
> Path: `C:\Users\drwis\karmin-satellite`. Data dir: `%LOCALAPPDATA%\KarminSatellite` (legacy `CynoberStudio` auto-renamed).

Standalone like **Cynober DB**: own substrate + engine. **KarmazynOs is optional** (native slab, Lua tools).

**Architecture scale (measured):** **50 000** usable · **100 000** ceiling.  
Canon: [`docs/ARCHITECTURE_LIMITS.md`](docs/ARCHITECTURE_LIMITS.md) · baseline: [`docs/capacity_baseline.json`](docs/capacity_baseline.json).  
**50k SLA:** [`docs/SLA_50K.md`](docs/SLA_50K.md) · `engine/sla.py` · `GET /api/sla`.  
CLI default sample **400**. Capacity: `python tests\test_capacity.py`.

## Docs map

| Doc | Content |
|-----|---------|
| [`docs/USER_GUIDE.en.md`](docs/USER_GUIDE.en.md) | User guide (all UI + CLI) |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Instrukcja obsługi (PL) |
| [`docs/CLI.md`](docs/CLI.md) | Full CLI subcommands & flags |
| [`docs/HAZARD_LAYER.md`](docs/HAZARD_LAYER.md) | Solar H0–H8 · multi-fleet H7 · UX |
| [`docs/STARLINK_ATOMS.md`](docs/STARLINK_ATOMS.md) | Engine contract & layout |
| [`docs/SLA_50K.md`](docs/SLA_50K.md) | Scale budgets |
| [`docs/KARMIN_SATELLITE_VERIFIED_PLAN.md`](docs/KARMIN_SATELLITE_VERIFIED_PLAN.md) | Roadmap / status |
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | Status · **COMPLETE** |
| [`docs/REACH_STUDIO.md`](docs/REACH_STUDIO.md) | Session reach · flags · law (density vs view) |
| [`docs/DELTA_VIEW.md`](docs/DELTA_VIEW.md) | **Delta View** — only changes (vanished/grew · hazard · live log) |

## Layout

```
karmin-satellite/
├── main.py
├── substrate/                 # pure-Python thermal atom store
├── engine/
│   ├── tle.py · prop.py · grid.py · map.py · build.py
│   ├── catalogs.py            # H7 Celestrak fleets
│   ├── solar/                 # H0–H5 weather · hazard · predict · report · geo
│   ├── export_2d.py · cli.py · live_feeder.py · sla.py
│   ├── reach_studio.py        # session reach · ghost · impact · live root
│   └── starlink_atoms.py      # facade
├── transform/sphere.py        # 3D quads + radiation layers
├── ui/                        # HTTP Studio 2D/3D
├── adapters/                  # snapshots · optional Cynober RPC · shims
├── docs/
├── out/                       # caches, snapshots (gitignore)
└── tests/
```

## Quick start

```bat
cd /d C:\Users\drwis\karmin-satellite
python -m pip install -r requirements.txt

:: Studio UI (normal — Celestrak / cache, opens browser)
python main.py studio
python main.py studio --limit 12000
python main.py studio --fleet oneweb --limit 200
python main.py studio --fleet debris --limit 400

:: offline smoke only (synthetic TLE, no network)
python main.py studio --offline-demo --limit 40
python main.py --offline-demo --limit 40 --hot-only --no-heatmap

:: multi-fleet list
python main.py fleets
```

Top-level help: `python main.py --help` · details: [`docs/CLI.md`](docs/CLI.md).

## CLI overview

| Command | Role |
|---------|------|
| *(default)* | One-shot map / heatmap / snapshot |
| `studio` | HTTP UI 2D/3D |
| `weather` · `predict` · `hazard` · `report` · `geo` | Solar / geo research tools |
| `fleets` | List public catalogs |

```bat
python main.py weather --offline
python main.py predict --offline
python main.py hazard --offline-demo --limit 40 --offline --no-heatmap
python main.py report --offline-demo --limit 40 --offline --json --md
python main.py geo --offline-demo --limit 40 --no-heatmap
python main.py --fleet starlink,oneweb --limit 40 --offline-demo --no-heatmap
```

## Studio UI

```bat
python main.py studio
python main.py studio --studio-mode 3d --live-feed --interval 30
:: http://127.0.0.1:8765/  ·  ?mode=3d
:: no network: python main.py studio --offline-demo --limit 40
```

**Workflow:** live map → fleet / shell filter → 2D/3D layers → **Save** frame → Library **Load** → Analyze → solar panels → optional Push DB.

| UI | Notes |
|----|--------|
| 2D layers | Density / Hazard / Blend |
| 3D layers | Density / Radiation / Blend · large globe |
| Edge aura | Vignette on map/globe ∝ solar stress |
| Adaptive px | Few sats → coarse blocks; many → fill panel, sharp |
| Horizons | 1h / 6h / 24h |
| Alt / sunlit | Bands + sunlit fraction |
| Fleet | Public Celestrak picker + Load fleet |

### HTTP API

| Endpoint | Opis |
|----------|------|
| `GET /` | UI 2D/3D |
| `GET /api/version` · `/api/sla` | version + 50k contract |
| `GET /api/data` | snapshot density (cells-scale) + `fleet` |
| `GET /api/sphere?layer=` | `density` \| `radiation` \| `blend` |
| `GET /api/filter?shell=&min_count=` | shell filter |
| `POST /api/refresh` | `{minutes, reload_tle}` |
| `GET /api/feeder` · `POST …/start\|stop` | live feeder |
| `GET /api/snapshots` · `POST …/save\|load` | Library |
| `GET /api/analyze` | density metrics (+ geo) |
| `GET /api/weather` · `/hazard` · `/predict` · `/report` · `/geo` | solar stack |
| `GET /api/fleets` · `POST /api/fleet` | multi-fleet |
| `GET /api/reach` · `POST /api/session` | session reach / scope |
| `GET /api/ghost` · `POST …/demo` | retained / cold in reach |
| `POST /api/impact` | cooling impact (simulate default) |
| `GET /api/resonance` · `POST /api/system_tick` | HRR browse · decisions |
| `GET/POST /api/attention` | live root · commit vacuum · restore |
| `GET /api/export` | JSON / MD download |
| `GET /api/alert` | EM storm watch (public Kp/flare now or 6h) |
| `POST /api/rpc/push` · `pull` | optional Cynober DB |

stdlib only (no Flask). Quality: [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md).

### Space weather & fleets (research)

Public **NOAA SWPC** + **Celestrak TLE** only. Proxies ≠ mission certification.

Modules: `engine/solar/*` · `engine/catalogs.py`.  
Canon: [`docs/HAZARD_LAYER.md`](docs/HAZARD_LAYER.md).

### Snapshots

```bat
python main.py --offline-demo --limit 40 --snapshot-save
python main.py --snapshot-list
python main.py --snapshot-load snap_YYYYMMDD... --no-heatmap
```

Files: `out/snapshots/*.json` (gitignore). Save attaches **`solar`** meta by default.

### Delta View (changes only)

See [`docs/DELTA_VIEW.md`](docs/DELTA_VIEW.md). UI: **Delta** mode · Arm baseline · Live Δ · Change log.  
Vanished cells / optional NORAD loss = research proxy (e.g. post-flare fleet thinning) — **not** SSA collisions.

```bat
python main.py studio
:: then: Save ≥2 snapshots → Compare newest, or Arm baseline → refresh → Live Δ
```

### Optional Cynober DB RPC

Local snapshots stay primary. Optional density-first push/pull over **Cynober-Secure**.

**Requires cynober-db ≥ 8.2.5** (`pip install -U "cynober-db>=8.2.5"` or `CYNOBER_DB` → DBase tree).  
Do **not** use PyPI **8.2.4** (broken wheel: missing `cynober_paths`).

```bat
python main.py --rpc-health
python main.py --offline-demo --limit 40 --snapshot-save --rpc-push
python main.py --rpc-pull snap_YYYYMMDD...
```

Env:

| Variable | Role |
|----------|------|
| `CYNOBER_HOST` / `CYNOBER_PORT` | Direct endpoint (default port 8080) |
| `CYNOBER_PROFILE` | `~/.karmazyn_client.json` profile |
| `CYNOBER_WORLD` | `WYBIERZ ŚWIAT` after connect |
| `CYNOBER_USER` / `CYNOBER_TOKEN` | `ZALOGUJ` when server `auth.json` is enabled |
| `CYNOBER_RPC=0` | Disable bridge even if client importable |
| `CYNOBER_DB` / `DBASE_PATH` | Dev path to DBase sources |

Code: `adapters/cynober_rpc.py` · status: `GET /api/rpc/status` (`min_cynober_db`, `auth_configured`).

## Tests

```bat
python run_tests.py
python tests\test_bench.py
python tests\test_capacity.py
```

`run_tests.py` loads `tests/test_*.py` by path so a site-packages `tests` package cannot shadow the suite. Capacity / bench stay optional (scale).

Engine contract:

- `snapshot()` · `filter_density` · `refresh(ensure=True)` · `density_cell_consistency()`
- `summary()` includes `shells` + `fleets`
- `load_catalog(fleet=…)` multi-fleet merge

Full catalog (network or cache):

```bat
python main.py --limit 0 --prop sgp4 --hot-only --html out/starlink_report.html
```

## Relation to other trees

| Path | Role |
|------|------|
| `C:\Users\drwis\karmin-satellite` | **This product** |
| `C:\Users\drwis\DBase` | Cynober DB / Karmin_DB (skarbiec) |
| `C:\Users\drwis\KarmazynOs` | Optional OS runtime (`KARMAZYN_OS` for Lua) |
| `C:\Users\drwis\Karmin_Ae` | Agent SE memory (Holon), not runtime |

## License

Private — all rights reserved. Not for public visitors.
