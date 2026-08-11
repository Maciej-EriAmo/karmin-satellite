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
├── docs/
│   ├── CYNOBER_STUDIO_PLAN.md
│   ├── CYNOBER_STUDIO_AUDIT.md
│   └── STARLINK_ATOMS.md
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
