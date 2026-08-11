# Cynober Studio — szybki przegląd jakości (2026-08-11)

**Zakres:** `engine/`, `ui/`, `tests/` (bez vendored `substrate/` — osobny kanon jądra).

## Ocena skrótowa

| Obszar | Nota | Komentarz |
|--------|------|-----------|
| Poprawność kontraktu | **B+** | snapshot / filter / version / RLock solidne; 14 testów zielonych |
| Bezpieczeństwo wątków | **B** | amap RLock OK; StudioState.lock + amap = podwójny, ale spójny |
| Struktura | **B** | monolit pocięty (tle/prop/grid/map/export_2d/build/cli); facade `starlink_atoms` |
| API / UI | **B** | stdlib HTTP czytelne; JS bez bundlera — OK na MVP |
| Błędy / observability | **B-** | prop_errors jest; brak structured logging (print/stderr) |
| Bezpieczeństwo HTTP | **B** | static path guard jest; CORS `*` tylko dev — OK private localhost |
| Testy | **B+** | unit + concurrent + API; brak długiego soak 30 min (manual) |

## Mocne strony

1. **Jasny SoT:** `density` + `snapshot()` — UI nie czyta store „na dziko”.
2. **Audit-driven:** RLock, GC satów, shell_index, filter backend — nie tylko HTML.
3. **Zero ciężkich deps** w Studio (sgp4 + Pillow; HTTP stdlib).
4. **Testowalność:** ThreadingHTTPServer na porcie 0 w testach.

## Słabe punkty / tech debt

| # | Problem | Priorytet | Status |
|---|---------|-----------|--------|
| Q1 | Monolit `engine/starlink_atoms.py` (CLI+HTML+map+TLE) | MEDIUM | **DONE** (split + Faza 4) |
| Q2 | `refresh_catalog` gubi oryginalny `limit` przy `reload_tle` | HIGH | **DONE** (`StudioState.limit`) |
| Q3 | Brak LiveFeeder (S3b) | HIGH | **DONE** (`engine/live_feeder.py`) |
| Q4 | `except Exception` szerokie w handlerach (OK MVP, mało sygnału) | LOW | later |
| Q5 | HTML report w silniku nadal marka „Karmazyn” w title | LOW | cosmetic |
| Q6 | UI poll 5s bez ETag/delta | LOW | later |
| Q7 | `create_bubble` przy każdym shell — idempotentność zależy od store | LOW | OK w praktyce |
| Q8 | Unused typing imports w `ui/app.py` | LOW | **DONE** |

## Rekomendacje (kolejność)

1. Faza 3: feeder + limit fix + stop clean.  
2. Split `starlink_atoms` → `tle.py` / `map.py` / `export.py` / `cli.py` gdy ruszasz 3D.  
3. Opcjonalnie: `logging` module zamiast print w feederze.  
4. Nie dodawać Flask dopóki stdlib wystarcza.

## Werdykt

**Gotowe do Faza 3.** Fundament (lock/snapshot/API) jest wystarczająco dobry, żeby live feed nie siedział na piasku. Największy dług to rozmiar pliku silnika, nie logika.
