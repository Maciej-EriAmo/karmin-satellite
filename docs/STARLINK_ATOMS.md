# Thermal atoms studio — engine contract

**Project:** Cynober Studio · `engine/`  
**Status:** MVP phases 0–5 + hazard H0–H8 + multi-fleet H7  
**Language of this doc:** English  
**Plan:** [CYNOBER_STUDIO_VERIFIED_PLAN.md](CYNOBER_STUDIO_VERIFIED_PLAN.md)  
**Solar / fleets:** [HAZARD_LAYER.md](HAZARD_LAYER.md) · **CLI:** [CLI.md](CLI.md)

---

## Scale (architecture)

**Canon:** [ARCHITECTURE_LIMITS.md](ARCHITECTURE_LIMITS.md) · [capacity_baseline.json](capacity_baseline.json) · [SLA_50K.md](SLA_50K.md)

| | |
|---|---|
| **ARCH_USABLE_SATS** | **50 000** — operating budget |
| **ARCH_CEILING_SATS** | **100 000** — hard cap |
| **DEFAULT_LIMIT** | **400** — dev sample CLI |
| Public fleets | Starlink ~10–11k; OneWeb / Iridium / … via Celestrak |

```bat
python tests\test_capacity.py
set CYNOBER_CAPACITY_CEILING=1
python tests\test_capacity.py
```

## Goal

Show that **one atom substrate** can multi-task a real-scale public workload without a second database *in process* (snapshots are optional persistence):

| Concern | Same Store |
|---------|------------|
| Catalog | `starlink:sat` atoms (NORAD / TLE / lat·lon · **fleet**) |
| Heatmap | `starlink:cell` atoms — **temperature T = density** |
| Grouping | bubbles (`starlink`, `sats`, `grid`, `shell:*`) |
| Solar | `engine/solar/*` — research proxies (not atoms) |
| Studio UI | 2D canvas + 3D globe + filters + fleet picker |
| Persistence | local JSON snapshots (`out/snapshots/`, optional `solar` meta) |

**Law (kernel):** temperature says *when*; reachability says *whether*.

This is **not** an ops SSA product. It is a **substrate + research workbench** for public constellation data.

---

## Layout (this repo)

| Path | Role |
|------|------|
| `engine/tle.py` · `prop.py` · `grid.py` · `map.py` | Core engine |
| `engine/catalogs.py` | H7 fleet registry (Celestrak) |
| `engine/solar/` | H0–H5 weather · hazard · predict · report · geo |
| `engine/export_2d.py` · `cli.py` · `live_feeder.py` | Export, CLI subcommands, feeder |
| `engine/starlink_atoms.py` | Compatibility facade |
| `transform/sphere.py` | S2b/H6 sphere quads + radiation layers |
| `ui/` | Studio HTTP + 2D/3D + adaptive UX |
| `adapters/snapshot_store.py` | Local snapshots (+ solar attach) |
| `adapters/cynober_rpc.py` | Optional Cynober DB bridge |
| `out/` | caches, PNG, HTML, snapshots (gitignored) |

**KarmazynOs** is optional (`KARMAZYN_OS` for Lua tools only).

---

## Quick start

```powershell
cd C:\Users\drwis\cynober_studio
pip install -r requirements.txt

# Offline smoke
python main.py --offline-demo --limit 40 --hot-only --no-heatmap

# Studio UI (preferred subcommand)
python main.py studio --offline-demo --limit 40 --open-browser
python main.py studio --limit 12000 --open-browser

# Fleet switch (H7)
python main.py fleets
python main.py studio --fleet oneweb --limit 200 --open-browser

# Solar / geo
python main.py weather --offline
python main.py predict --offline
python main.py geo --offline-demo --limit 40 --no-heatmap
```

Dependencies: **sgp4**, **Pillow**. Substrate: pure-Python (`KARMAZYN_SUBSTRATE=python`).

---

## Engine contract (Studio-ready)

| API | Role |
|-----|------|
| `StarlinkAtomMap.snapshot()` | Coherent density view for UI |
| `filter_density(shell, min_count)` | S4b backend |
| `refresh(..., ensure=True)` | Upsert + sat GC + `version++` |
| `density_cell_consistency()` | hot-only density ↔ cell atoms |
| `summary()` | includes `shells` + **`fleets`** |
| `load_catalog(fleet=…)` | H7 single or merged public TLE |

Sat metadata `v`: `norad`, `name`, `tle*`, `inc`, `shell`, **`fleet`**, lat/lon/alt after prop.

---

## HTTP API (Studio)

| Endpoint | Role |
|----------|------|
| `GET /api/data` | snapshot density + `fleet` + feeder |
| `GET /api/sphere?layer=` | 3D quads · `density` \| `radiation` \| `blend` |
| `GET /api/filter` | shell / min_count |
| `POST /api/refresh` | re-propagate · optional reload_tle |
| `GET /api/feeder` · `POST …/start\|stop` | live feeder |
| `GET /api/snapshots` · `POST …/save\|load` | local persistence |
| `GET /api/analyze` | density stats (+ geo by default) |
| `GET /api/weather` · `/hazard` · `/predict` · `/report` · `/geo` | solar stack |
| `GET /api/fleets` · `POST /api/fleet` | H7 catalog switch |
| `GET /api/sla` · `/api/version` | scale contract |
| `GET /api/rpc/*` | optional Cynober DB |

stdlib `http.server` only (no Flask). See [README.md](../README.md).

---

## UI surfaces

| Surface | Notes |
|---------|--------|
| 2D layers | Density / Hazard / Blend |
| 3D layers | Density / Radiation / Blend · large globe |
| Edge aura | Frame vignette ∝ solar stress (H8) |
| Adaptive px | few→coarse blocks; many→fill panel, sharp (H8) |
| Horizons | 1h/6h/24h panel (H3) |
| Alt / sunlit | H5 panel |
| Fleet picker | H7 Load fleet rebuilds map |
| Library | Snapshot list / load / save (solar meta on save) |

---

## Tests

```powershell
python -m unittest discover -s tests -v
python tests\test_catalogs.py
python tests\test_space_weather.py
python tests\test_sphere.py
```

---

*Home: Cynober Studio · private repo Maciej-EriAmo/cynober_studio*
