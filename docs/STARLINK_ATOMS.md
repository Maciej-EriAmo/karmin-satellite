# Starlink on thermal atoms — Cynober Studio

**Project:** Cynober Studio · `engine/`  
**Status:** MVP complete (phases 0–5: engine, 2D/3D UI, live feed, snapshots)  
**Language of this doc:** English  
**Plan:** [CYNOBER_STUDIO_VERIFIED_PLAN.md](CYNOBER_STUDIO_VERIFIED_PLAN.md)

---

## Scale (architecture)

| | |
|---|---|
| **ARCH_MAX_SATS** | **12 000** — budżet produktu (pure-Python Store / jedna mapa) |
| **DEFAULT_LIMIT** | **400** — wygodny dev sample w CLI |
| **`--limit 0`** | cały TLE po parse, potem cap do 12 000 (wyłączenie: `arch_cap=False` / `--no-arch-cap`) |
| Public Starlink (typowo) | ~10–11 k w grupie Celestrak — **mieści się w 12 k** |

Planowe „50–100k” w starych notatkach to horyzont researchowy, **nie** limit v1 Studio.

## Goal

Show that **one atom substrate** can multi-task a real-scale public workload without a second database *in process* (snapshots are optional persistence):

| Concern | Same Store |
|---------|------------|
| Catalog | `starlink:sat` atoms (NORAD / TLE / lat·lon) |
| Heatmap | `starlink:cell` atoms — **temperature T = density** |
| Grouping | **bubbles** (`starlink`, `sats`, `grid`, `shell:*`) |
| Query / watch | list HOT·WARM, `state_changed` events |
| Studio UI | 2D canvas + optional 3D globe + filters |
| Persistence | local JSON snapshots (`out/snapshots/`) |

**Law (kernel):** temperature says *when*; reachability says *whether*.

This is **not** a Starlink ops competitor. It is a **substrate product**: constellation as load on thermal memory physics.

---

## Layout (this repo)

| Path | Role |
|------|------|
| `engine/tle.py` · `prop.py` · `grid.py` · `map.py` | Core engine (modular) |
| `engine/export_2d.py` · `cli.py` · `live_feeder.py` | Export, CLI, S3b feeder |
| `engine/starlink_atoms.py` | Compatibility facade |
| `transform/sphere.py` | S2b sphere quads |
| `ui/` | Studio HTTP + 2D/3D |
| `adapters/snapshot_store.py` | S1b local snapshots |
| `out/` | caches, PNG, HTML, snapshots (gitignored) |

**KarmazynOs** is optional (`KARMAZYN_OS` for Lua tools only).

---

## Quick start

```powershell
cd C:\Users\drwis\cynober_studio
pip install -r requirements.txt

# Offline smoke
python main.py --offline-demo --limit 40 --hot-only

# Studio UI (2D default; toggle 3D in UI or --studio-mode 3d)
python main.py --offline-demo --limit 40 --hot-only --studio --open-browser

# Live feed (interval seconds; 900 = 15 min)
python main.py --offline-demo --limit 40 --hot-only --studio --live-feed --interval 30

# Snapshot
python main.py --offline-demo --limit 40 --hot-only --snapshot-save
python main.py --snapshot-list
```

Dependencies: **sgp4**, **Pillow**. Substrate: pure-Python (`KARMAZYN_SUBSTRATE=python`).

---

## API (Studio)

| Endpoint | Role |
|----------|------|
| `GET /api/data` | snapshot density |
| `GET /api/sphere` | 3D quads |
| `GET /api/filter` | shell / min_count |
| `POST /api/refresh` | re-propagate |
| `GET /api/feeder` | live feeder status |
| `GET /api/snapshots` · `POST .../save|load` | local persistence |

---

## Tests

```powershell
python -m unittest discover -s tests -v
```

---

*Home: Cynober Studio · private repo Maciej-EriAmo/cynober_studio*
