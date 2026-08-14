# Cynober Studio — instrukcja obsługi

**UI language: English.** Etykiety przycisków poniżej są takie, jak na ekranie.  
To jest prywatny warsztat badawczy: gęstość publicznych katalogów TLE + kontekst słoneczny na atomach termicznych. **Nie jest** operacyjnym SSA, certyfikatem radiacyjnym ani Space-Track.

Wejście: `http://127.0.0.1:8765/` · CLI: [`CLI.md`](CLI.md) · status: [`PROJECT_STATUS.md`](PROJECT_STATUS.md)  
English: [`USER_GUIDE.en.md`](USER_GUIDE.en.md)

---

## 1. Start

```bat
cd /d C:\Users\drwis\cynober_studio
python -m pip install -r requirements.txt

:: bez sieci (syntetyczne TLE)
python main.py studio --offline-demo --limit 40 --open-browser

:: live Celestrak
python main.py studio --limit 400 --open-browser
python main.py studio --fleet debris --limit 400 --open-browser
```

Domyślny port **8765**. Zatrzymanie: `Ctrl+C` w terminalu.

| Flaga | Znaczenie |
|-------|-----------|
| `--offline-demo` | Bez sieci; syntetyczny katalog |
| `--fleet ID` | `starlink`, `oneweb`, `debris`, `starlink,oneweb`, `all` |
| `--limit N` | Ile obiektów wciągnąć. `0` = cały katalog (sufit 100 000) |
| `--country CC` | Filtr SATCAT / heurystyka (`US`, `UK`, …) |
| `--open-browser` | Otwórz UI |
| `--studio-mode 3d` | Start od globu |
| `--live-feed` | Odświeżanie pozycji (domyślnie co 900 s) |

Gdy Celestrak odda 503, Studio pomija padniętą chmurę i ładuje resztę (albo cache z `out/tle_*.txt`).

---

## 2. Co widać na górze

| Badge | Co pokazuje |
|-------|-------------|
| `boot` / `live` / `loading…` | Stan sesji |
| `vN` | Wersja mapy (rośnie po refresh / rebuild) |
| `2d` / `3d` | Aktywny widok |
| `solar …` | Klasa rozbłysku · F10.7 · Kp · dopisek `stub`/`cache` gdy nie live |
| `hazard …` | Proxy narażenia grupy |
| `reach off` / `reach: N sats` | Czy włączony widok sesji |

---

## 3. Widok: 2D i 3D

**2D heatmap** — mapa komórek 5° (domyślnie). Pixel komórki sam się skaluje: mało satów → duże bloki, dużo → ~1 px.

| Przycisk 2D | Skutek |
|-------------|--------|
| **Density** | Gęstość (źródło prawdy mapy) |
| **Hazard** | Ekspozycja słoneczna × waga gęstości (proxy, nie dawka) |
| **Blend** | Mix Density + Hazard |
| **Ghost** | Retained / cold w zasięgu sesji |

**3D globe** — ta sama gęstość na sferze. Przeciągnij = obrót, scroll = zoom.

| Przycisk 3D | Skutek |
|-------------|--------|
| **Density** | Termiczna gęstość |
| **Exposure** | To samo co 2D Hazard (nie „promieniowanie fizyczne”) |
| **Blend** | Mix |

Bez pogody NOAA warstwa Exposure **nie wymyśla** score — zostaje Density.

---

## 4. Ładowanie katalogów

Sekcja **Load satellites**.

1. Wybierz **Catalog / fleet**.
2. Opcjonalnie **Country filter**.
3. Ustaw limit: presety **400 / 2k / 10k / 50k**, suwak, pole liczbowe albo **Full catalog**.
4. **Load satellites** — pobierz / przebuduj mapę.
5. **Reload** — to samo co Load satellites (aktualny wybór).
6. **Load debris** — publiczne chmury Celestrak (nie Space-Track):
   - Fengyun-1C (2007)
   - Cosmos 2251 + Iridium 33 (2009)
   - Microsat-R (2019; często już pusta)
   - Cosmos 1408 (2021; mało kawałków)
7. W liście jest też **Public debris (5 event clouds)** i **All curated fleets** (bez `active` i bez debris).

`all` = fleety komunikacyjne. Debris nie wchodzi do „wszystkich satelitów”.

Offline (`--offline-demo`) daje syntetyczne TLE z etykietą floty — do nauki UI, nie do badań orbitalnych.

---

## 5. Filtr powłoki (S4b)

**Shell** — inklinacja (`shell:53`, …) albo **All**.  
**Min count** — ukryj komórki z małą liczbą.

| Przycisk | Skutek |
|----------|--------|
| **Refresh** | Ponowna propagacja (SGP4) aktualnego katalogu |
| **Reset filter** | All + min 1 |
| **Impact** | *What-if*: co jeśli ta powłoka ostygnie. **Symulacja** — gęstość zostaje |

Gdy włączony jest **Reach view**, zmiana shella przebudowuje korzeń sesji (`POST /api/session`), nie tylko wycina PNG.

---

## 6. Reach, Ghost, Live root

Prawo: **T mówi kiedy, reach mówi czy.**  
**Density** zawsze zostaje źródłem prawdy mapy, dopóki nie włączysz Reach view.

### Reach / Ghost (lewy panel)

| Kontrolka | Skutek |
|-----------|--------|
| **Reach view** | Mapa tylko w domknięciu sesji |
| **Ghost under density** | Duchy pod warstwą gęstości |
| **Demo: cool in reach** | Sztucznie schładza próbkę w sesji, żeby Ghost miał co pokazać |

Bez ticka / dema Ghost jest pusty — to nie jest błąd.

### Pasek nad mapą

| Przycisk | Skutek |
|----------|--------|
| **Live root** | Jedyny korzeń GC = sesja. Poza sesją + zimny = vacuum |
| **Commit** | Schłodź poza sesją i `tick()` — znikają naprawdę |
| **Restore** | Wróć korzeń katalogu i wciągnij TLE z powrotem |
| **Reach view** | To samo co checkbox w panelu |
| **Impact** | Symulacja cool powłoki; obrys komórek 5 s (amber = hit, crimson = emptied) |
| **Fleet log** | Jeden `Store.tick()` + dziennik flot. `cool_hint` **nie chłodzi** |
| **Search** | Nazwa / `shell:53` / `fleet:starlink`. HRR tylko gdy naprawdę trafi; inaczej `scope` / `lexical` |
| **JSON** / **MD** | Pobierz widok |

Liczniki na pasku: `live`, `reach`, `ghost`, `impact`, `tick`, `density SoT`.

---

## 7. Pogoda, horyzonty, geo

Wszystko to **proxy badawcze** (NOAA SWPC + geometria). Nie ephemeris zaćmienia, nie dawka.

| Sekcja | Co robi |
|--------|---------|
| **Solar weather** | Flare, F10.7, Kp. **Refresh weather** wymusza pobranie. `Mode`: `live` / `cache` / `stub` |
| **Horizons (H3)** | 1h / 6h / 24h — zanik + krótki trend indeksów, nie prognoza misji |
| **Shell hazard** | Score per powłoka |
| **Altitude / sunlit** | Pasma wysokości + ułamek oświetlenia (geometria) |
| Obramowanie mapy/globu | Aura ∝ stresowi słonecznemu. Bez pogody = 0 (bez sztucznego świecenia) |

---

## 8. Analyze, Library, Timeline

**Analyze** — statystyki bieżącego widoku: liczba komórek, Σ count, max, hotspot, p50/p90, top komórki.

**Library** — klatki na dysku `out/snapshots/` (gitignore).

| Przycisk | Skutek |
|----------|--------|
| **Save server** | Zapisz snapshot (+ meta `solar` gdy jest) |
| **Refresh list** | Odśwież listę |
| klik w klatkę | Wczytaj ją na mapę |

**Timeline** — metryki gęstości po zapisanych klatkach.

| Przycisk | Skutek |
|----------|--------|
| **Refresh timeline** | Lista ramek |
| **Compare newest** | Delta dwóch najnowszych |

**JSON file** / **MD file** — pobierz aktualny widok. Zaznacz **Include TLE in JSON file** jeśli chcesz linie TLE w eksporcie.

**Push DB** — opcjonalny most do Cynober DB. Przycisk jest **ukryty**, dopóki nie ma `cynober_client`. Lokalne snapshoty zostają primary.

---

## 9. CLI — skrót funkcji

Pełne flagi: [`CLI.md`](CLI.md).

| Komenda | Funkcja |
|---------|---------|
| *(domyślna)* | One-shot mapa / heatmap / snapshot |
| `studio` | UI HTTP |
| `weather` | JSON NOAA |
| `predict` | Horyzonty 1h/6h/24h |
| `hazard` | Score na mapie |
| `report` | HazardReport JSON/MD |
| `geo` | Wysokość + sunlit |
| `fleets` | Lista katalogów |
| `timeline` | Porównanie snapshotów |

```bat
python main.py fleets
python main.py --fleet debris --limit 400 --no-heatmap
python main.py weather
python main.py report --offline-demo --limit 40 --offline --json --md
python main.py --offline-demo --limit 40 --snapshot-save
```

---

## 10. Testy

```bat
python run_tests.py
python tests\test_capacity.py
python tests\test_bench.py
```

`run_tests.py` ładuje `tests/test_*.py` po ścieżce (omija cień `tests` z site-packages). Capacity / bench są opcjonalne (skala).

---

## 11. Czego to nie robi

- Operacyjnego śledzenia zderzeń / Conjunction Assessment  
- Autoryzowanego Space-Track  
- Edycji atomów ani „agentów satelitów”  
- Natywnego slaba Rust w ścieżce Studio (Python Store)  
- Przełącznika języka EN/PL (UI = English)  
- Stosowania `cool_hint` z Fleet log — to tylko dziennik  

Gęstość (`density`) jest SoT wizualizacji. Reach / Ghost / Impact / Fleet log to warstwy obok, nie drugi silnik orbity.

---

## 12. Czerwony pasek — burza elektromagnetyczna

Zwykły próg na publicznych indeksach NOAA SWPC, teraz albo na horyzoncie 6h (H3):

- Kp ≥ 5, albo
- rozbłysk M/X, albo
- score ≥ 55

Bez dodatkowego równania. Nie magnetometr, nie detekcja z mapy satelitów.

Nachodzenie ops∩debris jest w API jako `crowding` (licznik) i **nie** zapala paska.
