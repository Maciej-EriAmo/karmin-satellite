# Hazard layer — public solar context for Starlink groups

**Status:** H0–H2 shipped (2026-08-12) · H3/H4 next · 3D intensity later  
**Product role:** research workbench for enthusiasts (not operational SSA)

## Principle

- **Public data only** (NOAA SWPC + TLE/SGP4 density).
- Scores are **proxies**, not radiation-dose or collision certification.
- Aggregates by **group** (constellation / shell); cells-scale overlay for maps.
- Density remains density; solar is a **separate layer**.

## Shipped

| Step | Code | API / UI |
|------|------|----------|
| H0 weather | `adapters/space_weather.py` | `GET /api/weather` · CLI `--weather` |
| H1 groups | `engine/hazard.py` | `GET /api/hazard` · badges + shell list |
| H2 2D overlay | heatmap layers + `build_overlay` | Density / Hazard / Blend · `?grid=1` |

### Exposure (2D)

```text
exposure ≈ base_score × (0.3 + 0.7 · log1p(count)/log1p(max_count))
```

`base_score` = global or selected shell score from H1.

## Roadmap (next)

| Step | What |
|------|------|
| **H3 NEXT** | Predict 1h / 6h / 24h from public indices (+ optional forward prop) |
| **H4** | HazardReport JSON/MD; attach weather+hazard to snapshot meta |
| **H6 later** | **3D radiation intensity** on globe quads (`ui/static/globe.js` TODO) |
| **H5** | Alt-band + sunlit fraction |
| **H7** | Multi-fleet: NASA TLE API, Celestrak groups/SATCAT country (public) |

## CLI

```bat
python main.py --weather
python main.py --weather --weather-offline
python main.py --offline-demo --limit 40 --hazard --no-heatmap
```

## Disclaimer (product)

Public NOAA SWPC indices and geometric LEO density only.  
Research / education / hobby — not mission operations.
