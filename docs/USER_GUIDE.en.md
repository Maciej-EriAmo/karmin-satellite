# Cynober Studio — user guide

**UI language: English.** Button labels below match the screen.  
Research workbench: public TLE density + solar context on thermal atoms. **Not** operational SSA, radiation certification, or Space-Track.

Open: `http://127.0.0.1:8765/` · CLI: [`CLI.md`](CLI.md) · status: [`PROJECT_STATUS.md`](PROJECT_STATUS.md)  
Polish: [`USER_GUIDE.md`](USER_GUIDE.md)

---

## 1. Start

```bat
cd /d C:\Users\drwis\cynober_studio
python -m pip install -r requirements.txt

:: no network (synthetic TLE)
python main.py studio --offline-demo --limit 40 --open-browser

:: live Celestrak
python main.py studio --limit 400 --open-browser
python main.py studio --fleet debris --limit 400 --open-browser
```

Default port **8765**. Stop with `Ctrl+C` in the terminal.

| Flag | Meaning |
|------|---------|
| `--offline-demo` | No network; synthetic catalog |
| `--fleet ID` | `starlink`, `oneweb`, `debris`, `starlink,oneweb`, `all` |
| `--limit N` | How many objects to load. `0` = whole catalog (ceiling 100 000) |
| `--country CC` | SATCAT / heuristic filter (`US`, `UK`, …) |
| `--open-browser` | Open the UI |
| `--studio-mode 3d` | Start on the globe |
| `--live-feed` | Re-propagate on a timer (default 900 s) |

If Celestrak returns 503, Studio skips that cloud and loads the rest (or cache in `out/tle_*.txt`).

---

## 2. Header badges

| Badge | Meaning |
|-------|---------|
| `boot` / `live` / `loading…` | Session state |
| `vN` | Map version (increments on refresh / rebuild) |
| `2d` / `3d` | Active view |
| `solar …` | Flare class · F10.7 · Kp · `stub`/`cache` when not live |
| `hazard …` | Group exposure proxy |
| `reach off` / `reach: N sats` | Whether session reach view is on |

---

## 3. View: 2D and 3D

**2D heatmap** — 5° cells by default. Cell pixels scale: few sats → large blocks, many → ~1 px.

| 2D button | Effect |
|-----------|--------|
| **Density** | Density (map source of truth) |
| **Hazard** | Solar exposure × density weight (proxy, not dose) |
| **Blend** | Density + Hazard |
| **Ghost** | Retained / cold inside session reach |

**3D globe** — the same density on a sphere. Drag = rotate, scroll = zoom.

| 3D button | Effect |
|-----------|--------|
| **Density** | Thermal density |
| **Exposure** | Same as 2D Hazard (not physical radiation) |
| **Blend** | Mix |

With no NOAA weather, Exposure does **not** invent a score — it stays Density.

---

## 4. Loading catalogs

**Load satellites** panel.

1. Pick **Catalog / fleet**.
2. Optional **Country filter**.
3. Set limit: presets **400 / 2k / 10k / 50k**, slider, number field, or **Full catalog**.
4. **Load satellites** — fetch / rebuild the map.
5. **Reload** — same as Load satellites (current selection).
6. **Load debris** — public Celestrak clouds (not Space-Track):
   - Fengyun-1C (2007)
   - Cosmos 2251 + Iridium 33 (2009)
   - Microsat-R (2019; often empty now)
   - Cosmos 1408 (2021; few pieces left)
7. The list also has **Public debris (5 event clouds)** and **All curated fleets** (no `active`, no debris).

`all` = comms fleets. Debris is not included in “all satellites”.

`--offline-demo` builds synthetic TLE tagged with the fleet name — for UI practice, not orbital research.

---

## 5. Shell filter (S4b)

**Shell** — inclination (`shell:53`, …) or **All**.  
**Min count** — hide sparse cells.

| Button | Effect |
|--------|--------|
| **Refresh** | Re-propagate (SGP4) the current catalog |
| **Reset filter** | All + min 1 |
| **Impact** | What-if: this shell goes cold. **Simulate** — density stays |

With **Reach view** on, changing shell rebuilds the session root (`POST /api/session`), it does not just crop a PNG.

---

## 6. Reach, Ghost, Live root

Law: **T says when, reach says whether.**  
**Density** stays the map SoT until you turn on Reach view.

### Reach / Ghost (left panel)

| Control | Effect |
|---------|--------|
| **Reach view** | Map only in the session closure |
| **Ghost under density** | Ghosts under the density layer |
| **Demo: cool in reach** | Artificially cool a sample so Ghost has something to show |

Empty Ghost without a tick / demo is expected.

### Bar above the map

| Button | Effect |
|--------|--------|
| **Live root** | Only GC root = session. Out of session + cold = vacuum |
| **Commit** | Cool outside session and `tick()` — they vanish for real |
| **Restore** | Catalog root back, re-ingest TLE |
| **Reach view** | Same as the panel checkbox |
| **Impact** | Simulate cooling a shell; cell outline 5 s (amber = hit, crimson = emptied) |
| **Fleet log** | One `Store.tick()` + fleet log. `cool_hint` does **not** cool |
| **Search** | Name / `shell:53` / `fleet:starlink`. HRR only on a real hit; else `scope` / `lexical` |
| **JSON** / **MD** | Download the view |

Bar meters: `live`, `reach`, `ghost`, `impact`, `tick`, `density SoT`.

---

## 7. Weather, horizons, geo

All of this is a **research proxy** (NOAA SWPC + geometry). Not eclipse ephemeris, not dose.

| Section | What it does |
|---------|----------------|
| **Solar weather** | Flare, F10.7, Kp. **Refresh weather** forces a fetch. `Mode`: `live` / `cache` / `stub` |
| **Horizons (H3)** | 1h / 6h / 24h — index decay + short trend, not a mission forecast |
| **Shell hazard** | Score per shell |
| **Altitude / sunlit** | Altitude bands + sunlit fraction (geometry) |
| Map/globe frame | Aura ∝ solar stress. No weather = 0 (no fake glow) |

---

## 8. Analyze, Library, Timeline

**Analyze** — current-view stats: cell count, Σ count, max, hotspot, p50/p90, top cells.

**Library** — frames on disk `out/snapshots/` (gitignored).

| Button | Effect |
|--------|--------|
| **Save server** | Write a snapshot (+ `solar` meta when present) |
| **Refresh list** | Reload the list |
| click a frame | Load it onto the map |

**Timeline** — density metrics across saved frames.

| Button | Effect |
|--------|--------|
| **Refresh timeline** | Frame list |
| **Compare newest** | Delta of the two newest |

**JSON file** / **MD file** — download the current view. Check **Include TLE in JSON file** to embed TLE lines.

**Push DB** — optional Cynober DB bridge. The button stays **hidden** until `cynober_client` is installed. Local snapshots stay primary.

---

## 9. CLI — function list

Full flags: [`CLI.md`](CLI.md).

| Command | Role |
|---------|------|
| *(default)* | One-shot map / heatmap / snapshot |
| `studio` | HTTP UI |
| `weather` | NOAA JSON |
| `predict` | Horizons 1h/6h/24h |
| `hazard` | Score on a map |
| `report` | HazardReport JSON/MD |
| `geo` | Altitude + sunlit |
| `fleets` | Catalog list |
| `timeline` | Snapshot compare |

```bat
python main.py fleets
python main.py --fleet debris --limit 400 --no-heatmap
python main.py weather
python main.py report --offline-demo --limit 40 --offline --json --md
python main.py --offline-demo --limit 40 --snapshot-save
```

---

## 10. Tests

```bat
python run_tests.py
python tests\test_capacity.py
python tests\test_bench.py
```

`run_tests.py` loads `tests/test_*.py` by path (avoids a site-packages `tests` shadow). Capacity / bench are optional (scale).

---

## 11. What it does not do

- Operational conjunction assessment  
- Authenticated Space-Track  
- Atom editing or “sat agents”  
- Native Rust slab on the Studio path (Python Store)  
- EN/PL language switch (UI = English)  
- Applying `cool_hint` from Fleet log — log only  

Density is the visualization SoT. Reach / Ghost / Impact / Fleet log sit beside it, they are not a second orbit engine.

---

## 12. Red bar — electromagnetic storm

A plain threshold on public NOAA SWPC indices, now or at the 6h horizon (H3):

- Kp ≥ 5, or  
- M/X flare, or  
- score ≥ 55  

No extra equation. Not a magnetometer, not detection from the sat map.

Ops∩debris overlap lives in the API as `crowding` (a count) and **does not** fire the bar.
