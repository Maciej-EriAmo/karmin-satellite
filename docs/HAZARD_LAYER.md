# Hazard layer — public solar & fleet context

**Status:** H0–H8 + H7 multi-fleet **shipped** (2026-08-12)  
**Product role:** research workbench for enthusiasts (not operational SSA)

## Principle

- **Public data only** (NOAA SWPC + public TLE / Celestrak + SGP4 density).
- Scores are **proxies**, not radiation-dose or collision certification.
- Aggregates by **group** (fleet / shell); cells-scale overlay for maps.
- Density remains density; solar is a **separate layer**.
- Solar code lives **inside the engine**: `engine/solar/` (not bolt-on CLI flags).

## Package layout

```
engine/solar/
  weather.py   # H0 NOAA SWPC + cache/stub
  hazard.py    # H1 scores + H2 overlay helpers
  predict.py   # H3 horizons 1h/6h/24h
  report.py    # H4 HazardReport JSON/MD + snapshot solar meta
  geo.py       # H5 altitude bands + sunlit fraction
engine/catalogs.py   # H7 fleet registry (Celestrak groups)
transform/sphere.py  # H6 3D layers density|radiation|blend
ui/static/heatmap.js · globe.js · studio.css   # H8 adaptive px + edge aura
```

Compatibility shims: `adapters/space_weather.py`, `engine/hazard.py`, `engine/predict.py` → re-export `engine.solar`.

## Shipped matrix

| Step | Code | API / CLI / UI |
|------|------|----------------|
| **H0** weather | `engine/solar/weather.py` | `GET /api/weather` · `main.py weather` |
| **H1** groups | `engine/solar/hazard.py` | `GET /api/hazard` · `main.py hazard` · badges |
| **H2** 2D overlay | `build_overlay` + heatmap | Density / Hazard / Blend · `?grid=1` |
| **H3** predict | `engine/solar/predict.py` | `GET /api/predict` · `main.py predict` · UI Horizons |
| **H4** report | `engine/solar/report.py` | `GET /api/report` · `main.py report` · snapshot `solar` |
| **H5** alt / sunlit | `engine/solar/geo.py` | `GET /api/geo` · `main.py geo` · UI panel |
| **H6** 3D intensity | `transform/sphere.py` + `globe.js` | `GET /api/sphere?layer=` · 3D layers |
| **H7** multi-fleet | `engine/catalogs.py` + `tle.load_catalog` | `main.py fleets` · `--fleet` · `GET/POST /api/fleet(s)` |
| **H8** adaptive UX | `heatmap.js` + `studio.css` | adaptive cell px · edge aura · large globe |

Full CLI tables: [CLI.md](CLI.md).

---

### Exposure (H2 / H6)

```text
exposure ≈ base_score × (0.3 + 0.7 · log1p(count)/log1p(max_count))
```

`base_score` = constellation or selected shell score from H1.  
2D and 3D radiation share the same purple→magenta→red ramp.

### Horizons (H3)

```text
1h / 6h / 24h  ← X-ray decay (+ optional short log-flux trend)
               ← Kp geometric relaxation (+ optional trend)
               ← F10.7 hold (1–6h) / slow mean-reversion (24h)
score/severity ← same combine_global as H1
```

```bat
python main.py weather [--offline] [--force]
python main.py predict [--offline] [--force] [--prop MIN]
python main.py hazard  [map opts] [--offline] [--with-predict]
```

### Report (H4)

```text
HazardReport  → JSON + Markdown
snapshot.solar → weather + hazard(+groups) + optional predict horizons
```

```bat
python main.py report --offline-demo --limit 40 --offline --json --md
python main.py report --offline-demo --limit 40 --offline --save-snapshot
```

API: `GET /api/report?offline=1&md=1` · snapshot save attaches `solar` by default.

### Altitude / sunlit (H5)

```text
sunlit  ← solar elev at sub-sat point > −limb_depression(alt)
bands   ← lt350 · 350-450 · 450-550 · 550-650 · 650-800 · 800-1200 · gt1200
```

```bat
python main.py geo --offline-demo --limit 40 --no-heatmap
GET /api/geo
GET /api/analyze   # includes geo block by default
```

### 3D radiation (H6)

```text
layer=density | radiation | blend
lift     = mild altitude offset ∝ exposure (visual only)
```

```bat
GET /api/sphere?layer=density
GET /api/sphere?layer=radiation&offline=1
GET /api/sphere?layer=blend
```

UI: sidebar **3D layer** · Density / Radiation / Blend. Globe viewport ~62vh; edge aura on frame.

### Multi-fleet (H7)

Public **Celestrak GP groups** only (no API keys). Cache: `out/tle_<fleet>.txt` (Starlink may use legacy `out/starlink_tle_cache.txt`).

Curated ids: `starlink`, `oneweb`, `iridium`, `globalstar`, `orbcomm`, `planet`, `spire`, `swarm`, `gps`, `galileo`, `stations`, `visual`, `active`.

```bat
python main.py fleets
python main.py --fleet oneweb --limit 200
python main.py --fleet starlink,oneweb --limit 400
python main.py studio --fleet iridium --open-browser
```

- Merge splits `limit` evenly across fleets.
- NORAD dedupe on merge (first fleet wins).
- `summary.fleets` counts per fleet; sat metadata includes `fleet`.

API: `GET /api/fleets` · `POST /api/fleet` `{ "fleet": "oneweb", "limit": 200 }`.  
UI: **Fleet** select + **Load fleet**.

### Adaptive UX (H8)

| Piece | Behavior |
|-------|----------|
| Adaptive cell px | few sats → coarser blocks (~7–10px); many (≥2k) → fill panel width, sharp |
| Shell filter | fewer sats → pixels grow again |
| No stretch blur | canvas drawn 1:1 CSS px (not `width:100%` upscale) |
| Edge aura | vignette on map + globe frame; strength ∝ hazard score/severity |
| Large globe | height ≈ 62vh (520–820px) |

UI shows `cell ≈ Npx · n≈… · hot=…` under 2D layer controls.

---

## CLI (quick)

```bat
python main.py weather
python main.py weather --offline
python main.py predict --offline
python main.py hazard --offline-demo --limit 40 --offline --with-predict --no-heatmap
python main.py report --offline-demo --limit 40 --offline --json --md --save-snapshot
python main.py geo --offline-demo --limit 40 --no-heatmap
python main.py fleets
python main.py studio --offline-demo --limit 40 --open-browser
```

See [CLI.md](CLI.md) for the full flag table.

## Roadmap (optional polish)

| Step | What |
|------|------|
| SATCAT / country filter | public Celestrak / open SATCAT metadata |
| More ad-hoc groups | pass-through Celestrak GROUP names (already partial) |
| Analytics deeper | batch snap×states, charts |

## Disclaimer (product)

Public NOAA SWPC indices, public TLE catalogs, and geometric LEO density only.  
Research / education / hobby — not mission operations or radiation certification.
