# Karmin Satellite — Granice architektury (skala)

**Status:** MEASURED · **Data pomiaru:** 2026-08-11  
**Maszyna:** Windows desktop · pure-Python Store · SGP4 · hot-only · grid 5°  
**Źródło kodu:** `engine/constants.py` · `tests/test_capacity.py`  
**Surowy raport:** `out/capacity_report.json` (gitignore) · kopia bazowa: `docs/capacity_baseline.json`

> **To jest pierwszy kanon skali produktu.** Wszystkie decyzje UI/API/DB opierają się na tych liczbach.  
> **SLA produktowe (target vs hard, live, API):** [`docs/SLA_50K.md`](SLA_50K.md) · kod: `engine/sla.py` · `GET /api/sla`.

---

## 1. Kanon (liczby twarde)

| Symbol | Wartość | Znaczenie |
|--------|---------|-----------|
| **ARCH_USABLE_SATS** | **50 000** | Zalecany budżet **użytkowy** jednej mapy / sesji |
| **ARCH_CEILING_SATS** | **100 000** | **Sufit** twardej architektury (cap w `build_map` gdy `arch_cap=True`) |
| **DEFAULT_LIMIT** | **400** | Domyślny sample CLI (dev) — **nie** limit produktu |
| **ARCH_MAX_SATS** | = ceiling | Alias wsteczny (= 100 000) |

```text
skala dev (default CLI)     400
public Starlink (typowo)    ~10–11k
użytkowo (target)           50k   ← projektujemy pod to
sufit (hard cap)            100k  ← nie przekraczamy w v1 bez decyzji
```

### Co to NIE jest

| Mit | Prawda |
|-----|--------|
| Default 400 = max systemu | Nie — to tylko wygodny sample |
| Sufit = 12k | Błędny epizod; **odwołany** |
| 50–100k z planu = science fiction | **50k zmierzone OK**, **100k zmierzone OK** na tym stacku |

---

## 2. Płaszczyzna pomiaru

| Parametr | Wartość |
|----------|---------|
| Katalog | synthetic `build_demo_catalog(n)` — unikalne norad 1..n |
| Prop | SGP4 (`prop=sgp4`) |
| Grid | 5° |
| Komórki | **hot-only** (density SoT) |
| Backend | pure-Python thermal Store |
| Sieć | brak (offline) |

Powtórzenie:

```bat
cd /d C:\Users\drwis\karmin-satellite
set CYNOBER_CAPACITY_CEILING=1
python tests\test_capacity.py
```

---

## 3. Wyniki (baseline 2026-08-11)

### 3.1 Pełny pipeline (ingest + refresh + export meta + sphere)

Źródło: `capacity_report.json` / `docs/capacity_baseline.json`

| N sats | e2e [s] | prop_ms | cells (hot) | prop_err | tracemalloc peak [MB] | export JSON [B] | sphere [ms] |
|--------|---------|---------|-------------|----------|------------------------|-----------------|-------------|
| 1 000 | 0.12 | 42 | ~595 | 0 | 3.6 | ~28k | 6 |
| 10 000 | 1.11 | 380 | ~1 737 | 0 | 31 | ~71k | 17 |
| **50 000** | **5.73** | **2 120** | **~1 846** | **0** | **148** | **~77k** | **34** |
| **100 000** | **11.56** | **4 203** | **~1 872** | **0** | **294** | **~78k** | **53** |

**Verdict usable 50k:** OK  
**Verdict ceiling 100k:** OK (powyżej usable — świadomie)

### 3.2 RSS procesu (osobny przebieg, warm machine)

Źródło: `out/capacity_rss.json` (lokalnie)

| N | e2e [s] | prop_ms | Δ RSS [MB] | RSS after [MB] |
|---|---------|---------|------------|----------------|
| 1k | 0.04 | 12 | ~4 | ~40 |
| 10k | 0.36 | 151 | ~31 | ~71 |
| 50k | 1.67 | 650 | ~135 | ~195 |
| 100k | 3.64 | 1 335 | ~206 | ~350 |

> RSS zależy od GC, warm-up i kolejności przebiegów — **orientacyjnie** ~3 MB / 1k satów w Δ, nie liniowo idealnie na 100k (reuse heap).

---

## 4. Co wynika ze skali (implikacje)

### 4.1 Czas

- Prop SGP4 **≈ liniowy** w N (~40 ms/1k → ~2.1 s/50k → ~4.2 s/100k w cold full pipeline).
- **Użytkowo 50k:** e2e **&lt; 10 s** cold — akceptowalne na one-shot / ręczny refresh; live co 15 min jest komfortowe.
- **Sufit 100k:** e2e **~12 s** cold — OK jako batch; nie jako 1 Hz UI loop.

### 4.2 Pamięć

- Tracemalloc peak: **~150 MB @ 50k**, **~300 MB @ 100k** (same atomy + metadata).
- Process RSS after 100k: **~350 MB** rzędu — mieści się w desktopie.
- Budżet planowania: **≥ 512 MB RAM** wolne na Studio @ usable; **≥ 1 GB** headroom na ceiling + UI + browser.

### 4.3 Komórki (hot-only)

- Liczba **cell atoms** rośnie **subliniowo** i saturuje się (~1.8–1.9k na synthetic demo przy 5°).
- Real Starlink ma inną gęstość (pasy, inklinacje) — **komórki 2–5k typ, p95 &lt; 8k** to sensowny target UI, nie 50k quads.
- **UI / JSON export skaluje się z komórkami**, nie z N satów — kluczowe dla 3D/2D.

### 4.4 Sieć / API

| Payload | @50k (hot cells ~1.8k) | Uwaga |
|---------|------------------------|--------|
| `/api/data` density | ~80 KB | lekki |
| `/api/sphere` | rośnie z cells + quads | nadal &lt; kilka MB typ. |
| Pełne pozycje satów w JSON | **unikać** | O(N) — tylko snapshot plikowy / sampling |

### 4.5 Live feed

| Interval | @50k | @100k |
|----------|------|-------|
| 15 min (900 s) | prop ~2 s → **OK** | prop ~4 s → **OK** |
| 60 s | OK, z lekkim jitter UI | granica komfortu |
| &lt; 5 s full SGP4 | **nie** | **nie** |

---

## 5. Reguły produktowe (z granic)

1. **Projektuj UX i SLA pod 50k** (usable).  
2. **Nigdy nie obiecuj &gt; 100k** w v1 bez zmiany substratu (Rust slab / sharding).  
3. **Default CLI 400** zostaje — nie mylić z limitem.  
4. **`--limit 0`** ładuje katalog i **tnie do ceiling**.  
5. Powyżej usable (50k): log `NOTE: ... above recommended operating budget`.  
6. Snapshoty: domyślnie density + sample satów; full 100k TLE w JSON = świadomy koszt dysku.  
7. Bench regresji: `tests/test_capacity.py` musi trzymać **50k green**; ceiling opcjonalnie `CYNOBER_CAPACITY_CEILING=1`.

---

## 6. Acceptance (definition of scale-done)

| Kryterium | Target | Zmierzono |
|-----------|--------|-----------|
| 50k SGP4 hot-only, 0 prop errors | wymagane | **PASS** |
| 50k e2e cold | &lt; 30 s | **~5.7 s** |
| 50k consistency density↔cells | ok | **PASS** |
| 100k SGP4 hot-only, 0 errors | ceiling smoke | **PASS ~11.6 s** |
| Hot cells @50–100k synthetic | &lt; 5k | **~1.8–1.9k** |
| Export density @50k | &lt; 500 KB | **~77 KB** |

---

## 7. Co mierzyć przy zmianie architektury

Po każdej zmianie map/store/prop:

```bat
python tests\test_capacity.py
:: porównaj prop_ms i peak_mb @10k i @50k z docs/capacity_baseline.json
```

Jeśli @50k: `prop_errors>0` **lub** `elapsed_s>=30` **lub** `peak_tracemalloc_mb>=1024` **lub** export ≥500 KB **lub** consistency fail → **blokuj merge** (patrz hard SLA w `engine/sla.py`).

---

## 8. Historia korekt

| Data | Zmiana |
|------|--------|
| 2026-08-11 | Pierwszy pomiar 1k/10k/50k/100k; usable=50k, ceiling=100k |
| (wcześniej) | Błędny epizod ARCH=12k — **odwołany** |

---

*Karmin Satellite · granice = kontrakt skali · nie zgadujemy — mierzymy.*
