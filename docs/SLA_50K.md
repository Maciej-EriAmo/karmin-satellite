# Karmin Satellite — 50k SLA / Kontrakt skali

**Status:** ACTIVE · **SLA version:** 1.0.0 · **Date:** 2026-08-11  
**Code:** `engine/sla.py` · **Scale canon:** `docs/ARCHITECTURE_LIMITS.md` · **Baseline:** `docs/capacity_baseline.json`  
**API:** `GET /api/sla`

> **Design target = 50 000 sats (usable).** Ceiling 100 000 is a hard cap, not the UX budget.  
> **Cel projektowy = 50 000 satelitów (usable).** Sufit 100 000 to twardy cap, nie budżet UX.

---

## 1. Scope / Zakres

| EN | PL |
|----|-----|
| One map / one Studio session | Jedna mapa / jedna sesja Studio |
| Pure-Python thermal store, SGP4, hot-only, grid 5° | Store pure-Python, SGP4, hot-only, siatka 5° |
| Offline capacity plane (synthetic catalog) for gate tests | Płaszczyzna capacity offline (katalog syntetyczny) do bramek |
| HTTP Studio API must scale with **cells**, not **N sats** | API HTTP skaluje się z **komórkami**, nie z **N satów** |

**Out of scope for this SLA (later):** analytics tooling, Cynober DB RPC, full bilingual UI polish, edit-atoms.

---

## 2. Numbers / Liczby

| Symbol | Target (design) | Hard (merge-block) | Meaning |
|--------|-----------------|--------------------|---------|
| `SLA_USABLE_SATS` | **50 000** | — | Recommended operating load |
| `SLA_CEILING_SATS` | — | **100 000** | Never exceed in v1 without substrate change |
| Cold e2e @50k | **&lt; 10 s** | **&lt; 30 s** | ingest+refresh+export meta+sphere |
| Prop SGP4 @50k | **&lt; 5 s** | **&lt; 15 s** | `prop_ms` |
| Peak tracemalloc @50k | **&lt; 256 MB** | **&lt; 1024 MB** | process planning ≥512 MB free @usable |
| Export density JSON @50k | **&lt; 200 KB** | **&lt; 500 KB** | `/api/data`-class payload without PNG |
| Hot cells (synthetic) | ~2 k | **&lt; 5 k** | saturates with grid |
| Hot cells p95 (UI real) | 2–5 k | **&lt; 8 k** | quads / density rows |
| Live interval comfort | **900 s (15 min)** | — | full SGP4 rebin @50k |
| Live interval min | **60 s** | warn below | tight but allowed |
| Live interval forbidden | — | **&lt; 5 s** | not supported for full SGP4 @ usable |
| Prop errors | **0** | **0** | required |
| Density ↔ cells consistency | **ok** | **ok** | required |

**Measured baseline (2026-08-11):** 50k e2e ~**5.7 s**, peak ~**148 MB**, export ~**77 KB**, cells ~**1.8 k**, 0 errors → **PASS target**.

---

## 3. Product rules / Reguły produktowe

1. **Design UX, timers, and API under 50k** — not under CLI default 400.  
   **Projektuj UX, timery i API pod 50k** — nie pod default CLI 400.
2. **Never promise &gt; 100k** in v1 without a substrate decision.  
   **Nigdy nie obiecuj &gt; 100k** w v1 bez decyzji o substracie.
3. **Default CLI 400** stays a *dev sample*, not architecture max.  
   **Default CLI 400** to *sample deweloperski*, nie max architektury.
4. **API never dumps full sat positions** (`sat_positions`, `positions`, …).  
   **API nigdy nie zrzuca pełnych pozycji satów**.
5. Snapshots may store density (+ optional sat sample); full 100k TLE JSON is a conscious disk cost.  
   Snapshoty: density (+ opcjonalny sample satów); pełne 100k TLE w JSON = świadomy koszt dysku.
6. Above usable (50k…100k): log `NOTE: … above recommended operating budget`.  
   Powyżej usable: log `NOTE: … above recommended operating budget`.
7. Capacity regression gate: `python tests\test_capacity.py` must keep **50k green** against **hard** SLA.  
   Bramka regresji: 50k green względem **hard** SLA.

---

## 4. API contract / Kontrakt API

| Endpoint | Scales with | Forbidden |
|----------|-------------|-----------|
| `GET /api/data` | density / cells (~2–8k) | O(N) sat lat/lon arrays |
| `GET /api/sphere` | hot cells / quads | per-sat mesh |
| `GET /api/filter` | filtered cells | full catalog dump |
| `GET /api/sla` | constant | — |
| Snapshot file | density (+ optional sample) | silent full TLE unless explicit |

Shape checks: `engine.sla.assert_api_payload_shape`.

---

## 5. Live feed / Live

| Interval | @50k verdict |
|----------|--------------|
| ≥ 900 s | **comfort OK** |
| 60–900 s | OK tight (expect some contention) |
| 5–60 s | **warn** — demo-only / small N |
| &lt; 5 s full SGP4 | **forbidden** at usable scale |

`engine.sla.evaluate_live_interval(interval_sec)` · feeder status may include `sla`.

---

## 6. How to verify / Jak weryfikować

```bat
cd /d C:\Users\drwis\karmin-satellite
python -m unittest tests.test_sla -v
python tests\test_capacity.py
:: optional ceiling:
set CYNOBER_CAPACITY_CEILING=1
python tests\test_capacity.py
```

Merge block if @50k: `prop_errors>0` **or** `elapsed_s>=30` **or** `peak_tracemalloc_mb>=1024` **or** export ≥500 KB **or** consistency fail.

Compare prop_ms / peak_mb @10k and @50k to `docs/capacity_baseline.json` after engine changes.

---

## 7. Roadmap after this SLA / Po tym SLA

| Item | When |
|------|------|
| Optional Cynober DB RPC bridge | after SLA |
| Analytics tooling | later |
| Fuller EN UI strings | later (docs already PL+EN here) |
| Soak 30 min live-feed | ops / low |

---

*Karmin Satellite · SLA 1.0.0 · design against 50k · measure, don’t guess.*
