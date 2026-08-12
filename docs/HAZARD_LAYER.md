# Hazard layer — public solar context for Starlink groups

**Status:** H0–H8 core shipped (2026-08-12) · H7 multi-fleet later  
**Product role:** research workbench for enthusiasts (not operational SSA)

## Principle

- **Public data only** (NOAA SWPC + TLE/SGP4 density).
- Scores are **proxies**, not radiation-dose or collision certification.
- Aggregates by **group** (constellation / shell); cells-scale overlay for maps.
- Density remains density; solar is a **separate layer**.

## Shipped

| Step | Code | API / UI |
|------|------|----------|
| H0 weather | `engine/solar/weather.py` | `GET /api/weather` · `python main.py weather` |
| H1 groups | `engine/solar/hazard.py` | `GET /api/hazard` · `python main.py hazard` |
| H2 2D overlay | heatmap layers + `build_overlay` | Density / Hazard / Blend · `?grid=1` |
| H3 predict | `engine/solar/predict.py` | `GET /api/predict` · `python main.py predict` · UI Horizons |
| H4 report | `engine/solar/report.py` | `GET /api/report` · `python main.py report` · snapshot `solar` meta |
| H6 3D intensity | `transform/sphere.py` + `globe.js` | `GET /api/sphere?layer=radiation` · UI 3D Radiation/Blend |
| H5 alt / sunlit | `engine/solar/geo.py` | `GET /api/geo` · `python main.py geo` · UI Altitude/sunlit |

### Exposure (2D)

```text
exposure ≈ base_score × (0.3 + 0.7 · log1p(count)/log1p(max_count))
```

`base_score` = global or selected shell score from H1.

### Horizons (H3)

```text
1h / 6h / 24h  ← X-ray decay (+ optional short log-flux trend)
               ← Kp geometric relaxation (+ optional trend)
               ← F10.7 hold (1–6h) / slow mean-reversion (24h)
score/severity ← same combine_global as H1
```

CLI (subcommands):

```bat
python main.py weather [--offline] [--force]
python main.py predict [--offline] [--force] [--prop MIN]
python main.py hazard  [map opts] [--offline] [--with-predict]
```

Optional: `predict --prop MIN` records forward-prop context minutes in JSON (density not re-scored).

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

### 3D radiation (H6)

```text
exposure ≈ base_score × (0.3 + 0.7 · log1p(count)/log1p(max_count))
color    = purple→magenta→red ramp (same as 2D hazard)
lift     = mild altitude offset ∝ exposure (visual only)
```

```bat
:: API
GET /api/sphere?layer=density
GET /api/sphere?layer=radiation&offline=1
GET /api/sphere?layer=blend
```

UI: sidebar **3D layer** · Density / Radiation / Blend on globe.

### Altitude / sunlit (H5)

```text
sunlit  ← solar elev at sub-sat point > −limb_depression(alt)
bands   ← lt350 · 350-450 · 450-550 · 550-650 · 650-800 · 800-1200 · gt1200
```

```bat
python main.py geo --offline-demo --limit 40 --no-heatmap
GET /api/geo
```

UI panel: sunlit % · alt median/range · band list with lit fraction.

### Adaptive UX (H8) — shipped

| Piece | Status |
|-------|--------|
| Adaptive cell px | **DONE** · `heatmap.js` `adaptiveCellPx` · few→~18px, many→~1px |
| Group filter grows px | **DONE** · shell/min filter re-scales from `count_sats` |
| Edge aura / fog | **DONE** · CSS vignette on map+globe · strength ∝ hazard |

```text
cell_px ≈ min(tier(n_sats), availW/nlon)
  few (demo/shell)  → coarser integer blocks (~7–10px)
  many (≥2k)        → fill panel width, sharp (availW/nlon)
  never: tiny bitmap stretched to 100% (blur) nor 18px on full catalog
```

UI shows `cell ≈ Npx · n≈… · hot=…` under 2D layer controls.

### Multi-fleet (H7)

Public **Celestrak GP groups** only (no keys). Cache per fleet under `out/tle_*.txt`.

```bat
python main.py fleets
python main.py --fleet oneweb --limit 200
python main.py --fleet starlink,oneweb --limit 400
python main.py studio --fleet iridium --open-browser
```

API: `GET /api/fleets` · `POST /api/fleet` `{fleet, limit?}`. UI: Fleet picker + Load fleet.

## Roadmap (next)

| Step | What |
|------|------|
| **polish** | SATCAT country filter · more ad-hoc groups |

## CLI

```bat
python main.py weather
python main.py weather --offline
python main.py predict
python main.py predict --offline
python main.py hazard --offline-demo --limit 40 --offline --with-predict --no-heatmap
python main.py report --offline-demo --limit 40 --offline --json --md --save-snapshot
```

## Disclaimer (product)

Public NOAA SWPC indices and geometric LEO density only.  
Research / education / hobby — not mission operations.
