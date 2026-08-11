# Cynober Studio — Plan Kompletny (Substrate → Visual)

**Celem:** Zaplanować architekturę wizualizacji dla 50–100k atomów Starlink (lub innych masowych obiektów) od warstwy substratu aż do graficznego interfejsu.

**Status:** PLANOWANIE  
**Język:** PL  
**Data:** 2026-08-10

---

## Wariantowe Decyzje (Zaznacz Wybór)

Zaznacz `[x]` przy wybranym wariancie w każdej sekcji.

### S1: SUBSTRATE (warstwa atomów)
- [ ] **S1a: Python Store** — nieskończony HashMap, łatwy dev, no persist
- [ ] **S1b: Hybrid** — Python Store (desktop) + DB_karmin (history/media/sync)
- [ ] **S1c: Rust native** — slab MAX_ATOMS~256, tight, embeddable

**Rekomendacja:** S1b (najrealistyczne dla teraz: Python na dev, DB_karmin na future)

### S2: VISUAL LAYER (format wyjścia)
- [ ] **S2a: 2D Heatmapa** (PNG + HTML canvas) — co teraz
- [ ] **S2b: 3D Globe** (WebGL/Three.js/Babylon) — satelity na sferze
- [ ] **S2c: Interactive Canvas** (Pygame/Qt desktop) — zoom/pan/live
- [ ] **S2d: Rust Native UI** (egui/bevy) — embedded slab + renderer

**Rekomendacja:** S2b (nowoczesne, interaktywne, web-native)

### S3: DATA FLOW (jak dane wchodzą do studia)
- [ ] **S3a: One-shot** — uruchomienie → ingest → render → exit
- [ ] **S3b: Live refresh** — co 15 min nowy TLE → update atomów → redraw
- [ ] **S3c: Agent** — satelity mają własny agent, sami się evolve
- [ ] **S3d: Hybrid** — DB_karmin persists, cykliczny feeder, UI query DB

**Rekomendacja:** S3b lub S3d (S3b dla MVP, S3d dla produkcji)

### S4: INTERAKCJA (co robi user w UI)
- [ ] **S4a: View-only** — pasywna wizualizacja, no edit
- [ ] **S4b: Query & filter** — zaznacz satelity po shell/region, heatmapa się zmienia
- [ ] **S4c: Edit atoms** — dodaj/usuń/zmień T, test physics
- [ ] **S4d: Lua REPL** — :tool commands w UI, live results

**Rekomendacja:** S4b (safe, intuicyjne)

---

## Architektura: Pięć Warstw

```
┌─────────────────────────────────────────────┐
│ S4: INTERACTION LAYER (UI widgets)          │
│     (query, filter, click handlers)         │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ S3: PRESENTATION LAYER (rendering)          │
│     (WebGL, Canvas 2D, events, state)       │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ S2: DATA TRANSFORM LAYER (projection)       │
│     (cells → screen coords, T → color)      │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ S1: RUNTIME (Python Store / DB_karmin)      │
│     (atoms, T, reach, isolation)            │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│ S0: DATA INGESTION (TLE → atoms)            │
│     (fetch, parse, ingest_sats)             │
└─────────────────────────────────────────────┘
```

---

## Fazy Implementacji (MVP → Production)

### **FAZA 0: Przygotowanie (teraz)**

**Cel:** Przygotować kod, dane, środowisko.

| Element | Zadanie | Status |
|---------|---------|--------|
| Substrate | Upewnij się `starlink_atoms.py` skaluje do 50k bez OOM | [ ] |
| TLE cache | Świeży dump, ~10k–100k satelitów | [ ] |
| Dependencies | `sgp4`, `pillow`, opcjonalnie `three.js` / `pygame` | [ ] |
| Metrics baseline | Zmierz CPU/RAM na 10k, 50k (propagacja, density, render) | [ ] |

**Deliverables:**
- Benchmark: propagacja SGP4 na 50k (oczekiwane ~2s)
- Benchmark: apply_density na 50k (oczekiwane ~200ms)
- Benchmark: memory footprint (oczekiwane ~300–500 MB)

---

### **FAZA 1: Substrate Optimization (S1 — wybór wg wariantu)**

#### Wariant S1a: Python Store (dalej bez zmian)
- Już działa; hold.

#### Wariant S1b: Hybrid (Python + DB_karmin)
**Kroki:**
1. Rozszerz `project_starlink_view()` aby zapisywał snapshot do DB_karmin:
   ```python
   def project_to_karmin(amap: StarlinkAtomMap, karmin_path: Path):
       payload = export_report_payload(amap, ...)
       # INSERT INTO karmin: sats, cells, bubbles, metadata
       # ID snapshot: timestamp
       # Media: heatmap PNG → KAFS
   ```

2. Dodaj `load_from_karmin(snapshot_id)` — odczyt z DB do Store:
   ```python
   def load_from_karmin(karmin_path: Path, snapshot_id: str) -> StarlinkAtomMap:
       # SELECT sats, cells, bubbles FROM karmin WHERE snapshot_id
       # CREATE atoms w Store
       # return amap
   ```

3. Interfejs CLI:
   ```bash
   python starlink_atoms.py --limit 0 --karmin-save my_snapshot
   python starlink_atoms.py --karmin-load my_snapshot --html --studio
   ```

#### Wariant S1c: Rust native
**Skomplikowane; defer na Phase 3.**

---

### **FAZA 2: Data Flow Layer (S3 — wybór wg wariantu)**

#### Wariant S3a: One-shot (MVP, używany teraz)
Nie zmienia się — `build_map() → summary() → done`.

#### Wariant S3b: Live refresh (co 15 min)
**Architektura:**
```python
class StarlinkLiveFeeder:
    def __init__(self, store, interval_min=15):
        self.store = store
        self.interval = interval_min * 60
        self.thread = None
        self.amap = None
        
    def start(self):
        self.thread = Thread(target=self._loop, daemon=True)
        self.thread.start()
        
    def _loop(self):
        while True:
            time.sleep(self.interval)
            raw, src = load_tle_text(offline_demo=False, ...)
            catalog = parse_tle_catalog(raw)
            
            # Update atoms w Store (nie recreate)
            self.amap.refresh(catalog)
            
            # Event: store.emit("starlink_refreshed", amap)
            # UI słucha i redrawuje
```

**CLI:**
```bash
python starlink_atoms.py --limit 0 --live-feed --interval 15 --studio
```

#### Wariant S3c: Agent
**Zaawansowane; defer na Phase 3.**

#### Wariant S3d: Hybrid (DB_karmin + cykliczny feeder)
Kombinacja S3b + S1b: feeder zapisuje snapshoty do DB, UI query DB.

---

### **FAZA 2.5: Projection & Transform (S2 — wybór wg wariantu)**

Dla każdego wariantu S2, przygotuj **projekcję** — mapa atomów → screen space.

#### S2a: 2D Heatmapa (PNG)
**Już implementowane.** Forward do S3 (presentation).

#### S2b: 3D Globe (WebGL)
**Nowa implementacja:**

```python
class StarlinkGlobeProjection:
    """Projekcja: lat/lon/alt → 3D sphere coords"""
    
    def __init__(self, radius_earth=1.0):
        self.r = radius_earth
        
    def latlon_to_xyz(self, lat, lon, alt_km=400):
        """WGS84 → ECEF → normalized"""
        r_km = 6378.137 + alt_km / 1000.0  # Earth radius + altitude
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        
        x = r_km * math.cos(lat_rad) * math.cos(lon_rad)
        y = r_km * math.cos(lat_rad) * math.sin(lon_rad)
        z = r_km * math.sin(lat_rad)
        
        # Normalize to sphere
        norm = math.sqrt(x*x + y*y + z*z)
        return (x/norm * self.r, y/norm * self.r, z/norm * self.r)
    
    def cell_to_sphere_quad(self, ilat, ilon, grid_deg, alt_km=400):
        """Komórka gęstości → cztery punkty na sferze"""
        corners = [
            (ilat * grid_deg - 90, ilon * grid_deg - 180),
            ((ilat+1) * grid_deg - 90, ilon * grid_deg - 180),
            ((ilat+1) * grid_deg - 90, (ilon+1) * grid_deg - 180),
            (ilat * grid_deg - 90, (ilon+1) * grid_deg - 180),
        ]
        return [self.latlon_to_xyz(lat, lon, alt_km) for lat, lon in corners]

def export_sphere_data(amap: StarlinkAtomMap) -> dict:
    """Generuj JSON dla Three.js/Babylon"""
    proj = StarlinkGlobeProjection()
    cells = []
    max_t = T_MAX
    
    for a in amap.iter_cells():
        v = a.metadata.get("v") or {}
        ilat, ilon = v.get("ilat"), v.get("ilon")
        if ilat is None or ilon is None:
            continue
        
        quad = proj.cell_to_sphere_quad(ilat, ilon, amap.grid_deg)
        color = t_to_rgb(float(a.T))
        
        cells.append({
            "id": str(a.id),
            "quad": quad,  # [[x,y,z], ...]
            "color": f"rgb({color[0]},{color[1]},{color[2]})",
            "T": round(float(a.T), 2),
            "count": v.get("count"),
        })
    
    return {
        "projection": "sphere",
        "cells": cells,
        "shells": amap._shells,
        "stats": amap.summary(),
    }
```

#### S2c / S2d: Interactive Canvas
**Defer na Phase 3** (render engine choice).

---

### **FAZA 3: Presentation Layer (S2 rendering → screen)**

#### Wariant S2a: 2D Heatmapa + HTML Canvas
**Implementacja:**
```html
<canvas id="heatmap"></canvas>
<script>
const canvas = document.getElementById('heatmap');
const ctx = canvas.getContext('2d');
const payload = {...}; // z export_report_payload()

function draw() {
  const w = canvas.width, h = canvas.height;
  const nlat = payload.nlat, nlon = payload.nlon;
  const cw = w / nlon, ch = h / nlat;
  
  payload.density.forEach(({ilat, ilon, count}) => {
    const T = density_to_T(count, max);
    const [r, g, b] = t_to_rgb(T);
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.fillRect(ilon * cw, (nlat-1-ilat) * ch, cw, ch);
  });
}

draw();
</script>
```

**Interakcja:** Hover → tooltip z metadanymi; click → filter shell.

#### Wariant S2b: 3D Globe (Three.js)
**Implementacja:**
```html
<div id="globe"></div>
<script src="three.js"></script>
<script>
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, w/h, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setSize(w, h);
document.getElementById('globe').appendChild(renderer.domElement);

// Earth sphere
const earth = new THREE.Mesh(
  new THREE.SphereGeometry(1, 64, 64),
  new THREE.MeshPhongMaterial({color: 0x000844})
);
scene.add(earth);

// Load cells from export_sphere_data()
const data = {...}; // z export_sphere_data()
data.cells.forEach(cell => {
  const geom = new THREE.BufferGeometry();
  const vertices = [];
  cell.quad.forEach(([x, y, z]) => vertices.push(x, y, z));
  geom.setAttribute('position', new THREE.BufferAttribute(
    new Float32Array(vertices), 3
  ));
  
  const mat = new THREE.MeshBasicMaterial({
    color: new THREE.Color(cell.color)
  });
  const mesh = new THREE.Mesh(geom, mat);
  scene.add(mesh);
});

// Render loop
function animate() {
  requestAnimationFrame(animate);
  earth.rotation.y += 0.0001;
  renderer.render(scene, camera);
}
animate();
</script>
```

**Interakcja:** Drag-to-rotate; zoom; click → query satellite positions.

#### Wariant S2c/d: Pygame / Native Desktop
**Defer na Phase 3.**

---

### **FAZA 4: Interaction Layer (S4 — UI widgets)**

#### S4a: View-only
No implementation needed; skip.

#### S4b: Query & Filter (rekomendowany)
**Komponenty:**

1. **Shell filter** (radio buttons):
   ```html
   <fieldset>
     <legend>Shells (Inclination)</legend>
     <input type="radio" name="shell" value="all" checked> All
     <input type="radio" name="shell" value="53"> 53°
     <input type="radio" name="shell" value="70"> 70°
     ...
   </fieldset>
   <script>
   document.querySelectorAll('input[name="shell"]').forEach(input => {
     input.onchange = () => {
       const shell = input.value;
       applyFilter(shell === "all" ? null : shell);
       redrawHeatmap();
     };
   });
   </script>
   ```

2. **Density range slider**:
   ```html
   <input type="range" id="minCount" min="1" max="50" value="1">
   <span id="minCountVal">1</span>
   ```

3. **Statistics panel**:
   ```html
   <div id="stats">
     <p>Total sats: <strong id="stat-sats">-</strong></p>
     <p>Hot cells: <strong id="stat-hot">-</strong></p>
     <p>Prop time: <strong id="stat-prop">-</strong>ms</p>
   </div>
   <script>
   function updateStats(summary) {
     document.getElementById('stat-sats').textContent = summary.sats;
     document.getElementById('stat-hot').textContent = summary.hot_cells;
     document.getElementById('stat-prop').textContent = summary.prop_ms;
   }
   </script>
   ```

#### S4c: Edit atoms
**Zaawansowane; defer.**

#### S4d: Lua REPL
**Zaawansowane; defer na Phase 4.**

---

### **FAZA 5: Integration & Studio App**

**Cel:** Połączyć wszystkie warstwy w gotową aplikację: **Cynober Studio**.

#### CLI Entry Point:
```bash
python starlink_atoms.py \
  --limit 0 \
  --prop sgp4 \
  --hot-only \
  --studio \
  [--studio-mode {2d|3d|interactive}] \
  [--live-feed --interval 15] \
  [--karmin-load snapshot_id]
```

#### Studio App struktura:
```
cynober_studio/
├── main.py                    # CLI + server startup
├── substrate/
│   ├── __init__.py
│   ├── starlink_map.py        # StarlinkAtomMap + optimizations
│   └── live_feeder.py         # S3b/S3d implementation
├── transform/
│   ├── __init__.py
│   ├── projections.py         # S2 implementations
│   └── export.py              # export_report_payload, export_sphere_data
├── ui/
│   ├── __init__.py
│   ├── app.py                 # Flask/FastAPI server
│   ├── templates/
│   │   ├── heatmap_2d.html    # S2a
│   │   ├── globe_3d.html      # S2b
│   │   └── interactive.html   # S2c
│   └── static/
│       ├── js/
│       │   ├── heatmap.js
│       │   ├── globe.js       # Three.js setup
│       │   └── filters.js     # S4b interactions
│       └── css/
│           └── studio.css
└── tests/
    ├── test_substrate.py
    ├── test_projections.py
    └── test_ui.py
```

#### Main entry:
```python
# cynober_studio/main.py

import argparse
from flask import Flask, render_template, jsonify, request
from .substrate import StarlinkAtomMap, build_map
from .transform import export_report_payload, export_sphere_data
from .ui import create_app

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--studio-mode", choices=["2d", "3d", "interactive"], default="2d")
    ap.add_argument("--live-feed", action="store_true")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()
    
    if not args.studio:
        # stary tryb CLI
        store, amap, use, src = build_map(limit=args.limit)
        print(amap.summary())
        return
    
    # Studio mode
    store, amap, use, src = build_map(limit=args.limit)
    
    if args.live_feed:
        from .substrate import StarlinkLiveFeeder
        feeder = StarlinkLiveFeeder(store, interval_min=args.interval)
        feeder.start()
    
    app = create_app(amap, studio_mode=args.studio_mode)
    
    @app.route("/api/data")
    def api_data():
        if args.studio_mode == "2d":
            return jsonify(export_report_payload(amap))
        elif args.studio_mode == "3d":
            return jsonify(export_sphere_data(amap))
    
    @app.route("/api/filter")
    def api_filter():
        shell = request.args.get("shell")
        # Filter amap.density by shell
        # Return filtered data
        return jsonify({...})
    
    print(f"Studio running on http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False)

if __name__ == "__main__":
    main()
```

---

## Metryki Sukcesu

### Performance Targets:

| Operacja | 10k | 50k | 100k |
|----------|-----|-----|------|
| Ingest | ~50ms | ~250ms | ~500ms |
| Propagate (SGP4) | ~200ms | ~1000ms | ~2000ms |
| Density update | ~20ms | ~100ms | ~200ms |
| Render PNG | ~30ms | ~150ms | ~300ms |
| Render 3D (sphere) | ~40ms | ~200ms | ~400ms |
| Export JSON | ~50ms | ~250ms | ~500ms |
| **Total** | <500ms | <3s | <5s |

### Memory Targets:

| Wariant | 10k atoms | 50k atoms | 100k atoms |
|---------|-----------|-----------|------------|
| S1a (Python Store) | ~150 MB | ~750 MB | ~1.5 GB |
| S1b (Python + DB snapshots) | ~150 MB + ~10 MB/snapshot | ~750 MB + ~50 MB/snapshot | ~1.5 GB + ~100 MB/snapshot |
| S1c (Rust slab) | — | — | Not viable (MAX_ATOMS~256) |

### Quality Targets:

- [ ] Zero propagation errors (SGP4)
- [ ] Hot-only maintains <2.5k cells always
- [ ] UI refresh <100ms (heatmap), <500ms (3D globe)
- [ ] Query/filter response <50ms
- [ ] Memory leak-free over 1h live-feed

---

## Timeline (estymacja)

| Faza | Zadanie | Dni | Status |
|------|---------|-----|--------|
| 0 | Benchmark, TLE, deps | 1 | [ ] |
| 1 | Substrate optimization (S1 wariant) | 2–3 | [ ] |
| 2 | Data flow (S3 wariant: S3a or S3b) | 2 | [ ] |
| 2.5 | Projection layer (S2 wariant) | 2–3 | [ ] |
| 3 | Presentation layer (render engine) | 3–5 | [ ] |
| 4 | Interaction layer (filters, UI) | 2–3 | [ ] |
| 5 | Integration & Studio app | 2–3 | [ ] |
| **Total** | | **16–22 dni** | |

---

## Decision Checklist

Zaznacz wybory do kopii tego planu:

### Substrate (S1):
- [ ] S1a (Python Store, teraz)
- [ ] **S1b (Python + DB_karmin)** ← rekomendacja
- [ ] S1c (Rust slab, defer)

### Visual (S2):
- [ ] S2a (2D Heatmapa, teraz)
- [ ] **S2b (3D Globe, Three.js)** ← rekomendacja (nowoczesne)
- [ ] S2c (Pygame)
- [ ] S2d (Native Rust)

### Data Flow (S3):
- [ ] **S3a (One-shot)** ← szybkie MVP
- [ ] **S3b (Live refresh co 15 min)** ← rekomendacja (bardziej realistyczne)
- [ ] S3c (Agent, zaawansowane)
- [ ] S3d (Hybrid DB_karmin, defer)

### Interaction (S4):
- [ ] S4a (View-only)
- [ ] **S4b (Query & Filter)** ← rekomendacja (intuicyjne)
- [ ] S4c (Edit atoms, zaawansowane)
- [ ] S4d (Lua REPL, zaawansowane)

---

## Followup Documents

Po wyborze wariantów, przygotuj:

1. **CYNOBER_STUDIO_ARCH.md** — szczegółowa architektura (klasy, API, flowcharts)
2. **CYNOBER_STUDIO_CODE_PHASE_X.md** — kod dla każdej fazy (nie komentarze, pełny kod)
3. **CYNOBER_STUDIO_METRICS.md** — benchmarks i test suite

---

*Plan autora: Maciej · KarmazynOs · 2026-08-10*  
*Zamiast 300MB dokumentacji, jeden modularny plan. Wybierz warianty, a robię kod.*
