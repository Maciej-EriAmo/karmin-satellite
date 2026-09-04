# Delta View — tylko zmiany (Karmin Satellite)

**Status:** design + MVP tor A→B→C  
**Nie jest to:** ops SSA / katalog CDM „kolizji”.  
**Jest to:** research screen — *co się zmieniło* między klatkami A→B.

---

## 1. Intencja

Zwykła mapa = **stan obecny** (wszystkie gorące komórki).  
**Delta View** = tło ciemne + wyłącznie:

| Sygnał | Znaczenie badawcze |
|--------|-------------------|
| **Appeared cells** | Nowa gęstość w komórce (0→N) |
| **Vanished cells** | Komórka wygasła (N→0) — proxy „strata / odpływ” |
| **Grew / shrunk** | Δ count w komórce |
| **Vanished sats** *(opc.)* | NORAD w A, brak w B — gdy snapshot ma listę `sats` |
| **Hazard Δ** | Zmiana score/severity / Kp / flare watch między klatkami |

### Utracone satelity vs „kolizje”

Myśl o **kolizjach SSA** zostaje poza MVP.  
**Utracone / znikające** z floty (np. Starlink po silnym evencie słonecznym) jest **możliwe do pokazania** jako:

1. **Komórki vanished / shrunk** (zawsze, cells-scale, SLA-friendly)  
2. **Diff NORAD** gdy zapisano `sats` w snapshotach (`include_sats` / lokalny dump) — nie domyślnie przy density-first RPC  

Disclaimer UI: *research proxy · not conjunction assessment*.

---

## 2. Fundament w kodzie

| Element | Gdzie |
|---------|--------|
| `compare_density` | `engine/analytics.py` |
| Timeline / compare API | `GET /api/timeline?a=&b=` |
| Hazard / weather | `/api/hazard`, `/api/weather`, `/api/predict` |
| 2D / 3D canvas | `heatmap.js`, `globe.js` |

---

## 3. Tor wdrożenia

| Krok | Co |
|------|-----|
| **D** | Ten dokument |
| **A** | Tryb UI **Delta** · 2D tylko komórki Δ · **live change log** |
| **B** | Pasek hazard Δ (score / severity / alert) |
| **C** | Te same komórki Δ na globe 3D |

### Live log (na bieżąco)

Ring-buffer zdarzeń (serwer + panel UI):

```text
[ts] delta A→B · appeared=… vanished=… ΔΣ=…
[ts] sat loss · n=… (jeśli NORAD diff)
[ts] hazard · sev A→B · score …
```

Źródła wpisów: ręczne Compare / Enter Delta / opc. po `POST /api/refresh` gdy jest poprzedni snapshot „baseline”.

---

## 4. API (MVP)

```http
GET /api/delta?a=snap_X&b=snap_Y
GET /api/delta/log?limit=40
POST /api/delta/baseline   # zapamiętaj bieżącą gęstość jako A (live)
```

Odpowiedź `/api/delta` = `compare_density` + `cells_changed[]` + opc. `sats_lost[]` / `sats_new[]` + `hazard_delta`.

---

## 5. UI

- Przycisk **Delta** obok 2D / 3D  
- Wybór A/B z timeline (domyślnie: dwa najnowsze) albo **Live vs baseline**  
- Canvas: tylko `delta ≠ 0` (zieleń ↑ / czerwień ↓)  
- Panel **Change log** (scroll, najnowsze na górze)  
- B: pasek pod mapą — hazard Δ  
- C: warstwa globe `delta`

---

## 6. Poza zakresem (świadomie)

- Prawdziwe conjunction / CDM / COLA  
- Pełny dump satelitów na każdym refreshu (łamie SLA)  
- Automatyczne „winę” flare → strata bez korelacji czasowej (log może *sugerować*, nie orzekać)

---

*Karmin Satellite · Delta View · 2026-09*
