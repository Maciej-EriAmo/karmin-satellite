# Reach Studio — relacyjność KarmazynOs w Cynober Studio

**Status:** COMPLETE — F0 + W1–W5 + **Live root** (session-only GC · `depends_on` graph)  
**Kod:** `engine/reach_studio.py` · szwy: `engine/map.py`, `engine/build.py`, `ui/app.py`  
**Zasada jądra:** temperatura mówi *kiedy*; osiągalność mówi *czy*.

To nie jest drugi silnik gęstości. To **widzialny i sterowalny reach**
obok istniejącego pipeline’u. `Store.tick()` zostaje z tą samą semantyką.

---

## 1. Prawo (nie mylić warstw)

| Warstwa | Co to jest | SoT? |
|---------|------------|------|
| **Density** | `StarlinkAtomMap.density` + hot-only cell atoms (`T` ∝ count) | **Tak** — hotspoty, SLA, default `/api/data` |
| **Reach view** | Domknięcie bąbla `session:{id}` (walk jak `_reachable`, ale **z korzenia sesji**) | Nie — widok |
| **Ghost** (W2) | `retained_tomb` ∩ domena mapy | Nie — osobna warstwa |
| **Impact** (W3) | skutek cool/scope na cells/hazard | Nie — raport / highlight |
| **Resonance** (W4) | HRR browse | Nie — highlight |
| **Decisions** (W5) | mini system-tick na fleetach | Nie — log |

1. **Density pozostaje SoT.** Reach / ghost / impact nie podmieniają `density`.
2. Domyślne `GET /api/data` **bez** `reach=1` = kontrakt jak przed wdrożeniem.
3. Żadnego full conjunction i żadnego O(N²) na satelitach.
4. SLA 50k: reach filtruje **po** prop/bin; nie mnoży kosztu SGP4.
5. `simulate=true` domyślnie przy impact (W3).
6. Reach **nie** jest obowiązkowym polem snapshotu (meta opcjonalna OK).

---

## 2. Flagi

| Zmienna | Wartości | Default |
|---------|----------|---------|
| `CYNOBER_REACH` | `0` \| `1` | **`1`** (dev) |
| `CYNOBER_REACH_MODE` | `off` \| `session` \| `ghost` \| `impact` | `session` |

- `CYNOBER_REACH=0` albo `CYNOBER_REACH_MODE=off` → produkt jak przed wdrożeniem
  (brak session root, `/api/reach` zgłasza `enabled: false`, `?reach=1` ignorowane).
- `session` — W1 (ten dokument).
- `ghost` / `impact` — W2 ghost działa przy włączonym reach (`session`+).

Runtime: `StudioState.reach_mode` nadpisuje env, gdy niepuste.

---

## 3. Identyfikatory atomów i bąbli

| Rodzaj | ID | Uwagi |
|--------|-----|--------|
| Sat | `sat:{norad}` | już w `ingest_sats` |
| Cell | `cell:{ilat}:{ilon}` | `engine.grid.cell_id` |
| Shell bubble | `shell:{inc}` | np. `shell:53` |
| Fleet bubble | `fleet:{id}` | np. `fleet:starlink` |
| Session root | `session:{id}` | domyślnie `session:default` |

Wiązania sesji używają **id atomu** jako klucza (`sat:…`, `cell:…`), nie `E`
(unika kolizji nazw w `import_to_bubble`).

Katalog (`starlink` / `sats` / `grid`) **nie jest kasowany** przy zmianie scope.
Sesja przebudowuje tylko własne bindings.

---

## 4. Session as root (W1)

Przy `build_map` / starcie Studio (gdy flaga włączona):

```text
session_bubble = store.create_bubble("session:default", root=True)
set_session_scope(shell, fleet, country, min_count)
  → wybrane saty + ich bieżące cell atoms
session_reach() → set[atom_id]   # walk z bąbla sesji, nie union wszystkich roots
```

`starlink` zostaje korzeniem Store — scope sesji **nie** odkurza katalogu
przy `tick()`. `session_reach()` **nie** woła `store._reachable()` (to byłby
union `starlink` ∪ session). Walk startuje wyłącznie od `session:*`.

`GET /api/data?reach=1` / `snapshot(reach_only=True)`:

- density tylko w komórkach, które mają ≥1 sat w reach **albo** cell sam w reach;
- `T` w komórce nadal z SoT density (nie przeliczamy gęstości).

Filtr UI przy włączonym Reach view = `POST /api/session` (zmiana korzenia),
nie tylko przycięcie listy `/api/filter`.

---

## 4b. Ghost (W2)

Po `store.tick()` zimny atom **w reach** idzie do `retained_tomb` (trzymany),
poza reach — vacuum. Ghost to **osobna warstwa**:

- `kind=retained` — T < T_TOMB, w session reach
- `kind=cold` — COLD (żywy), w session reach
- poza reach + zimny → **nie** w ghost

`POST /api/ghost/demo` schładza próbkę satów w sesji, żeby prawo T×reach
było widać od razu (inaczej Studio bez ticka nigdy nie pokaże ghost).

---

## 4c. Impact (W3)

Lekki indeks przy `propagate` / `rebuild_bin_index`:

```text
cell(ilat,ilon) → sats currently binned there
sat:{norad}     → current cell
```

`POST /api/impact` (`simulate=true` default):

- `or_shell` / `cool_sats` / `or_fleet`
- `affected_cells`, `cells_emptied`, `reach_before/after`, `hazard_delta_estimate`
- **bez** mutacji store i **bez** `version++`
- `simulate=false` — cool + tick (density SoT i tak zostaje)

UI: przycisk **Impact** na pasku mapy, panel 5 linii, obrys komórek 5 s
(amber = hit, crimson = emptied).

---

## 4d. Resonance (W4)

`GET /api/resonance?q=shell:53&k=20` → `{ enabled, hits:[{id,sim}], cells }`.

- Z HRR: `store.resonance` na atomach z `E`, mapowanie na cells.
- Bez HRR: `enabled: false`, **bez 500**, plus lexical (shell/fleet/nazwa).
- Highlight cyjan na mapie 5 s — nie zastępuje filtrów.

---

## 4e. System tick (W5)

Węzły: `session:default`, `fleet:*`, `layer:density`, `layer:hazard`.  
Krawędzie stałe: session→fleets (protect), density→fleets (cascade soft),
hazard→density (notify).

`POST /api/system_tick` woła `Store.tick()` gdy `settle_local≥1` (UI: 1),
zbiera `T_agg` per fleet i pisze `decisions[]` (`retain` / `note` / `cool_hint`).
`cool_hint` jest **doradczy** — nic nie chłodzi. Koszt O(F) fleets.
Density SoT nietknięte. Panel **Decisions** — ostatnie 10 linii.

---

## 4f. Live root — to, czego skrypt nie sfałszuje

Domyślnie `starlink` **też** jest korzeniem: scope nie odkurza katalogu
(`tick` zachowuje zimne atomy, bo są osiągalne z katalogu). To tryb
kompatybilny ze skryptem.

**Live root ON** — jedyny korzeń Store to `session:*`. TLE zostaje w
Pythonie (`StudioState.catalog`). Potem:

| | w sesji | poza sesją |
|--|---------|------------|
| gorący | żyje | żyje aż ostygnie |
| zimny | **retained TOMB** (Ghost) | **vacuum** — atom znika |

`POST /api/attention {commit:true}` (albo zmiana scope przy włączonym live)
chłodzi poza sesją i woła **to samo** `Store.tick()`. Mapa = domknięcie.
`Restore` wstawia z powrotem `starlink` jako root i wciąga katalog TLE.

Komórka nosi żywe krawędzie: `cell.v.depends_on = [sat:…]`.
`POST /api/impact` czyta **graf**, nie boczny indeks (`source: graph`).

---

## 5. API (W1)

| Endpoint | Zachowanie |
|----------|------------|
| `GET /api/reach` | `{ enabled, mode, session, scope, n_reach, n_sats, n_cells }` — **liczniki**, bez listy satów |
| `POST /api/session` | body: `shell`, `fleet`, `country`, `min_count` → `set_session_scope` → `version++` |
| `GET /api/data?reach=1` | density tylko w reach sesji + `reach_view` / `reach` meta |
| `GET /api/ghost` | retained/cold w session reach (liczniki + cells; sample satów) |
| `POST /api/ghost/demo` | ochłodź próbkę w reach → retained TOMB (density SoT nietknięte) |
| `POST /api/impact` | `impact_of_cooling` · `simulate=true` domyślnie |
| `GET /api/resonance` | W4 HRR browse (`?q=&k=20`); bez HRR `{enabled:false}` + lexical |
| `POST /api/system_tick` | W5 mini tick · O(fleets) · decisions |
| `GET /api/decisions` | ostatni log (≤10) |
| `GET/POST /api/attention` | live root · commit vacuum · restore catalog |
| `GET /api/export` | plik JSON/MD (`?format=json\|md&reach=1&sats=1`) |

Bez flagi / bez `reach=1`: kształt i wartości density jak dotychczas.

UI 50k: preset 400 / 2k / 10k / **50k** (SLA usable) + slider + pole liczbowe.

---

## 6. Kolejność toru

```text
F0  ten dokument + flagi + ID          ← done
W1  session root + Reach view          ← done
W2  Ghost / retained layer + export    ← done
W3  impact_of_cooling + highlight      ← done
W4  resonance (HRR + lexical degrade)  ← done
W5  mini system_tick + decisions       ← done
```

W1–W3 obowiązkowe. W4–W5 gdy W1–W3 stabilne.

Czego **nie** robić w tym torze: przepisywanie substratu, pełny ServiceGraph,
ciężki 3D ghost na start, obowiązkowy zapis reach do snapshotu.

---

*Cynober Studio · reach = silnik uwagi na żywym grafie atomów, nie wycięty PNG.*
