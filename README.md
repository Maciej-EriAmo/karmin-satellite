# Cynober Studio

**Private product** — visual studio for thermal atoms (Starlink and other mass object maps).

Standalone like **Cynober DB**: own substrate + engine. **KarmazynOs is optional** later (native slab, Lua tools).

**Architecture scale (measured):** **50 000** usable · **100 000** ceiling.  
Canon: [`docs/ARCHITECTURE_LIMITS.md`](docs/ARCHITECTURE_LIMITS.md) · baseline JSON: [`docs/capacity_baseline.json`](docs/capacity_baseline.json).  
**50k SLA (design contract, PL+EN):** [`docs/SLA_50K.md`](docs/SLA_50K.md) · code `engine/sla.py` · `GET /api/sla`.  
CLI default sample **400**. Re-run: `python tests\test_capacity.py` (add `CYNOBER_CAPACITY_CEILING=1` for 100k).

## Layout

```
cynober_studio/
├── main.py
├── substrate/              # pure-Python thermal atom store
├── engine/                 # modular engine
│   ├── tle.py · prop.py · grid.py · map.py
│   ├── export_2d.py · build.py · cli.py · live_feeder.py
│   └── starlink_atoms.py   # facade (compat)
├── transform/
│   └── sphere.py           # S2b 3D quads
├── ui/                     # HTTP + 2D/3D
├── docs/
├── out/
└── tests/
```

## Quick start

```bat
cd /d C:\Users\drwis\cynober_studio
python -m pip install -r requirements.txt
python main.py --offline-demo --limit 40 --hot-only
python main.py --limit 400 --prop sgp4 --hot-only --html
```

## Studio UI (Faza 2–3)

```bat
python main.py --offline-demo --limit 40 --studio --open-browser
python main.py --offline-demo --limit 40 --studio --studio-mode 3d --open-browser
:: live feed (interval w sekundach; 15 min = 900)
python main.py --offline-demo --limit 40 --studio --live-feed --interval 30 --open-browser
:: http://127.0.0.1:8765/  ·  ?mode=3d
```

| Endpoint | Opis |
|----------|------|
| `GET /` | UI 2D/3D + filtry |
| `GET /api/version` | `{version, sla_version, design_sats}` |
| `GET /api/sla` | kontrakt SLA 50k (machine-readable) |
| `GET /api/data` | `snapshot()` + nlat/nlon + feeder (cells-scale) |
| `GET /api/sphere` | S2b sphere quads (3D) |
| `GET /api/filter?shell=&min_count=` | S4b |
| `POST /api/refresh` | `{minutes, reload_tle}` |
| `GET /api/feeder` | status live feedera |
| `POST /api/feeder/stop` · `start` | sterowanie feedera |
| `GET /api/snapshots` | lista snapshotów |
| `POST /api/snapshot/save` · `load` | S1b lokalny store |

stdlib only (no Flask). Quality notes: `docs/CODE_REVIEW.md`.

### Snapshots (Faza 5)

```bat
python main.py --offline-demo --limit 40 --snapshot-save
python main.py --snapshot-list
python main.py --snapshot-load snap_YYYYMMDD... --no-heatmap
```

Pliki: `out/snapshots/*.json` (gitignore). Nie wymaga działającego serwera Cynober.

## Tests & bench (Faza 0–2)

```bat
python -m unittest discover -s tests -v
python tests\test_bench.py
:: → out/bench.json
```

Engine contract (Studio-ready):

- `StarlinkAtomMap.snapshot()` — spójny widok pod UI
- `filter_density(shell=…, min_count=…)` — S4b backend
- `refresh(..., ensure=True)` — upsert + GC satów + `version++`
- `density_cell_consistency()` — hot-only density ↔ cell atoms

Full catalog (needs network for Celestrak TLE, or cache under `out/`):

```bat
python main.py --limit 0 --prop sgp4 --hot-only --html out/starlink_report.html
```

## Architecture (target)

See `docs/CYNOBER_STUDIO_PLAN.md` and audit `docs/CYNOBER_STUDIO_AUDIT.md`.

Recommended MVP path:

| Layer | Choice |
|-------|--------|
| S1 substrate | Pure-Python store here; Karmin/DB snapshots later (S1b) |
| S2 visual | 2D heatmap first → 3D globe |
| S3 data | One-shot → live feed with locks |
| S4 UI | Query & filter |

## Relation to other trees

| Path | Role |
|------|------|
| `C:\Users\drwis\cynober_studio` | **This product** (primary) |
| `C:\Users\drwis\DBase` | Cynober DB / Karmin_DB (skarbiec) |
| `C:\Users\drwis\KarmazynOs` | Optional OS runtime; set `KARMAZYN_OS` for Lua bridge |
| `C:\Users\drwis\Karmin_Ae` | Agent SE memory (Holon), not runtime |

## License

Private — all rights reserved. Not for public visitors.
