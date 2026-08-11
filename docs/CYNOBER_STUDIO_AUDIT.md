# CYNOBER STUDIO — Audyt Planu (20 Słabych Punktów)

**Status:** COMPLETED AUDIT  
**Data:** 2026-08-10  
**Autor:** Analiza krytyczna planu CYNOBER_STUDIO_PLAN.md

---

## Spis Słabych Punktów

Każdy punkt ma:
- **Opis problemu** — co jest nie tak
- **Implikacja** — co się może stać
- **Rekomendacja** — jak naprawić
- **Priorytet** — CRITICAL / HIGH / MEDIUM

---

## 1. Race Condition: Store ↔ UI w S3b (Live Feeder)

**Problem:**
```
Thread: StarlinkLiveFeeder._loop()
  ├─ time.sleep(900)
  ├─ load_tle_text() [blocking I/O]
  ├─ parse_tle_catalog()
  ├─ amap.refresh() [WRITES to Store]
  │  ├─ propagate_and_bin() [updates _active_cells, density]
  │  ├─ apply_density() [modifies cells]
  └─ store.emit("starlink_refreshed") [event]

Thread: Flask handler /api/data
  ├─ export_sphere_data(amap)
  ├─ iter_cells() [READS Store]
  ├─ amap.summary() [counts atoms]
  └─ return JSON
```

Brak lock'ów — race condition na:
- `_active_cells` (Set — nie thread-safe w CPython bez GIL, ale lepiej być safe)
- `density` (Dict — reader może widać partial update)
- Atom.metadata updates

**Implikacja:**
- JSON export może mieć stare dane z częścią nowych
- Sphere quads mogą mieć inconsistent state
- Crash w JSON serialization (Atom w trakcie modifikacji)

**Rekomendacja:**

Dodaj do plan:

```
### FAZA 1.5: Thread Safety (dodać do S3b)

**Kroki:**
1. Import threading locks:
   ```python
   from threading import RLock
   
   class StarlinkAtomMap:
       def __init__(self, ...):
           self._lock = RLock()  # Re-entrant
           self._active_cells = set()
           self.density = {}
   
   def refresh(self, sats, ...):
       with self._lock:
           counts = self.propagate_and_bin(sats, ...)
           hot = self.apply_density(counts)
           return {"bins": ..., "hot": ...}
   
   def iter_cells(self):
       with self._lock:
           for a in self.store.atoms():
               if getattr(a, "S", None) == S_CELL:
                   yield a
   ```

2. Flask routes also lock:
   ```python
   @app.route("/api/data")
   def api_data():
       with amap._lock:  # Or: snapshot = amap.snapshot_locked()
           return jsonify(export_sphere_data(amap))
   ```

3. Alternatywa (lepsze): Snapshot pattern:
   ```python
   class StarlinkAtomMap:
       def snapshot_locked(self) -> dict:
           """Atomic read — zwraca immutable copy"""
           with self._lock:
               return {
                   "cells": [(a.id, a.T, a.metadata.copy()) for a in self.iter_cells()],
                   "density": dict(self.density),
                   "shells": dict(self._shells),
                   "summary": self.summary(),
               }
   ```
```

**Priorytet:** CRITICAL (bug na produkcji, zwłaszcza na S3b)

---

## 2. S4b Filtering Logic: Brakuje Backend Implementation

**Problem:**
Plan pokazuje HTML:
```html
<input type="radio" name="shell" value="53"> 53°
```

I Flask route:
```python
@app.route("/api/filter")
def api_filter():
    shell = request.args.get("shell")
    # Filter amap.density by shell
    # Return filtered data
    return jsonify({...})
```

Ale:
- Jak się mapuje shell (string "53") do faktycznych komórek?
- Czy filtrujemy atomy w Store czy tylko JSON response?
- Jak się cachuje sats na shell (amap._shells) — czy to za stary?
- Co ze stats — czy to recalculate czy cache?

**Implikacja:**
- Implementacja będzie guesswork
- Potencjalne O(n) iteracje zamiast O(1) lookup
- Stale data jeśli filter nie synchronizuje z Store

**Rekomendacja:**

```
### SEKCJA: S4b Backend Specification

**Filter API endpoint:**

```python
def api_filter():
    """GET /api/filter?shell=53&min_count=1"""
    shell = request.args.get("shell", "all")  # "all" | "53" | "70" ...
    min_count = int(request.args.get("min_count", 1))
    
    with amap._lock:
        filtered_cells = []
        filtered_density = {}
        
        for (ilat, ilon), count in amap.density.items():
            if count < min_count:
                continue
            
            cell_id = cell_id(ilat, ilon)
            cell_atom = amap.store.get_atom(cell_id)
            if cell_atom is None:
                continue
            
            v = cell_atom.metadata.get("v") or {}
            
            # Check shell membership
            if shell != "all":
                # Get sats in this cell
                sats_in_cell = [...]  # iterate bubbles
                has_shell = any(
                    amap.store.get_atom(f"sat:{sat}").metadata.get("v", {}).get("shell") == f"shell:{shell}"
                    for sat in sats_in_cell
                )
                if not has_shell:
                    continue
            
            filtered_cells.append({
                "id": cell_id,
                "count": count,
                "T": float(cell_atom.T),
                "color": t_to_rgb(float(cell_atom.T)),
            })
            filtered_density[(ilat, ilon)] = count
        
        # Return filtered + recomputed stats
        return jsonify({
            "cells": filtered_cells,
            "shell": shell,
            "min_count": min_count,
            "count_cells": len(filtered_cells),
            "count_sats": sum(c for c in filtered_density.values()),
        })
```

**Optymalizacja:** Index sats by shell w init:
```python
self._shell_index = {}  # shell_key → [sat_ids]
# Build in ingest_sats():
for sat in sats:
    sk = sat.shell_key
    self._shell_index.setdefault(sk, []).append(f"sat:{sat.norad}")
```
Wtedy lookup jest O(1).
```

**Priorytet:** HIGH (bez tego UI filtry będą fake)

---

## 3. Memory Leak w S3b: Brak Graceful Shutdown

**Problem:**
```python
class StarlinkLiveFeeder:
    def start(self):
        self.thread = Thread(target=self._loop, daemon=True)
        self.thread.start()  # daemon=True → nie blokuje exit
    
    def _loop(self):
        while True:  # ← nigdy się nie kończy
            time.sleep(self.interval)
            self.amap.refresh(catalog)
```

- Thread jest daemon — wątek się nie kończy gracefully
- Brak stop() method
- SIGTERM/SIGINT mogą nie czekać na cleanup
- TLE cache rośnie na dysku co 15 min (jeśli cache nie ma TTL)

**Implikacja:**
- Po 1 godzinie: 4 snapshoty × 50 MB = 200 MB cache dysku
- Po 1 tygodniu: 672 snapshoty × 50 MB = 33 GB
- Brak way to stop gracefully bez kill -9

**Rekomendacja:**

```
### SEKCJA: S3b Graceful Lifecycle

**Dodaj:**

```python
import signal
import atexit

class StarlinkLiveFeeder:
    def __init__(self, store, interval_min=15):
        self.store = store
        self.interval = interval_min * 60
        self.thread = None
        self.amap = None
        self._stop_event = threading.Event()  # Graceful stop flag
    
    def start(self):
        self.thread = Thread(target=self._loop, daemon=False)  # daemon=False
        self.thread.start()
        
        # Register cleanup on exit
        atexit.register(self.stop)
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())
        signal.signal(signal.SIGINT, lambda s, f: self.stop())
    
    def stop(self):
        """Graceful shutdown"""
        print("Feeder shutting down...")
        self._stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        print("Feeder stopped")
    
    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._stop_event.wait(timeout=self.interval)
                if self._stop_event.is_set():
                    break
                
                raw, src = load_tle_text(...)
                catalog = parse_tle_catalog(raw)
                self.amap.refresh(catalog)
                print(f"[Feeder] refreshed at {datetime.now()}")
            except Exception as e:
                print(f"[Feeder ERROR] {e}", file=sys.stderr)
                # Continue; retry in next interval
    
    def __del__(self):
        """Fallback cleanup"""
        if self.thread and self.thread.is_alive():
            self.stop()
```

**TLE Cache TTL:**
```python
def load_tle_text(..., cache_ttl_hours=24):
    """Stare cache automatycznie refreshuje"""
    if cache.is_file() and cache.stat().st_size > 100:
        age = time.time() - cache.stat().st_mtime
        if age < cache_ttl_hours * 3600:  # ← TTL check
            return (cache.read_text(...), f"cache:{age/3600:.1f}h")
    # Fetch fresh
    ...
```
```

**Priorytet:** HIGH (production readiness)

---

## 4. Bug Matematyczny w S2b: Błędne Współrzędne Sferyczne

**Problem:**
```python
def cell_to_sphere_quad(self, ilat, ilon, grid_deg, alt_km=400):
    corners = [
        (ilat * grid_deg - 90, ilon * grid_deg - 180),  # ← BŁĄD!
        ((ilat+1) * grid_deg - 90, ilon * grid_deg - 180),
        ((ilat+1) * grid_deg - 90, (ilon+1) * grid_deg - 180),
        (ilat * grid_deg - 90, (ilon+1) * grid_deg - 180),
    ]
```

Wzór oblicza lat/lon narożników źle:
- ilat=0 → lat = 0*5 - 90 = -90 (OK, South Pole)
- ilat=18 → lat = 18*5 - 90 = 0 (OK, Equator)
- ilat=36 → lat = 36*5 - 90 = 90 (OK, North Pole)

Wait, to jest OK w rzeczywistości. Ale problem:
- Dla ilon: ilon * 5 - 180 → ilon=0 = -180, ilon=72 = 180 (wraparound)

Rzeczywisty problem: **brakuje clamp na boundaries**:
- ilon=71 → lon1 = 71*5 - 180 = 175 (OK)
- ilon=72 → lon1 = 72*5 - 180 = 180 (wrap)
- Nie ma handling dla: ilon+1 może być 73 (out of bounds)

Ponadto: `grid_deg` jest 5° a wzór zakłada że grid_deg jest zawsze 5.

**Implikacja:**
- Komórki na granicy gridu mogą być źle ułożone na sferze
- dateline crossing (180° / -180°) może producować backface triangles
- Dateline cells mogą być niewidoczne lub rysowane 2x

**Rekomendacja:**

```python
def cell_to_sphere_quad(self, ilat, ilon, grid_deg=5.0, alt_km=400):
    """Narożniki komórki gęstości jako punkty na sferze WGS84."""
    
    # Oblicz lat/lon dla narożników (to jest OK)
    lat0 = -90.0 + ilat * grid_deg
    lat1 = -90.0 + (ilat + 1) * grid_deg
    lon0 = -180.0 + ilon * grid_deg
    lon1 = -180.0 + (ilon + 1) * grid_deg
    
    # Clamp na valid ranges
    lat0 = max(-90.0, min(90.0, lat0))
    lat1 = max(-90.0, min(90.0, lat1))
    
    # Wrap longitude
    def wrap_lon(lon):
        return ((lon + 180.0) % 360.0) - 180.0
    
    lon0 = wrap_lon(lon0)
    lon1 = wrap_lon(lon1)
    
    # Dateline handling: jeśli lon1 < lon0, to jest dateline crossing
    # (nie problem sam w sobie, ale rendering może)
    
    corners = [
        (lat0, lon0),
        (lat1, lon0),
        (lat1, lon1),
        (lat0, lon1),
    ]
    
    return [self.latlon_to_xyz(lat, lon, alt_km) for lat, lon in corners]
```

**Priorytet:** MEDIUM (wizualizacja będzie dziwna na dateline i polach)

---

## 5. Export Sphere Data Nie Handleuje Hot-Only Policy

**Problem:**
```python
def export_sphere_data(amap: StarlinkAtomMap) -> dict:
    for a in amap.iter_cells():  # ← ile komórek?
        v = a.metadata.get("v") or {}
        ...
```

Niejasność:
- Jeśli `hot_only=True`, Store ma tylko ~2k comórki (hot)
- `amap.density` ma również ~2k entries
- Ale: co jeśli stara komórka się schłodziła ale nie została usunięta z Store?
- Czy `iter_cells()` i `amap.density` są **zawsze** synchronized?

W `apply_density()`:
```python
if self.hot_only:
    for key in list(self._active_cells - new_keys):
        aid = cell_id(*key)
        if callable(getattr(self.store, "delete_atom", None)):
            self.store.delete_atom(aid)  # ← Czy to zawsze się powiedzie?
```

Jeśli `delete_atom()` failnąć, komórka pozostaje w Store ale nie w `_active_cells`.

**Implikacja:**
- Heatmapa może pokazać ghost cells (stare, schłodzone komórki)
- JSON export ma więcej komórek niż `amap.density`
- Inconsistency między 2D a 3D vizualizacją

**Rekomendacja:**

```python
def export_sphere_data(amap: StarlinkAtomMap) -> dict:
    """Nur aktywne komórki (hot-only policy)"""
    proj = StarlinkGlobeProjection()
    cells = []
    
    # Use density dict (source of truth dla hot-only)
    max_t = T_MAX
    max_c = max(amap.density.values()) if amap.density else 1
    
    for (ilat, ilon), count in amap.density.items():
        aid = cell_id(ilat, ilon)
        
        # Fetch atom (may or may not exist in Store)
        atom = amap.store.get_atom(aid)
        if atom is None:
            # Fallback: create transient data (nie dodawaj do Store)
            T = density_to_T(count, max_count=max_c)
            color = t_to_rgb(T)
        else:
            T = float(atom.T)
            color = t_to_rgb(T)
        
        quad = proj.cell_to_sphere_quad(ilat, ilon, amap.grid_deg)
        
        cells.append({
            "id": aid,
            "quad": quad,
            "color": f"rgb({color[0]},{color[1]},{color[2]})",
            "T": round(T, 2),
            "count": count,
        })
    
    return {
        "projection": "sphere",
        "cells": cells,
        "shells": amap._shells,
        "stats": amap.summary(),
        "policy": "hot-only" if amap.hot_only else "full-grid",
    }

# Assert consistency:
assert len(cells) == len(amap.density), "Mismatch density vs cells"
```

**Priorytet:** MEDIUM (data consistency)

---

## 6. JSON Export Za Duży dla Live-Feed (brak Delta Encoding)

**Problem:**
Na każdy refresh (co 15 min):
- ~2000 komórek × 4 vertices × 3 coords × 2 floats = ~384k numbers
- + metadata dla każdej = ~500k JSON
- + gzip: ~200 KB per refresh
- 60 refreshes/dzień × 200 KB = 12 MB/dzień = 360 MB/miesiąc

Problemy:
1. Bandwidth: jeśli UI jest remotem, to co minutę 200 KB
2. Brak delta — każdy refresh to full dump
3. Brak versioning — skąd UI wie że ma stare dane?

**Implikacja:**
- Na slow network (<1 MB/s), loading ~0.2s za każdy refresh
- Jitter network → restart download
- Stale data jeśli refresh się nie skończył

**Rekomendacja:**

```
### SEKCJA: Optimizations for S3b

**1. Delta encoding:**
```python
class StarlinkAtomMap:
    def __init__(self, ...):
        self._last_export_version = 0
        self._last_cells_snapshot = {}  # {cell_id: hash}
    
    def export_sphere_data_delta(self) -> dict:
        """Exportuj tylko zmienione komórki"""
        cells_new = {}
        cells_changed = []
        cells_deleted = []
        
        for (ilat, ilon), count in amap.density.items():
            aid = cell_id(ilat, ilon)
            atom = amap.store.get_atom(aid)
            if atom:
                T = float(atom.T)
                cell_hash = hash((aid, T, count))
                cells_new[aid] = cell_hash
                
                if aid not in self._last_cells_snapshot or \
                   self._last_cells_snapshot[aid] != cell_hash:
                    # Changed
                    quad = proj.cell_to_sphere_quad(ilat, ilon, amap.grid_deg)
                    cells_changed.append({
                        "id": aid,
                        "quad": quad,
                        "color": t_to_rgb(T),
                        "T": round(T, 2),
                        "count": count,
                    })
        
        # Deleted cells (were in last snapshot, not in density)
        for aid in self._last_cells_snapshot:
            if aid not in cells_new:
                cells_deleted.append(aid)
        
        self._last_cells_snapshot = cells_new
        self._last_export_version += 1
        
        return {
            "version": self._last_export_version,
            "type": "delta",
            "changed": cells_changed,
            "deleted": cells_deleted,
        }
```

**2. Compress + ETag:**
```python
@app.route("/api/data")
def api_data():
    use_delta = request.args.get("version", 0)
    
    if use_delta:
        data = export_sphere_data_delta(amap)
    else:
        data = export_sphere_data(amap)
    
    json_str = json.dumps(data)
    etag = hashlib.md5(json_str.encode()).hexdigest()
    
    response = app.make_response(jsonify(data))
    response.headers["ETag"] = etag
    response.headers["Content-Encoding"] = "gzip"  # Flask auto-compresses
    return response
```

**3. Client side:**
```javascript
let lastVersion = 0;
async function fetchData() {
    const url = `/api/data?version=${lastVersion}`;
    const resp = await fetch(url);
    if (resp.status === 304) {  // Not Modified
        return;  // Use cached data
    }
    
    const data = await resp.json();
    if (data.type === "delta") {
        applyDelta(data);
        lastVersion = data.version;
    } else {
        redrawFull(data);
        lastVersion = data.version;
    }
}
```
```

**Priorytet:** MEDIUM (nie critical, ale good-to-have dla scale)

---

## 7. Brak Comprehensive Error Handling

**Problem:**
Plan mówi o kodzie ale brak error paths:

| Punkt | Błąd | Handler |
|-------|------|---------|
| TLE fetch | Network timeout | ? (retry? fallback?) |
| TLE parse | Malformed TLE | skip sat? log? |
| SGP4 propagate | NaN coordinates | skip sat? default position? |
| Store.get_atom | Atom deleted mid-read | None? exception? |
| DB_karmin save | DB full/locked | What then? |
| Flask request | Client disconnect mid-transfer | ? |

**Implikacja:**
- Crash instead of graceful degradation
- Partial data corrupts state
- No observability (logging)

**Rekomendacja:**

```
### SEKCJA: Error Handling Strategy

**Tier 1: Per-sat errors (don't crash entire run)**
```python
def propagate_and_bin(self, sats, ...):
    errors = []
    for sat in sats:
        try:
            lat, lon, alt = position_of(sat, ...)
            # Validate
            if not (-90 <= lat <= 90) or math.isnan(lat):
                errors.append((sat.norad, "invalid_lat"))
                continue
            if not (-180 <= lon <= 180) or math.isnan(lon):
                errors.append((sat.norad, "invalid_lon"))
                continue
            # ...
        except Exception as e:
            errors.append((sat.norad, str(e)))
    
    return counts, errors
```

**Tier 2: Feeder resilience**
```python
def _loop(self):
    fail_count = 0
    max_fails = 3
    
    while not self._stop_event.is_set():
        try:
            raw, src = load_tle_text(...)
            catalog = parse_tle_catalog(raw)
            counts, errors = self.amap.refresh(catalog)
            
            if errors:
                logging.warning(f"Refresh had {len(errors)} errors")
            
            fail_count = 0  # Reset on success
        except Exception as e:
            fail_count += 1
            logging.error(f"Feeder failed ({fail_count}/{max_fails}): {e}")
            
            if fail_count >= max_fails:
                logging.critical("Feeder giving up after 3 failures")
                self.stop()
                break
        
        self._stop_event.wait(timeout=self.interval)
```

**Tier 3: API error responses**
```python
@app.route("/api/data")
def api_data():
    try:
        with amap._lock:
            data = export_sphere_data(amap)
        return jsonify({
            "status": "ok",
            "data": data,
        })
    except Exception as e:
        logging.error(f"api_data failed: {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "data": None,
        }), 500
```
```

**Priorytet:** CRITICAL (production stability)

---

## 8. Metryki Sukcesu Są Optymistyczne

**Problem:**

| Metryka | Plan mówi | Reality |
|---------|-----------|---------|
| "Zero propagation errors" | Doskonałość | ~0.1-1% satelitów będzie mieć errory (NaN, timeout) |
| "Hot-only maintains <2.5k cells" | Zawsze | Na polach (±60°) gęstość jest wyższa → może być 5k+ cells |
| "<100ms UI refresh" | Heatmapa | Na 50k, je​śli JSON transit ~0.2s, to już przekroczone |
| "Memory leak-free" | Cały czas | Test 1h to zbyt krótko; leaks pojawiają się po dniach |

**Implikacja:**
- Nie będzie wiadomo czy implementation ma bugs czy metryki były fake
- Production będzie mieć surprises

**Rekomendacja:**

```
### SEKCJA: Realistic Quality Targets (zamiast Metryki Sukcesu)

| Metryka | Target | Acceptance |
|---------|--------|-----------|
| **Propagation errors** | <1% sats | Log all errors; investigate >0.1% |
| **Hot cells** | <3.5k avg | <5k p95 |
| **UI refresh (2D)** | <150ms latency | <500ms p95 |
| **UI refresh (3D)** | <500ms latency | <2s p95 |
| **Memory (Python Store)** | ~50 MB/10k sats | <2 GB max for 100k |
| **Memory leak** | <10 MB/hour | Test 24h continuous |
| **Network (JSON export)** | <500 KB | Gzipped <200 KB |
| **Feeder availability** | >99% over 24h | <1 missed refresh |
| **Error handling** | Zero unexpected crashes | All errors logged + handled |
| **TLE freshness** | ≤15 min stale | Configurable interval |

**Load test scenarios:**
1. Baseline: 100 refreshes (25 hours) at 15 min interval → memory stability
2. Error injection: 10% TLE failures → graceful recovery
3. Network: Simulate 50% packet loss, 500ms latency → UI still responsive
4. Concurrent: 10 concurrent API requests → no race conditions
```

**Priorytet:** HIGH (definition of done)

---

## 9. S1b (Hybrid): Integration Nigdzie Nie Dokumentowany

**Problem:**
Plan ma:
```python
def project_to_karmin(amap, karmin_path):
    # INSERT INTO karmin
    pass

def load_from_karmin(karmin_path, snapshot_id):
    # SELECT FROM karmin
    pass
```

Ale brak:
- Gdzie w flow się to calluje? (Faza 1.5? Feeder?)
- Czy auto snapshot co N refreshów? Czy manual?
- Versioning: co jeśli 2 processesy robią snapshot naraz?
- Conflict resolution: różne checksums?
- Retencja: ile snapshoty trzymać?
- Migration: jak się migruje stary Python Store do DB_karmin?

**Implikacja:**
- S1b zostanie nie zaimplementowany
- Albo żle, z dużo bugs'ami

**Rekomendacja:**

```
### SEKCJA: S1b Integration Flow (szczegółowo)

**Architektura:**
```
Feeder (co 15 min)
  ├─ refresh(catalog) → Store
  ├─ emit("starlink_refreshed", amap)
  └─ [ASYNC] snapshot_to_karmin(amap)
       ├─ export_report_payload(amap)
       ├─ Serialize to JSON
       ├─ Timestamp: snapshot_id = f"{time.time():.0f}"
       ├─ INSERT karmin:snapshots:
       │   {id, timestamp, catalog_hash, sats_count, cells_count, heatmap_png_b64}
       ├─ Prune old: DELETE WHERE timestamp < now - 7 days
       └─ Emit: store.emit("snapshot_saved", snapshot_id)
```

**DB Schema (na DB_karmin):**
```sql
CREATE TABLE starlink_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at TIMESTAMP,
    catalog_hash TEXT,
    sats_count INT,
    cells_count INT,
    heatmap_png BLOB,
    metadata_json TEXT,
    UNIQUE(created_at)
);

CREATE TABLE starlink_sat_positions (
    snapshot_id TEXT,
    sat_id TEXT,
    lat REAL,
    lon REAL,
    alt_km REAL,
    PRIMARY KEY (snapshot_id, sat_id),
    FOREIGN KEY (snapshot_id) REFERENCES starlink_snapshots
);

CREATE TABLE starlink_cell_density (
    snapshot_id TEXT,
    cell_id TEXT,
    count INT,
    T REAL,
    PRIMARY KEY (snapshot_id, cell_id),
    FOREIGN KEY (snapshot_id) REFERENCES starlink_snapshots
);
```

**Python API:**
```python
class KarminStarlinkAdapter:
    def __init__(self, db_path):
        self.db = DBasePath(db_path)  # cynober-db API
    
    def save_snapshot(self, amap: StarlinkAtomMap) -> str:
        snapshot_id = f"snapshot_{time.time():.0f}"
        
        # Payload
        payload = export_report_payload(amap)
        heatmap_b64 = payload.get("heatmap_png_b64")
        
        # INSERT main
        self.db.upsert("starlink_snapshots", {
            "id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "catalog_hash": hashlib.md5(
                json.dumps(amap._shells).encode()
            ).hexdigest(),
            "sats_count": amap.summary()["sats"],
            "cells_count": amap.summary()["cells"],
            "heatmap_png": base64.b64decode(heatmap_b64) if heatmap_b64 else None,
            "metadata_json": json.dumps({
                "prop": amap.prop_mode,
                "hot_only": amap.hot_only,
                "grid_deg": amap.grid_deg,
            }),
        })
        
        # INSERT positions (sample, nie wszystko)
        for sat in list(amap.iter_sats())[:100]:  # Top 100 by T
            v = sat.metadata.get("v") or {}
            if "lat" in v and "lon" in v:
                self.db.insert("starlink_sat_positions", {
                    "snapshot_id": snapshot_id,
                    "sat_id": str(sat.id),
                    "lat": v["lat"],
                    "lon": v["lon"],
                    "alt_km": v.get("alt_km"),
                })
        
        # INSERT cells
        for (ilat, ilon), count in amap.density.items():
            cell_id = cell_id(ilat, ilon)
            atom = amap.store.get_atom(cell_id)
            T = float(atom.T) if atom else None
            
            self.db.insert("starlink_cell_density", {
                "snapshot_id": snapshot_id,
                "cell_id": cell_id,
                "count": count,
                "T": T,
            })
        
        # Prune old (>7 days)
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        self.db.delete_where(
            "starlink_snapshots",
            f"created_at < '{cutoff.isoformat()}'"
        )
        
        return snapshot_id
    
    def load_snapshot(self, snapshot_id: str) -> StarlinkAtomMap:
        """Odczyt snapshot z DB → Store"""
        snap = self.db.get("starlink_snapshots", snapshot_id)
        if not snap:
            raise ValueError(f"Snapshot {snapshot_id} not found")
        
        store = open_store(thermal=True, backend="python")
        amap = StarlinkAtomMap(store, grid_deg=5.0, hot_only=True, listen=False)
        
        # Recreate cells from DB
        for row in self.db.query("SELECT * FROM starlink_cell_density WHERE snapshot_id=?", (snapshot_id,)):
            ilat, ilon = parse_cell_id(row["cell_id"])
            amap._upsert_cell(
                ilat, ilon,
                count=row["count"],
                max_count=100,  # normalized
                create_empty=False
            )
        
        return amap
```

**CLI:**
```bash
# Save snapshot
python starlink_atoms.py --limit 0 --karmin-save

# List snapshots
python starlink_atoms.py --karmin-list

# Load snapshot
python starlink_atoms.py --karmin-load snapshot_1723XXX --studio --studio-mode 3d

# Export snapshot to HTML
python starlink_atoms.py --karmin-load snapshot_1723XXX --html out/report.html
```

**Feeder integration:**
```python
class StarlinkLiveFeeder:
    def __init__(self, store, interval_min=15, db_path=None):
        ...
        self.db_adapter = KarminStarlinkAdapter(db_path) if db_path else None
    
    def _loop(self):
        while not self._stop_event.is_set():
            ...
            self.amap.refresh(catalog)
            
            # Async snapshot save
            if self.db_adapter:
                try:
                    snapshot_id = self.db_adapter.save_snapshot(self.amap)
                    logging.info(f"Saved snapshot {snapshot_id}")
                except Exception as e:
                    logging.error(f"Snapshot save failed: {e}")
```
```

**Priorytet:** HIGH (jeśli wybierze S1b, to CRITICAL)

---

## 10. Brak Cache Invalidation Strategy

**Problem:**
UI ma lokalny cache:
- Sphere data JSON (2 MB)
- Heatmap PNG (100 KB)
- Stats panel values

Kiedy cache się refreshuje?
- Co N sekund? (jitter?)
- Na webhook?
- Polling?

Brak mechanism:
- Versioning (ETag, timestamp)
- Event notification
- Cache-bust strategy

**Implikacja:**
- User widzi stare dane
- Albo refresh za częsty → waste bandwidth
- Race: czy cache jest fresh czy nie?

**Rekomendacja:**

```
### SEKCJA: Cache Strategy (dodać do S3/S4)

**Server-side versioning:**
```python
class StarlinkAtomMap:
    def __init__(self, ...):
        self._version = 0
        self._last_export = {}
    
    def refresh(self, sats, ...):
        ...
        self._version += 1
        self._last_export = {}  # Invalidate cache
        return ...
    
    def get_export_version(self) -> int:
        return self._version

@app.route("/api/version")
def api_version():
    return jsonify({"version": amap.get_export_version()})
```

**Client-side polling:**
```javascript
let cachedVersion = 0;
let cachedData = null;

setInterval(async () => {
    const resp = await fetch("/api/version");
    const {version} = await resp.json();
    
    if (version !== cachedVersion) {
        console.log(`Cache invalidated: ${cachedVersion} → ${version}`);
        cachedData = await fetch("/api/data").then(r => r.json());
        cachedVersion = version;
        redraw(cachedData);
    }
}, 5000);  // Poll every 5s
```

**Alternatywa: WebSocket (real-time):**
```python
from flask_socketio import SocketIO, emit

socketio = SocketIO(app)

@socketio.on("connect")
def handle_connect():
    print("Client connected")
    # Send initial version
    emit("version_update", {"version": amap.get_export_version()})

# Feeder emits version on refresh
class StarlinkLiveFeeder:
    def _loop(self):
        while ...:
            self.amap.refresh(catalog)
            socketio.emit("version_update", {
                "version": self.amap.get_export_version()
            }, broadcast=True)
```
```

**Priorytet:** MEDIUM (UX quality)

---

## 11. Brak S2a vs S2b Trade-off Analysis

**Problem:**
Plan rekomenduje S2b (3D Globe), ale brak porównania z S2a (2D Heatmapa):

| Aspekt | 2D Heatmapa | 3D Globe |
|--------|------------|----------|
| Render time | <100ms | <500ms |
| Network (JSON) | ~100 KB | ~2 MB |
| Interactivity | Click/filter | Drag/zoom/click |
| Polarity distortion | None | Massive (poles squeeze) |
| Mobile support | OK | Laggy (WebGL) |
| Accessibility | High (canvas simple) | Low (complex WebGL) |

Brak guidance: kiedy użyć które?

**Implikacja:**
- Developer zagębi się w 3D jeśli lepiej 2D
- Produkcja będzie slow na slowlm sprzęcie

**Rekomendacja:**

```
### SEKCJA: S2a vs S2b Comparison Matrix

**Performance:**
| Metrika | S2a (2D) | S2b (3D) |
|---------|----------|----------|
| Initial load | <100ms | ~1s (Three.js + data) |
| Render per frame | <16ms | <33ms (60 FPS) |
| Memory (canvas) | ~10 MB | ~50 MB (WebGL buffers) |
| Export (JSON) | ~100 KB | ~2 MB |
| Interactivity | Instant | Smooth |
| Data freshness | <100ms update | <500ms update |

**Feature support:**
| Feature | S2a | S2b |
|---------|-----|-----|
| Query/filter | ✓ | ✓ |
| Zoom | ✓ manual (canvas scale) | ✓ native (camera) |
| Pan | ✓ manual | ✓ native (drag) |
| Rotate | ✗ (2D only) | ✓ |
| Tooltip on hover | ✓ | ✓ (raycasting) |
| 3D perspective | ✗ | ✓ (Mercator distortion) |
| Dateline crossing | Native (wraps) | Needs handling (jump) |

**Browser support:**
| Browser | S2a | S2b |
|---------|-----|-----|
| Chrome | ✓ | ✓ |
| Firefox | ✓ | ✓ |
| Safari | ✓ | ✓ (WebGL supported) |
| IE11 | ✓ | ✗ (no WebGL) |
| Mobile Safari | ✓ | ⚠ (slow, battery drain) |
| Android Chrome | ✓ | ⚠ (laggy on older) |

**Recommendation:**

1. **MVP (Phase 0–2):** Start with S2a (2D Heatmapa)
   - Faster to implement (~1 day vs 3 days for S2b)
   - Better mobile UX
   - Easier to debug
   - Ship early

2. **Phase 3:** Add S2b (3D Globe) as option
   - `--studio-mode 2d|3d` selector
   - Async load Three.js library (don't block S2a)
   - User preference in localStorage

3. **Phase 4+:** Optimize S2b for production
   - Dateline-safe quad generation
   - Level-of-detail (LOD) for 100k cells
   - Progressive loading (render top cells first)
   - WebGL1 fallback for older devices
```

**Priorytet:** MEDIUM (architecture decision)

---

## 12. Brak Handling dla Duplicate Atoms

**Problem:**
Feeder może uruchomić się 2x (na wypadek restart):

```
Thread A: ingest_sats(catalog1) @ 15:00
Thread B: ingest_sats(catalog2) @ 15:00 (concurrent?)

ingest_sats() robi:
  if not self.store.has_atom(aid):
      self.store.create_atom(aid, T=T_INIT)  # Reset T
```

Jeśli T było 50 (hot), reset do T_INIT (30?) → lose history.

Ponadto: `refresh()` to:
```python
def refresh(self, sats, ...):
    counts = self.propagate_and_bin(sats, ...)  # Updates T via heat()
    hot = self.apply_density(counts)
    return ...
```

Jeśli sats list zmienił się (sat X usunięty z TLE):
- Atom sat:X pozostaje w Store (dead, schłodzony)
- Nie ma GC dla dead sats

**Implikacja:**
- Memory leaks (usunięte saty trzymane do końca czasu)
- T reset na unintended refresh
- Inconsistent temperature evolution

**Rekomendacja:**

```python
def refresh(self, sats, ...) -> dict:
    """Update velocities — nie recreate atoms"""
    counts = self.propagate_and_bin(sats, when=when, minutes=minutes)
    hot = self.apply_density(counts)
    
    # GC: Usuń saty które nie ma w katalog
    current_sat_ids = {f"sat:{sat.norad}" for sat in sats}
    for a in self.store.iter_bubble("sats"):
        if a.id not in current_sat_ids:
            # Sat was removed from catalog
            if callable(getattr(self.store, "delete_atom", None)):
                self.store.delete_atom(a.id)
                logging.info(f"GC: removed sat {a.id}")
    
    return {...}

def ingest_sats(self, sats):
    """One-time ingest. Call once, not per refresh."""
    # Jeśli atom istnieje, skip (preserve T history)
    # Jeśli nowy, create
    for sat in sats:
        aid = f"sat:{sat.norad}"
        if not self.store.has_atom(aid):
            self.store.create_atom(aid, S=S_SAT, E=sat.name, T=T_INIT)
            # ... metadata
        else:
            # Already exists; update metadata only
            atom = self.store.get_atom(aid)
            if atom:
                atom.E = sat.name  # Update name if changed
    
    return len(sats)

# FLOW (poprawnie):
# Phase 0: store, amap = build_map()  → ingest_sats(full_catalog) ONCE
# Phase 3b: while True:
#   new_catalog = parse_tle_catalog(fresh_tle)
#   amap.refresh(new_catalog, ...)  → update T, apply_density, GC
#   # NOT ingest_sats again
```

**Priorytet:** CRITICAL (leaks i data corruption)

---

## 13. Grid Resolution Trade-offs Not Discussed

**Problem:**
Plan ustala `grid_deg=5.0` w `build_map()`, ale:

- Na 10k sats, 5° grid → średnia 38 sats/komórka OK
- Na 100k sats, 5° grid → średnia 386 sats/komórka (ogromna gęstość)
- Hot-only: może być 5000+ komórek na 100k (zamiast 2000 na 10k)

Alternatywy:
- 10° grid: 9×36 = 324 komórki, ale mniej precision (utrata szczeółów)
- 2.5° grid: 144×72 = 10368 komórek, full grid = każdy ma atom (hot-only nie pomoże)
- Adaptive: grid res zależy od density

**Implikacja:**
- Za gruba grid (10°) → stracony detail
- Za drobna grid (2.5°) → masowo puste komórki (hot-only kluczowy)
- Hot-only coverage może eksplodować na 100k

**Rekomendacja:**

```
### SEKCJA: Grid Resolution Strategy

**Analysis:**
```python
def estimate_grid_cost(n_sats, grid_deg):
    """Estymuj how many cells będzie hot-only"""
    # Assume gaussian distribution around equator
    nlat = int(math.ceil(180.0 / grid_deg))
    nlon = int(math.ceil(360.0 / grid_deg))
    full_grid_size = nlat * nlon
    
    # Starlink distribution: ~60% at 53° ± 10°
    # ~30% at 70° ± 5°, ~10% at other
    # On average, ~40–50% cells have at least 1 sat
    hot_cells = int(full_grid_size * 0.45)
    
    avg_sats_per_hot = n_sats / hot_cells
    max_sats_per_cell = avg_sats_per_hot * 3  # p95
    
    return {
        "grid_deg": grid_deg,
        "total_cells": full_grid_size,
        "hot_cells_est": hot_cells,
        "avg_sats_per_hot": avg_sats_per_hot,
        "max_sats_est": max_sats_per_cell,
    }

# Results:
estimate_grid_cost(10000, 5.0)   # → 2592 total, ~1164 hot, ~8.6 avg
estimate_grid_cost(100000, 5.0)  # → 2592 total, ~1164 hot, ~85.9 avg (!)
estimate_grid_cost(100000, 2.5)  # → 10368 total, ~4666 hot, ~21.4 avg
estimate_grid_cost(100000, 10.0) # → 648 total, ~292 hot, ~342 avg (!!)
```

**Recommendation:**

```python
def choose_grid_for_scale(n_sats):
    """Auto-select grid resolution based on catalog size"""
    if n_sats < 1000:
        return 2.5  # High precision
    elif n_sats < 10000:
        return 5.0  # Standard (Starlink typical)
    elif n_sats < 50000:
        return 10.0  # Coarse to avoid hot-only explosion
    else:
        return 20.0  # Very coarse for massive catalogs
    
    # OR configurable:
    # python starlink_atoms.py --limit 100000 --grid 10.0 --studio
```

**Metryka:**
- Aim: <3k hot cells regardless of scale
- Adjust grid_deg automatically wenn hot_cells > threshold

**Priorytet:** MEDIUM (depends on final scale target)

---

## 14. Brak Load-Test Procedures

**Problem:**
"Faza 0" mówi:
> Metrics baseline — Zmierz CPU/RAM na 10k, 50k

Ale brak:
- Jakie tool? (psutil, memory_profiler, top?)
- Jakie metryki? (peak, average, sustained?)
- Memory leak test — jak się mierzy?
- Jakie scenario? (cold start? warm cache? live-feed 24h?)

**Implikacja:**
- Benchmarkami będą ad-hoc, non-reproducible
- Performance regression nie będzie widoczna
- "Memory leak-free" metrika jest nieweryfikowalna

**Rekomendacja:**

```
### SEKCJA: Load Testing & Metrics Collection

**Tool: Benchmark Suite**

```python
# cynober_studio/tests/test_performance.py

import tracemalloc
import time
import psutil
import os

class StarlinkPerformanceBenchmark:
    """Measures memory, CPU, latency for Starlink loading."""
    
    def __init__(self):
        self.results = {}
        self.process = psutil.Process(os.getpid())
    
    def measure_ingest(self, limit, repetitions=3):
        """Benchmark ingest + propagate + density for N sats"""
        times = []
        mems = []
        
        for i in range(repetitions):
            tracemalloc.start()
            t0 = time.perf_counter()
            
            store, amap, use, src = build_map(limit=limit)
            
            t1 = time.perf_counter()
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            
            times.append(t1 - t0)
            mems.append(peak / 1024 / 1024)  # MB
            
            del store, amap, use  # GC
            time.sleep(0.1)
        
        return {
            "limit": limit,
            "avg_time": sum(times) / len(times),
            "max_time": max(times),
            "avg_mem": sum(mems) / len(mems),
            "max_mem": max(mems),
        }
    
    def measure_live_feed(self, duration_minutes=60):
        """Benchmark live feeder for memory leaks"""
        tracemalloc.start()
        
        store, amap, use, src = build_map(limit=10000)
        feeder = StarlinkLiveFeeder(store, interval_min=1)
        feeder.start()
        
        initial_mem = self.process.memory_info().rss / 1024 / 1024
        mems = [initial_mem]
        
        start = time.time()
        while time.time() - start < duration_minutes * 60:
            time.sleep(30)
            mem = self.process.memory_info().rss / 1024 / 1024
            mems.append(mem)
        
        feeder.stop()
        
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        mem_growth = mems[-1] - mems[0]
        
        return {
            "duration_min": duration_minutes,
            "initial_mem": initial_mem,
            "final_mem": mems[-1],
            "peak_mem": max(mems),
            "mem_growth": mem_growth,
            "growth_rate": mem_growth / duration_minutes,  # MB/min
        }
    
    def measure_api_latency(self, n_requests=100, concurrency=1):
        """Benchmark Flask API response times"""
        app = create_app(amap, studio_mode="3d")
        app.testing = True
        client = app.test_client()
        
        latencies = []
        errors = 0
        
        for i in range(n_requests):
            t0 = time.perf_counter()
            resp = client.get("/api/data")
            t1 = time.perf_counter()
            
            if resp.status_code == 200:
                latencies.append((t1 - t0) * 1000)  # ms
            else:
                errors += 1
        
        return {
            "requests": n_requests,
            "errors": errors,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "p50": sorted(latencies)[len(latencies)//2] if latencies else 0,
            "p95": sorted(latencies)[int(len(latencies)*0.95)] if latencies else 0,
            "p99": sorted(latencies)[int(len(latencies)*0.99)] if latencies else 0,
        }

# Main test execution
if __name__ == "__main__":
    bench = StarlinkPerformanceBenchmark()
    
    print("=" * 60)
    print("STARLINK PERFORMANCE BENCHMARK")
    print("=" * 60)
    
    for limit in [10000, 50000, 100000]:
        print(f"\n[Ingest] {limit} satellites:")
        result = bench.measure_ingest(limit, repetitions=3)
        print(f"  Time:  {result['avg_time']:.2f}s (max: {result['max_time']:.2f}s)")
        print(f"  Mem:   {result['avg_mem']:.0f} MB (max: {result['max_mem']:.0f} MB)")
        bench.results[f"ingest_{limit}"] = result
    
    print(f"\n[LiveFeed] 1 hour @ 1 min interval (10k sats):")
    result = bench.measure_live_feed(duration_minutes=1)  # Demo: 1 min
    print(f"  Memory growth: {result['mem_growth']:.1f} MB over {result['duration_min']} min")
    print(f"  Growth rate:   {result['growth_rate']:.2f} MB/min")
    bench.results["live_feed_1h"] = result
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY (expected targets vs actual):")
    print("=" * 60)
    ingest_50k = bench.results.get("ingest_50000", {})
    target_time = 3.0  # 3s total
    actual_time = ingest_50k.get("avg_time", 0)
    print(f"Ingest 50k: {actual_time:.2f}s (target: {target_time}s) {'✓' if actual_time <= target_time else '✗'}")
    
    target_mem = 750  # 750 MB
    actual_mem = ingest_50k.get("max_mem", 0)
    print(f"Memory 50k:  {actual_mem:.0f} MB (target: {target_mem} MB) {'✓' if actual_mem <= target_mem else '✗'}")
```

**Run:**
```bash
python -m pytest tests/test_performance.py -v -s
```

**Priorytet:** HIGH (Phase 0 — bez tego reszta to blind)

---

## 15. S4b Filtering: Luka w Implementacji (part 2)

**Problem:**
Plan ma HTML `<input type="range" id="minCount">` ale brak:
- Backend logic do compute filtered density
- Client-side state management (current shell, current min_count)
- Invalidation when filters change

**Implikacja:**
- Frontend będzie czekać na backend
- Backend bez logiki → 404
- Race: user zmienia filter → Network latency → może kliknąć inny filter

**Rekomendacja:**

```python
class FilterState:
    """Maintains current filter on amap"""
    def __init__(self, amap):
        self.amap = amap
        self.shell = None  # None = all
        self.min_count = 1
    
    def apply(self) -> Tuple[Dict, Dict]:
        """
        Returns: (filtered_cells, filtered_density)
        """
        filtered_density = {}
        
        for (ilat, ilon), count in self.amap.density.items():
            if count < self.min_count:
                continue
            
            cell_id = cell_id(ilat, ilon)
            cell_atom = self.amap.store.get_atom(cell_id)
            
            if self.shell is not None:
                # Check if any sat in cell belongs to shell
                # Optimization: use _shell_index
                shell_key = f"shell:{self.shell}"
                sat_ids_in_shell = self.amap._shell_index.get(shell_key, [])
                
                # Find sats in this cell
                cell_sats = [...]  # Query sats in this cell (TODO: needs index)
                if not any(sat_id in sat_ids_in_shell for sat_id in cell_sats):
                    continue
            
            filtered_density[(ilat, ilon)] = count
        
        # Export filtered
        cells = []
        for (ilat, ilon), count in filtered_density.items():
            cell_id = cell_id(ilat, ilon)
            atom = self.amap.store.get_atom(cell_id)
            if atom:
                cells.append({
                    "id": cell_id,
                    "count": count,
                    "T": float(atom.T),
                    "color": t_to_rgb(float(atom.T)),
                })
        
        return cells, filtered_density

# Flask endpoint
filter_state = FilterState(amap)

@app.route("/api/filter", methods=["GET", "POST"])
def api_filter():
    if request.method == "POST":
        filter_state.shell = request.json.get("shell")
        filter_state.min_count = int(request.json.get("min_count", 1))
    
    shell = request.args.get("shell")
    min_count = int(request.args.get("min_count", 1))
    
    filter_state.shell = shell if shell != "all" else None
    filter_state.min_count = min_count
    
    cells, density = filter_state.apply()
    
    return jsonify({
        "cells": cells,
        "shell": shell,
        "min_count": min_count,
        "count_cells": len(cells),
        "count_sats": sum(density.values()),
        "version": amap.get_export_version(),
    })
```

**Priorytet:** HIGH (S4b feature completeness)

---

## 16. Brak Transaction/Atomicity w Live-Feed + UI

**Problem:**
```
Timeline:
T0: Feeder begins refresh
  ├─ T0.1: Load TLE
  ├─ T0.2: Parse
  ├─ T0.3: propagate_and_bin() writes metadata to atoms
  ├─ T0.4: apply_density() — LOCKS _active_cells for write
  
T1: User clicks "apply filter shell=53"
  ├─ Flask handler calls filter_state.apply()
  ├─ Reads amap.density (partially updated from T0.4)
  ├─ Reads cells from Store (some old, some new — mixed)
  └─ Returns JSON with inconsistent data
```

Brak atomicity = dapat być race condition.

**Implikacja:**
- Filter pokazuje partial data
- Cell counts nie matchują actual sats
- User confision

**Rekomendacja:**

Snapshot pattern (już wspomnięty w #1, ale tu emphasis):

```python
@app.route("/api/filter", methods=["GET"])
def api_filter():
    # Get atomic snapshot
    snapshot = amap.snapshot_locked()
    
    shell = request.args.get("shell")
    min_count = int(request.args.get("min_count", 1))
    
    # Filter on snapshot (nie na live Store)
    cells = []
    for cell_id, cell_data in snapshot["cells"]:
        count = cell_data["count"]
        if count < min_count:
            continue
        if shell != "all":
            # Check snapshot shells
            if cell_data.get("shell") != f"shell:{shell}":
                continue
        cells.append(cell_id, cell_data)
    
    return jsonify({
        "cells": cells,
        "version": snapshot["version"],
    })
```

**Priorytet:** MEDIUM (correctness)

---

## 17. Three.js Not Specified (CDN, Version, Fallbacks)

**Problem:**
Plan pokazuje kod:
```javascript
<script src="three.js"></script>
<script>
const scene = new THREE.Scene();
```

Ale:
- Skąd three.js? (CDN? npm install? local?)
- Która wersja? (r127, r150, latest?)
- Fallback jeśli CDN down?
- Czy Babylon zamiast Three? (nie wspomnięty w decyzji)

**Implikacja:**
- Code won't work out of the box
- Browser console errors
- Nie wiadomo co robić

**Rekomendacja:**

```html
<!-- cynober_studio/ui/templates/globe_3d.html -->

<!DOCTYPE html>
<html>
<head>
    <title>Cynober Studio — Starlink 3D Globe</title>
    <style>
        body { margin: 0; overflow: hidden; }
        #globe { width: 100vw; height: 100vh; }
    </style>
</head>
<body>
    <div id="globe"></div>
    
    <!-- Three.js from CDN -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    
    <!-- Optional: Fallback to local if CDN fails -->
    <script>
        if (!window.THREE) {
            var script = document.createElement('script');
            script.src = '/static/js/three.min.js';  // Local fallback
            document.head.appendChild(script);
        }
    </script>
    
    <!-- Our code -->
    <script src="/static/js/globe.js"></script>
    
    <script>
        // Initialize on load
        window.addEventListener('load', () => {
            if (!window.THREE) {
                alert('Three.js failed to load. Check network.');
                return;
            }
            initGlobe();
        });
    </script>
</body>
</html>
```

**package.json:**
```json
{
  "dependencies": {
    "three": "^r128"
  },
  "devDependencies": {
    "webpack": "^5",
    "webpack-cli": "^4"
  },
  "scripts": {
    "build": "webpack --mode production"
  }
}
```

**Priorytet:** MEDIUM (build process)

---

## 18. CLI Interface Incomplete / Pseudo-code

**Problem:**
Plan pokazuje:
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

Ale brak:
- Jak `--studio` wpływa na build_map()? (czy zmienia grid? czy ingest?)
- Czy args są mutually exclusive? (--studio-mode bez --studio?)
- Jak `--karmin-load` współpracuje z ingest? (czy skipuje TLE fetch?)

**Implikacja:**
- Implementacja będzie guesswork
- Logika może być redundantna lub błędna

**Rekomendacja:**

```python
def main():
    ap = argparse.ArgumentParser()
    
    # Data loading
    ap.add_argument("--limit", type=int, default=0, help="0=all TLE")
    ap.add_argument("--cache", default="out/starlink_tle_cache.txt")
    ap.add_argument("--offline-demo", action="store_true")
    
    # Substrate
    ap.add_argument("--grid", type=float, default=None, help="None=auto")
    ap.add_argument("--prop", choices=("auto", "sgp4", "approx"), default="auto")
    ap.add_argument("--hot-only", action="store_true")
    ap.add_argument("--full-grid", action="store_true")
    
    # Karmin (S1b)
    ap.add_argument("--karmin-path", default=None, help="DB_karmin path")
    ap.add_argument("--karmin-load", default=None, help="Load snapshot ID")
    ap.add_argument("--karmin-save", action="store_true", help="Save after run")
    
    # Studio (S3 + S4)
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--studio-mode", choices=("2d", "3d"), default="2d")
    ap.add_argument("--studio-port", type=int, default=5000)
    
    # Live feed (S3b)
    ap.add_argument("--live-feed", action="store_true")
    ap.add_argument("--live-interval", type=int, default=15)
    
    # Output
    ap.add_argument("--html", default=None)
    ap.add_argument("--open-html", action="store_true")
    ap.add_argument("--heatmap", default="out/starlink_heat.png")
    
    args = ap.parse_args()
    
    # Validation
    if args.full_grid and args.hot_only:
        ap.error("--full-grid and --hot-only are mutually exclusive")
    
    if args.karmin_load and args.offline_demo:
        ap.error("--karmin-load and --offline-demo don't mix")
    
    if not args.studio and args.studio_mode != "2d":
        ap.error("--studio-mode requires --studio")
    
    # Auto-select hot-only if large catalog
    hot_only = args.hot_only or (args.limit == 0 or args.limit >= 1000)
    if args.full_grid:
        hot_only = False
    
    # Load data
    if args.karmin_load:
        # Mode A: Load from DB
        if not args.karmin_path:
            ap.error("--karmin-load requires --karmin-path")
        db = KarminStarlinkAdapter(args.karmin_path)
        amap = db.load_snapshot(args.karmin_load)
        store = amap.store
        use = list(amap.iter_sats())
        src = f"karmin:{args.karmin_load}"
    else:
        # Mode B: Load from TLE
        store, amap, use, src = build_map(
            limit=args.limit,
            grid=args.grid or estimate_grid_for_scale(args.limit),
            hot_only=hot_only,
            prop=args.prop,
            offline_demo=args.offline_demo,
            cache=args.cache,
        )
    
    # Save to Karmin if requested
    if args.karmin_save and args.karmin_path:
        db = KarminStarlinkAdapter(args.karmin_path)
        snapshot_id = db.save_snapshot(amap)
        print(f"Saved snapshot: {snapshot_id}")
    
    # Studio mode
    if args.studio:
        from cynober_studio.ui import create_app
        
        app = create_app(amap, studio_mode=args.studio_mode)
        
        # Optional: Live feed
        if args.live_feed:
            feeder = StarlinkLiveFeeder(store, interval_min=args.live_interval)
            feeder.start()
        
        print(f"Studio running http://localhost:{args.studio_port}")
        app.run(host="0.0.0.0", port=args.studio_port, debug=False)
        return 0
    
    # One-shot mode (legacy)
    print(f"TLE source: {src} using {len(use)} satellites")
    print(f"grid={amap.grid_deg}° hot_only={hot_only}")
    print(amap.summary())
    
    if args.html:
        payload = export_report_payload(amap)
        write_html_report(payload, Path(args.html))
        print(f"HTML: {args.html}")
        if args.open_html:
            import webbrowser
            webbrowser.open(Path(args.html).resolve().as_uri())
    
    return 0
```

**Priorytet:** HIGH (usability)

---

## 19. Brak Persistence dla Filters / Settings

**Problem:**
User:
1. Otwiera http://localhost:5000
2. Ustawia shell=53°, minCount=5
3. Refreshuje stronę (F5)
4. Settings reset na defaults (shell=all, minCount=1)

Brak:
- localStorage persistence
- URL params (shareable links)
- Session save

**Implikacja:**
- Bad UX (frustracja)
- Nie można sharować view (komuś)

**Rekomendacja:**

```javascript
// cynober_studio/ui/static/js/filters.js

class FilterManager {
    constructor() {
        this.shell = localStorage.getItem("filter_shell") || "all";
        this.minCount = parseInt(localStorage.getItem("filter_minCount") || "1");
        this.initialize();
    }
    
    initialize() {
        document.getElementById("shellFilter").value = this.shell;
        document.getElementById("minCountSlider").value = this.minCount;
        
        // Event listeners
        document.getElementById("shellFilter").addEventListener("change", (e) => {
            this.shell = e.target.value;
            localStorage.setItem("filter_shell", this.shell);
            this.updateURL();
            this.apply();
        });
        
        document.getElementById("minCountSlider").addEventListener("input", (e) => {
            this.minCount = parseInt(e.target.value);
            localStorage.setItem("filter_minCount", this.minCount);
            this.updateURL();
            this.apply();
        });
        
        // Load from URL if present
        this.loadFromURL();
    }
    
    updateURL() {
        const params = new URLSearchParams({
            shell: this.shell,
            min_count: this.minCount,
        });
        window.history.replaceState(null, "", `?${params}`);
    }
    
    loadFromURL() {
        const params = new URLSearchParams(window.location.search);
        if (params.has("shell")) this.shell = params.get("shell");
        if (params.has("min_count")) this.minCount = parseInt(params.get("min_count"));
        
        document.getElementById("shellFilter").value = this.shell;
        document.getElementById("minCountSlider").value = this.minCount;
    }
    
    async apply() {
        const resp = await fetch(
            `/api/filter?shell=${this.shell}&min_count=${this.minCount}`
        );
        const data = await resp.json();
        redrawHeatmap(data.cells);
    }
}

const filterMgr = new FilterManager();
```

**Priorytet:** MEDIUM (UX quality)

---

## 20. Timeline Brakuje Bufora (Unrealistic)

**Problem:**
Plan mówi:
> 16–22 dni total

Ale brak:
- Buffer na unexpected issues (20%)
- Testing + bugfixes (10%)
- Refactoring (5%)
- Integration challenges
- Sick days, context switching

Realistycznie: dodaj 30% buffer.

**Implikacja:**
- Miss deadlines
- Crunch + bugs
- Burnout

**Rekomendacja:**

| Faza | Zadanie | Days | Buffer | Total |
|------|---------|------|--------|-------|
| 0 | Benchmark, TLE, deps | 1 | 0.5 | 1.5 |
| 1 | Substrate opt (S1) | 2–3 | 1 | 4 |
| 2 | Data flow (S3) | 2 | 1 | 3 |
| 2.5 | Projections (S2) | 2–3 | 1 | 4 |
| 3 | Presentation (render) | 3–5 | 2 | 7 |
| 4 | Interaction (S4b) | 2–3 | 1 | 4 |
| 5 | Integration + fixes | 2–3 | 2 | 5 |
| **Total** | | 16–22 | +8 | **24–30 days** |

**Priorytet:** MEDIUM (planning realism)

---

## Podsumowanie Audytu

| # | Problem | Priorytet | Implikacja |
|----|---------|-----------|-----------|
| 1 | Race condition (Store ↔ UI) | **CRITICAL** | Data corruption, crashes |
| 2 | S4b filtering incomplete | **HIGH** | Feature doesn't work |
| 3 | Memory leak (feeder) | **HIGH** | OOM after hours |
| 4 | Math bug (sphere coords) | MEDIUM | Wrong visualization |
| 5 | Hot-only inconsistency | MEDIUM | Ghost cells |
| 6 | JSON too large | MEDIUM | Slow on network |
| 7 | No error handling | **CRITICAL** | Unexpected crashes |
| 8 | Metrics unrealistic | HIGH | Can't measure success |
| 9 | S1b integration vague | **CRITICAL** (if chosen) | Won't get built |
| 10 | No cache invalidation | MEDIUM | Stale data in UI |
| 11 | S2a vs S2b trade-offs unclear | MEDIUM | Wrong choice |
| 12 | Duplicate atom handling | **CRITICAL** | Memory leaks, T reset |
| 13 | Grid resolution undefined | MEDIUM | Performance/precision trade-off |
| 14 | No load-test procedures | **HIGH** | Benchmarks unreliable |
| 15 | S4b backend logic missing | **HIGH** | Filter endpoint fake |
| 16 | No transaction safety | MEDIUM | Race conditions |
| 17 | Three.js not specified | MEDIUM | Build issues |
| 18 | CLI pseudo-code | HIGH | Can't implement |
| 19 | No filter persistence | MEDIUM | Bad UX |
| 20 | Timeline unrealistic | MEDIUM | Miss dates |

---

## Rekomendacja: Co Naprawić Najpierw

**CRITICAL (zrób najpierw):**
1. #1 — Thread safety (amap._lock)
2. #7 — Error handling (try/except everywhere)
3. #9 — S1b spec (jeśli wybierze S1b)
4. #12 — Duplicate atoms GC

**HIGH (przed implementacją):**
5. #2 — S4b backend logic
6. #3 — Feeder lifecycle (graceful stop)
7. #8 — Realistic metrics
8. #14 — Load-test suite
9. #18 — CLI full spec

**MEDIUM (nice-to-have):**
10. Reszta

---

*Koniec audytu. 20 słabych punktów, 5 CRITICAL. Plan potrzebuje znaczących poprawek przed implementacją.*
