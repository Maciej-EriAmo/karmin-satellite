# Cynober Studio

**Private product** — visual research studio for thermal atoms on public satellite catalogs (Starlink and multi-fleet).

Standalone like **Cynober DB**: own substrate + engine. **KarmazynOs is optional** (native slab, Lua tools).

**Architecture scale (measured):** **50 000** usable · **100 000** ceiling.  
Canon: [`docs/ARCHITECTURE_LIMITS.md`](docs/ARCHITECTURE_LIMITS.md) · baseline: [`docs/capacity_baseline.json`](docs/capacity_baseline.json).  
**50k SLA:** [`docs/SLA_50K.md`](docs/SLA_50K.md) · `engine/sla.py` · `GET /api/sla`.  
CLI default sample **400**. Capacity: `python tests\test_capacity.py`.

## Docs map

| Doc | Content |
|-----|---------|
| [`docs/CLI.md`](docs/CLI.md) | Full CLI subcommands & flags |
| [`docs/HAZARD_LAYER.md`](docs/HAZARD_LAYER.md) | Solar H0–H8 · multi-fleet H7 · UX |
| [`docs/STARLINK_ATOMS.md`](docs/STARLINK_ATOMS.md) | Engine contract & layout |
| [`docs/SLA_50K.md`](docs/SLA_50K.md) | Scale budgets |
| [`docs/CYNOBER_STUDIO_VERIFIED_PLAN.md`](docs/CYNOBER_STUDIO_VERIFIED_PLAN.md) | Roadmap / status |

## Layout

```
cynober_studio/
├── main.py
├── substrate/                 # pure-Python thermal atom store
├── engine/
│   ├── tle.py · prop.py · grid.py · map.py · build.py
│   ├── catalogs.py            # H7 Celestrak fleets
│   ├── solar/                 # H0–H5 weather · hazard · predict · report · geo
│   ├── export_2d.py · cli.py · live_feeder.py · sla.py
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
cd /d C:\Users\drwis\cynober_studio
python -m pip install -r requirements.txt

:: offline smoke
python main.py --offline-demo --limit 40 --hot-only --no-heatmap

:: Studio UI (subcommand preferred)
python main.py studio --offline-demo --limit 40 --open-browser
python main.py studio --limit 12000 --open-browser

:: multi-fleet
python main.py fleets
python main.py studio --fleet oneweb --limit 200 --open-browser
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
python main.py studio --offline-demo --limit 40 --open-browser
python main.py studio --studio-mode 3d --live-feed --interval 30 --open-browser
:: http://127.0.0.1:8765/  ·  ?mode=3d
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

### Optional Cynober DB RPC

Local snapshots stay primary. Optional density-first push/pull.

```bat
python main.py --rpc-health
python main.py --offline-demo --limit 40 --snapshot-save --rpc-push
python main.py --rpc-pull snap_YYYYMMDD...
```

Env: `CYNOBER_HOST` / `PORT` / `PROFILE` / `WORLD` · `CYNOBER_RPC=0` disables.  
Code: `adapters/cynober_rpc.py`.

## Tests

```bat
python -m unittest discover -s tests -v
python tests\test_bench.py
python tests\test_catalogs.py
```

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
| `C:\Users\drwis\cynober_studio` | **This product** |
| `C:\Users\drwis\DBase` | Cynober DB / Karmin_DB (skarbiec) |
| `C:\Users\drwis\KarmazynOs` | Optional OS runtime (`KARMAZYN_OS` for Lua) |
| `C:\Users\drwis\Karmin_Ae` | Agent SE memory (Holon), not runtime |

## License

Private — all rights reserved. Not for public visitors.
