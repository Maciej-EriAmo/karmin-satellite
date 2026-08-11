# Starlink on Karmazyn atoms

**Project:** KarmazynOs · `software/starlink_atoms.py`  
**Status:** MVP complete (phases 0–3 + HTML report)  
**Language of this doc:** English  
**Polish plan (archive of phases):** [PLAN_STARLINK_ATOMS.md](PLAN_STARLINK_ATOMS.md)

---

## Goal

Show that **one atom substrate** can multi-task a real-scale public workload without a second database:

| Concern | Same Store |
|---------|------------|
| Catalog | `starlink:sat` atoms (NORAD / TLE / lat·lon) |
| Heatmap | `starlink:cell` atoms — **temperature T = density** |
| Grouping | **bubbles** (`starlink`, `sats`, `grid`, `shell:*`) |
| Query / watch | list HOT·WARM, `state_changed` events |
| Scripts | Lua tools on an **isolated view Store** |
| Human view | PNG + self-contained HTML report |

**Law (kernel):** temperature says *when*; reachability says *whether*.

This is **not** a Starlink ops competitor. It is a **substrate demo**: constellation as load on thermal memory physics shared with media, agents, and OS tools.

---

## What makes it different

- One lifecycle for sat, cell, GIF frame, and agent fact — not map service + SQL + bus + dashboard.
- Density lives as **heat** on cells; idle empty bins need not be immortal atoms (`--hot-only`).
- Guest Lua mounts a **projected Store** so catalog stats are not polluted by the language heap.
- Public TLE only (Celestrak); no proprietary telemetry.

---

## Layout (source of truth)

| Path | Role |
|------|------|
| `software/starlink_atoms.py` | Host: fetch TLE, SGP4, bubbles, density, heatmap, HTML, Lua isolate |
| `lua_bin/starlink.lua` | OS tool — catalog view (isolated) |
| `lua_bin/starlink_hot.lua` | HOT / WARM cell list |
| `Documents/STARLINK_ATOMS.md` | **This file** (EN overview + proof) |
| `Documents/PLAN_STARLINK_ATOMS.md` | PL phase checklist (done) |
| `out/` | Generated only (gitignored): heat PNG, report HTML/JSON, TLE cache |

**Not in repo:** regenerated heatmaps, TLE cache (~2 MB), HTML embeds — run CLI to rebuild.

---

## Quick start

```powershell
cd C:\Users\drwis\KarmazynOs
pip install sgp4 pillow   # once

# Full public catalog, SGP4, hot-only cells, HTML dashboard
python software/starlink_atoms.py --limit 0 --prop sgp4 --hot-only --html --open-html

# Subset + isolated Lua tool
python software/starlink_atoms.py --limit 400 --prop sgp4 --lua

# Offline smoke (no network)
python software/starlink_atoms.py --offline-demo --limit 40 --full-grid --html
```

Dependencies: **sgp4** (propagation), **Pillow** (PNG). Substrate: `KARMAZYN_SUBSTRATE=python` for string atom ids (Lua-friendly).

---

## Proof of effectiveness (measured MVP)

Runs on a normal desktop (Windows), public Celestrak supplemental Starlink TLE, Python Store:

| Metric | Result |
|--------|--------|
| Catalog size | **~10 768** satellites (full group) |
| Propagate (SGP4) | **~200–240 ms** full catalog, **0** prop errors (typical run) |
| Cell atoms (`--hot-only`) | **~2 0xx** bins with count &gt; 0 (not full 2592 grid) |
| Shell bubbles | e.g. **43° / 53° / 70° / 97° / 98°** from inclination |
| End-to-end (ingest + bin + heat) | **&lt; 0.5 s** with warm TLE cache |
| Lua isolate | catalog `alive` **unchanged** after `:tool starlink` |
| Shared mode (before isolate) | host stats ballooned (~10×–20×) from Lua heap — **fixed by view Store** |
| HTML | single-file report: canvas density, PNG, shell bars, top cells |

**Qualitative proof of the multi-task thesis:** the same `Store` simultaneously holds sats, heated cells, shell bubbles, and event hooks; a separate guest Store only *views* a projection (meta + cells) so the catalog remains the source of truth.

Reproduce:

```powershell
python software/starlink_atoms.py --limit 0 --prop sgp4 --hot-only --lua --html
# expect: prop_errors=0, catalog after lua total == catalog before, html written under out/
```

---

## Phase status

| Phase | Status |
|-------|--------|
| 0 Spike (atoms, bubbles, PNG) | Done |
| 1 SGP4 + `--live` | Done |
| 2 Hot-only density atoms | Done |
| 3 Lua OS surface + isolate | Done |
| HTML visualization report | Done |

**Optional later:** boot-time seed for `:tool starlink`, Studio/SDL blit, viewport `note_visible`, KarminQL export, gossip mirror — see plan § Next.

---

## X / naming

API and code: **bubbles**.  
Public jokes about “boobs” are marketing copy only — never identifiers.
