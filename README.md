# Cynober Studio

**Private product** — visual studio for thermal atoms (Starlink and other mass object maps).

Standalone like **Cynober DB**: own substrate + engine. **KarmazynOs is optional** later (native slab, Lua tools).

## Layout

```
cynober_studio/
├── main.py                 # CLI entry
├── substrate/              # pure-Python thermal atom store (vendored kernel)
├── engine/
│   └── starlink_atoms.py   # TLE → atoms → density → heatmap/HTML
├── ui/                     # Studio HTTP + 2D canvas
│   ├── app.py
│   ├── templates/
│   └── static/
├── docs/
├── out/                    # caches, PNG, HTML (gitignored)
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
:: live feed (interval w sekundach; 15 min = 900)
python main.py --offline-demo --limit 40 --studio --live-feed --interval 30 --open-browser
:: http://127.0.0.1:8765/
```

| Endpoint | Opis |
|----------|------|
| `GET /` | 2D heatmap + filtry |
| `GET /api/version` | `{version}` |
| `GET /api/data` | `snapshot()` + nlat/nlon + feeder |
| `GET /api/filter?shell=&min_count=` | S4b |
| `POST /api/refresh` | `{minutes, reload_tle}` |
| `GET /api/feeder` | status live feedera |
| `POST /api/feeder/stop` · `start` | sterowanie feedera |

stdlib only (no Flask). Quality notes: `docs/CODE_REVIEW.md`.

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
