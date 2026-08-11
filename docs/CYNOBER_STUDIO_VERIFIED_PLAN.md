# Cynober Studio — Zweryfikowany plan

**Status:** VERIFIED + PLAN  
**Data:** 2026-08-11  
**Źródła:** `engine/starlink_atoms.py`, `substrate/*`, `docs/CYNOBER_STUDIO_PLAN.md`, `docs/CYNOBER_STUDIO_AUDIT.md`, smoke offline  
**Repo:** prywatne `Maciej-EriAmo/cynober_studio` · root `C:\Users\drwis\cynober_studio`

---

## 0. Cel produktu (jedno zdanie)

**Cynober Studio** = samodzielny produkt (jak Cynober DB): silnik atomów termicznych + mapa gęstości (Starlink i inne katalogi) + warstwa wizualna (2D → 3D) + filtry; KarmazynOs opcjonalny most później.

---

## 1. Weryfikacja założeń (pseudokod + werdykt)

Każde założenie: **TRUE** (potwierdzone w kodzie) · **PARTIAL** · **TARGET** (cel, jeszcze nie ma) · **RISK** (audit / luka).

### A1. Jedna Store = multi-task (sat + cell + bubbles)

```
ASSUME: jeden thermal Store trzyma katalog, heatmapę i grupowanie bez drugiego DB.

VERIFY (obecny silnik):
  store ← open_store(thermal=true, backend=python)
  map   ← StarlinkAtomMap(store, grid_deg=5, hot_only=…)

  map.ingest_sats(catalog):
    for sat in catalog:
      aid ← "sat:" + norad
      if not store.has_atom(aid): store.create_atom(aid, S=starlink:sat, T=T_INIT)
      store.import_to_bubble("starlink" | "sats" | shell_key, aid)
      atom.metadata.v ← {tle, inc, shell, …}

  map.refresh(catalog):
    counts ← propagate_and_bin(catalog)   # lat/lon → bin, density dict
    apply_density(counts)                 # cell atoms + T = f(count)

  PRAWO jądra (substrate):
    T mówi KIEDY (HOT/WARM/TOMB); reach (bubbles/root) mówi CZY (GC)
```

| Werdykt | **TRUE** |
|---------|----------|
| Dowód | `StarlinkAtomMap.__init__` tworzy root `starlink` + `sats` + `grid`; ingest + refresh w tym samym store |
| Limit | Store jest **w pamięci** (Python); persistence = TARGET (S1b / Cynober DB), nie dziś |

---

### A2. TLE → pozycja → bin (SGP4 / approx)

```
ASSUME: publiczny TLE wystarcza do heatmapy bez telemetrii prywatnej.

VERIFY:
  text, src ← load_tle_text(offline_demo | cache | fetch Celestrak)
  catalog   ← parse_tle_catalog(text)   # TleSat{norad, lines, inc, n, …}

  position_of(sat, mode):
    if mode == sgp4 and HAS_SGP4:
      (lat, lon, alt) ← SGP4(TLE, when) or fallback approx
    else:
      (lat, lon, alt) ← approx(mean motion, RAAN, …)

  (ilat, ilon) ← latlon_to_bin(lat, lon, grid_deg)
  density[(ilat,ilon)] += 1
```

| Werdykt | **TRUE** |
|---------|----------|
| Smoke | offline 20 satów, `prop=sgp4`, `prop_errors=0` |
| RISK | sieć / malform TLE / NaN — częściowo `try/except` w bin, brak spójnego error tier (audit #7) |

---

### A3. Hot-only: density jest źródłem prawdy dla wizualizacji

```
ASSUME: nie trzymamy 2592 atomów siatki; tylko bin z count>0 (~2k na full catalog).

VERIFY apply_density(hot_only=true):
  new_keys ← keys(counts)
  for key in active_cells \ new_keys:
    delete_atom(cell:ilat:ilon) OR cool to TOMB
    active_cells.discard(key)
  for (ilat,ilon), c in counts:
    upsert_cell(…, count=c, create_empty=false)
    active_cells.add((ilat,ilon))

  render_heatmap_png / export_report_payload:
    iterate density dict  ← NIE pełny iter_cells jako jedyne źródło
```

| Werdykt | **TRUE** (PNG/export z `density`) + **RISK** (audit #5) |
|---------|----------|
| RISK | jeśli `delete_atom` zawiedzie, ghost cells w `iter_cells()`; export sphere w planie musi iść po `density` |

---

### A4. T = gęstość (log-scale), nie surowa liczba

```
ASSUME: temperatura komórki mapuje gęstość do skali jądra [T_TOMB … T_MAX].

VERIFY:
  density_to_T(count, max_count):
    if count ≤ 0: return cold_floor ≥ T_TOMB+4
    t ← T_WARM + (T_MAX − T_WARM) * log1p(count)/log1p(max_count)
    clamp(t, cold_floor, T_MAX)

  t_to_rgb(T) → blue → cyan/yellow → red  (heatmap / canvas)
```

| Werdykt | **TRUE** |
|---------|----------|
| Uwaga | max_count jest **per refresh** (względna skala) — różne snapshoty nie porównują T absolutnie |

---

### A5. Studio jest niezależne od KarmazynOs

```
ASSUME: cynober_studio startuje bez KarmazynOs (jak DB).

VERIFY (stan 2026-08-11):
  ROOT = cynober_studio/
  sys.path ← substrate/   # vendored kernel pure-Python
  KARMAZYN_SUBSTRATE default = "python"
  main.py → engine.starlink_atoms.main()

  Lua path:
    if KARMAZYN_OS exists and lua_bin/name.lua:
      optional bridge
    else:
      soft message, no crash
```

| Werdykt | **TRUE** (CLI / smoke) |
|---------|----------|
| TARGET | API package name, brand strings w HTML nadal „Karmazyn” → rebrand Studio |

---

### A6. Live feed (S3b) jest bezpieczny przy UI

```
ASSUME (stary plan): thread refresh + Flask /api/data równolegle.

VERIFY (obecny kod):
  --live N: sekwencyjne refresh w pętli głównej (CLI), BEZ osobnego thread UI
  brak RLock na StarlinkAtomMap
  brak snapshot_locked()

PSEUDO (wymagane zanim S3b + serwer):
  class StarlinkAtomMap:
    lock ← RLock()
    version ← 0

    refresh(sats):
      with lock:
        counts ← propagate_and_bin(sats)
        apply_density(counts)
        version += 1
        return stats

    snapshot():
      with lock:
        return immutable {
          density: copy(density),
          shells: copy(_shells),
          summary: summary(),
          version: version
        }

  feeder_loop:
    while not stop:
      wait(interval)
      catalog ← load+parse TLE
      map.refresh(catalog)           # trzyma lock krótko
      optional save_snapshot(DB)

  api /data:
    snap ← map.snapshot()            # spójny odczyt
    return export(snap)
```

| Werdykt | **TARGET** + **CRITICAL** zanim live+HTTP |
|---------|---------------------------------------------|
| Audit | #1 race, #3 shutdown, #12 GC martwych satów |

---

### A7. Filter shell / min_count (S4b)

```
ASSUME: UI filtruje po inklinacji i progu count.

VERIFY dziś:
  _shells: shell_key → count przy ingest
  sat.metadata.v.shell = "shell:53"
  density NIE ma pola shell per cell
  brak /api/filter

PSEUDO (backend do zbudowania):
  build_shell_index przy ingest:
    shell_index[shell_key] ← set(sat_ids)

  # Opcja A — filtr po satelitach (dokładny, droższy):
  filter(shell, min_count):
    with lock:
      if shell == "all":
        cells ← {(k,c) in density | c ≥ min_count}
      else:
        # re-bin tylko satów z shell LUB precomputed cell→shells set
        cells ← cells where cell intersects shell AND c ≥ min_count
      return {cells, stats, version}

  # Opcja B — MVP szybkie: filtr tylko min_count na density;
  #           shell = recompute bins from sat atoms with v.shell match
```

| Werdykt | **PARTIAL** (dane shell na sat/bubble) · **TARGET** (API + UI) |
|---------|----------------------------------------------------------------|

---

### A8. 3D globe (S2b) vs 2D (S2a)

```
ASSUME plan: Three.js globe jako „rekomendacja”.
ASSUME audit: MVP = 2D, 3D później.

VERIFY dziś:
  export_report_payload → density + summary + optional PNG b64
  write_html_report → canvas 2D (self-contained file://)
  BRAK export_sphere_data, BRAK Three.js

PSEUDO S2a (już prawie):
  payload ← export_report_payload(map)
  draw canvas: for cell in payload.density → fillRect(color(T))

PSEUDO S2b (później):
  for (ilat,ilon),c in density:           # source of truth = density
    quad ← cell_to_sphere_quad(ilat,ilon, grid_deg)  # clamp + wrap lon
    color ← t_to_rgb(density_to_T(c, max_c))
  return {projection: sphere, cells, version, policy: hot-only|full}
```

| Werdykt | **TRUE: 2D działa** · **TARGET: 3D** · decyzja MVP = **S2a first** (audit #11) |

---

### A9. Hybrid DB / Karmin (S1b)

```
ASSUME: snapshoty historii w Cynober DB / Karmin.

VERIFY dziś: brak adaptera w cynober_studio.

PSEUDO (później, po stabilnym API exportu):
  adapter.save(map):
    payload ← export_report_payload(map)   # bez ogromnego b64 opcjonalnie
    id ← "snapshot_" + epoch
    DB.upsert(snapshots, {id, meta, cells, shells, hash})
    prune older than retention_days

  adapter.load(id) → rebuild density + optional light store
```

| Werdykt | **TARGET** (po Faza 1–2 silnika Studio); nie blokuje MVP wizualnego |

---

### A10. Skala 50–100k atomów

```
ASSUME plan: 50k–100k satów, total e2e <3–5s.

VERIFY (MVP mierzony w docs ~10.7k Starlink):
  prop SGP4 full catalog ~200–240 ms (desktop, stary pomiar KarmazynOs)
  hot cells ~2k
  e2e <0.5s z cache TLE

PSEUDO bench (Faza 0 Studio — do powtórzenia w tym repo):
  for N in [1k, 10k, full, synthetic_50k]:
    t0; build_map(limit=N); t1
    measure: prop_ms, cells, RSS, export_json_bytes
  assert prop_errors_rate < 1%
  assert hot_cells p95 < 5k (realistyczny target z audytu)
```

| Werdykt | **PARTIAL** — 10k potwierdzone historycznie; 50k/100k = **do zmierzenia tutaj** |

---

## 2. Architektura docelowa (warstwy + status)

```
┌──────────────────────────────────────────────────────────┐
│ L4 INTERACTION   filter shell / min_count / stats panel  │  TARGET
├──────────────────────────────────────────────────────────┤
│ L3 PRESENTATION  HTTP or static HTML · canvas 2D · 3D    │  PARTIAL (static HTML)
├──────────────────────────────────────────────────────────┤
│ L2 TRANSFORM     export_report · (sphere) · t_to_rgb     │  PARTIAL (2D export)
├──────────────────────────────────────────────────────────┤
│ L1 ENGINE MAP    StarlinkAtomMap · refresh · density     │  TRUE (engine/)
├──────────────────────────────────────────────────────────┤
│ L0 SUBSTRATE     open_store · atoms · bubbles · T/GC     │  TRUE (substrate/)
├──────────────────────────────────────────────────────────┤
│ L−1 INGEST       TLE fetch/cache/parse · SGP4            │  TRUE
└──────────────────────────────────────────────────────────┘
         │                              │
         │ optional later               │ optional later
         ▼                              ▼
   Cynober DB snapshots           KarmazynOs Lua / native
```

**Zasada granic (jak DB):**

| Pakiet | Wolno | Nie wolno |
|--------|-------|-----------|
| `substrate/` | atom API, pure-Python store | UI, TLE, HTTP |
| `engine/` | TLE, map, export, PNG | hard depend na KarmazynOs |
| `ui/` (przyszłe) | serwer, szablony, JS | mutować store bez lock/snapshot |
| `adapters/` (przyszłe) | DB, KarmazynOs bridge | być wymagane do `main.py` smoke |

---

## 3. Decyzje zamknięte (checklist)

| ID | Decyzja | Wybór | Uzasadnienie weryfikacji |
|----|---------|-------|---------------------------|
| S1 | Substrate | **S1a teraz** → S1b później | pure-Python w repo; DB po stabilnym export API |
| S2 | Visual | **S2a MVP** → S2b option | HTML/canvas już jest; 3D = Faza 3 |
| S3 | Data flow | **S3a MVP** → S3b z lock | live bez RLock = CRITICAL |
| S4 | Interaction | **S4b** po API snapshot | shell index + density filter |
| K0 | KarmazynOs | **opcjonalny most** | `KARMAZYN_OS`, nie import path domyślny |
| K1 | Repo | **PRIVATE** | `github.com/Maciej-EriAmo/cynober_studio` |

---

## 4. Plan implementacji (fazy)

### Faza 0 — Baseline w *tym* repo — **DONE 2026-08-11**

**Cel:** powtarzalne metryki i czysty kontrakt API silnika.

```
TASKS:
  ☑ tests/test_bench.py → out/bench.json (offline)
  ☑ density_cell_consistency() + test
  ☑ unittest discover (bez pytest)
  ☑ Decision freeze: ten dokument = źródło prawdy
  □ docs rebrand STARLINK_ATOMS.md paths (kosmetyka)

DONE WHEN:
  - bench JSON z prop_ms, cells, peak mem, export size  ☑
  - smoke + spójność density/cells green  ☑
```

### Faza 1 — Silnik „Studio-ready” — **DONE 2026-08-11**

**Cel:** bezpieczny kontrakt pod UI (audit #1, #7, #12).

```
PSEUDO deliverables:

  StarlinkAtomMap:
    ☑ RLock, version
    ☑ snapshot() → frozen export dict
    ☑ refresh: ensure_sats + GC sat nie w catalog
    ☑ shell_index: Dict[shell_key, Set[sat_id]]
    ☑ filter_density(shell, min_count) → list cells + stats
    ☑ last_prop_errors + prop_error_rate

  build_map / CLI: one-shot bez regresji

DONE WHEN:
  ☑ unit: concurrent snapshot vs refresh
  ☑ unit: sat GC po refresh(half)
  ☑ unit: filter shell:53 / empty shell:99
```

### Faza 2 — Presentation 2D jako Studio — **DONE 2026-08-11**

**Cel:** `python main.py --studio` serwuje UI z live-ready API shape.

```
PSEUDO:

  main --studio [--port 8765] [--limit …]:
    store, map, catalog, src ← build_map(…)
    app ← create_app(map)   # ui/app.py ThreadingHTTPServer

  ☑ GET /api/version  → {version}
  ☑ GET /api/data     → snapshot() + nlat/nlon
  ☑ GET /api/filter?shell=&min_count= → filter_density
  ☑ POST /api/refresh → version++
  ☑ GET /             → templates/index.html (canvas + shell + min_count)
  ☑ Client poll /api/version co 5s

  Opcja bez serwera: --html file:// (nadal)

DONE WHEN:
  ☑ tests/test_studio_api.py green
  ☑ version rośnie po POST /api/refresh
```

### Faza 3 — Live feeder — **DONE 2026-08-11**

```
  ☑ engine/live_feeder.py: Event stop, atexit, fail budget, stats
  ☑ StudioState.attach_feeder / stop_feeder; limit preserved on reload_tle
  ☑ load_tle_text(cache_ttl_hours=…)
  ☑ CLI: --live-feed --interval SEC --studio [--cache-ttl-hours]
  ☑ API: GET /api/feeder, POST /api/feeder/stop|start
  ☑ tests/test_feeder.py

DONE WHEN:
  ☑ unit: start/stop, max_fails, version bump
  □ opcjonalny ręczny soak 30 min (ops)
```

### Faza 4 — 3D globe — **DONE 2026-08-11**

```
  ☑ transform/sphere.py: density → quads (clamp, wrap, dateline meta)
  ☑ ui/static/globe.js (Three.js CDN, drag/zoom)
  ☑ GET /api/sphere
  ☑ --studio-mode 2d|3d + UI toggle
  ☑ monolit split: tle/prop/grid/map/export_2d/build/cli/lua_bridge

DONE WHEN:
  ☑ 2D default; 3D on demand
  ☑ tests/test_sphere.py
```

### Faza 5 — Adapter snapshot (S1b MVP) — **DONE 2026-08-11**

```
  ☑ adapters/snapshot_store.py — lokalny JSON store (jak osobny skarbiec;
      bez wymogu cynober_server; most RPC opcjonalny później)
  ☑ save / load / list / prune (retention 7d)
  ☑ CLI: --snapshot-save [id] --snapshot-load id --snapshot-list --snapshot-dir
  ☑ API: GET /api/snapshots, POST /api/snapshot/save|load
  ☑ tests/test_snapshots.py roundtrip density

DONE WHEN:
  ☑ roundtrip density == counts
```

### Poza zakresem v1

- Edit atoms (S4c), agent ewolucja satów (S3c), native Rust slab w Studio, Lua w core path, public repo.

---

## 5. Drzewo docelowe (ewolucja z obecnego)

```
cynober_studio/                    # teraz
├── main.py
├── substrate/                     # L0 — stabilne, rzadkie zmiany
├── engine/
│   └── starlink_atoms.py          # → rozbić stopniowo:
│       # starlink_map.py, tle.py, export.py, prop.py
├── transform/                     # Faza 4 sphere; Faza 1 filter helpers
├── ui/                            # Faza 2
│   ├── app.py
│   ├── templates/
│   └── static/
├── adapters/                      # Faza 5
├── docs/                          # plan, audit, THIS
├── tests/
└── out/
```

**Reguła refaktoru:** najpierw kontrakty (`snapshot`, `filter`, `version`), potem pocięcie pliku 1.5k LOC — nie na odwrót.

---

## 6. Definition of Done (MVP Studio v0.2)

| Kryterium | Target | Acceptance |
|-----------|--------|------------|
| Offline smoke | 40 sat | exit 0 |
| Full catalog e2e (cache) | < 2 s | prop_errors < 1% |
| Hot cells | ~2–3.5k typ | p95 < 5k |
| snapshot() thread-safe | 2 thr × 100 | 0 exceptions |
| Filter shell | exact | stats sum consistent |
| 2D studio UI | local | filter + stats |
| Secrets / visibility | private GitHub | remains private |
| KarmazynOs | not required | smoke bez `KARMAZYN_OS` |

---

## 7. Kolejność pracy (najbliższe commity)

```
1. [docs]  ten plik = kanon planu                              ← DONE (ten dokument)
2. [test]  bench + density↔cells consistency
3. [engine] RLock + version + snapshot + sat GC + shell_index + filter
4. [ui]    minimal FastAPI/Flask or stdlib http.server + 2D page
5. [feed]  live feeder + stop
6. [3d]    optional sphere export
7. [db]    Cynober DB adapter
```

---

## 8. Mapowanie audytu → faza

| Audit # | Temat | Faza |
|---------|-------|------|
| 1 Race Store↔UI | RLock + snapshot | 1 |
| 2 Filter backend | filter_density + shell_index | 1–2 |
| 3 Feeder lifecycle | stop_event, TTL cache | 3 |
| 4 Sphere math | clamp/wrap | 4 |
| 5 Hot-only export | density as SoT | 1, 4 |
| 6 Delta JSON | later opt | 3+ |
| 7 Error handling | prop errors list | 1 |
| 8 Metryki realistyczne | Faza 0 bench | 0 |
| 9 S1b schema | adapters | 5 |
| 10 Cache version | /api/version | 2 |
| 11 2D before 3D | decyzja | 2→4 |
| 12 Duplicate/GC sat | refresh GC | 1 |

---

## 9. Jednolinijkowe pseudokod „serce systemu”

```
loop (one-shot or live):
  catalog ← TLE
  with map.lock:
    ensure_sats(catalog)           # create missing, update meta, GC gone
    density ← SGP4_bin(catalog)
    heat_cells(density)            # hot-only atoms
    map.version++
  view ← map.snapshot()
  UI or HTML ← project(view)       # 2D now; 3D later
  optional DB.save(view)
```

To jest **jedyne** spójne założenie runtime. Wszystko inne (Three.js, Flask, DB, Lua) to wtyczki na `view`.

---

*Weryfikacja: kod `cynober_studio` 2026-08-11 · Plan autora w duchu CYNOBER_STUDIO_PLAN + twarde poprawki z AUDIT · Maciej / EriAmo*
