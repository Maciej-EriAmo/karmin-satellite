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
| **H8 UX later** | Adaptive pixels + group views + **radiation fog on cartouche** (see below) |

## Future UX (captured 2026-08-12) — readability at full catalog

**Problem:** przy załadowaniu *wszystkich* satelitów duże pixele siatki stają się nieczytelne (szum / zalanie mapy).

**Kierunek (nie implementowane jeszcze):**

1. **Adaptive cell size** — pomniejszać widok / cell rendering w zależności od `n_sats` (i viewportu), w dół **aż do ~1 px** na komórkę przy pełnej konstelacji.
2. **Wywołanie grupami** — wizualizacja i/lub load po **grupach** (shell, batch okien), żeby odzyskać czytelność; pełny katalog nie musi być jednym „grubym” pixelem na wszystko.
3. **Promieniowanie / hazard ambient** — zamiast (lub obok) malowania stressu w pixelach mapy: **mgła na kartuszu / obrzeżu wewnątrz okna graficznego** (vignette / edge fog). Natężenie mgły ∝ solar stress (global lub aktywnej grupy). Mapa density zostaje czytelna; stress = atmosfera ramki.

```text
┌─────────────────────────────┐
│ ░░ fog (radiation stress) ░░│
│ ░  ┌─────────────────┐   ░  │
│ ░  │  density cells  │   ░  │  ← adaptive px / group filter
│ ░  │  (1px…coarse)   │   ░  │
│ ░  └─────────────────┘   ░  │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░  │
└─────────────────────────────┘
```

H2 layers (Density/Hazard/Blend) zostają opcją badawczą; **fog na obrzeżu** = domyślny, nieinwazyjny sygnał pogody.

## CLI

```bat
python main.py --weather
python main.py --weather --weather-offline
python main.py --offline-demo --limit 40 --hazard --no-heatmap
```

## Disclaimer (product)

Public NOAA SWPC indices and geometric LEO density only.  
Research / education / hobby — not mission operations.
