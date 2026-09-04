# CLI reference — Karmin Satellite

**Entry:** `python main.py` · module: `engine/cli.py`  
**Principle:** solar / geo / fleets as **subcommands**; map build is the default command.

```text
python main.py [command] [options]
python main.py --help          # top-level help
```

---

## Commands

| Command | Role |
|---------|------|
| *(default / `run`)* | One-shot map build, heatmap, optional snapshot/RPC/Lua |
| `studio` | HTTP Studio UI (2D/3D) |
| `weather` | NOAA SWPC snapshot JSON (no map) |
| `predict` | H3 horizons 1h/6h/24h |
| `hazard` | H1 scores on a built map |
| `report` | H4 HazardReport JSON/MD + optional snapshot `solar` |
| `geo` | H5 altitude bands + sunlit fraction |
| `fleets` | H7 list public Celestrak fleets |
| `timeline` | B snapshot density timeline / compare |

Legacy: `python main.py --studio …` still works (maps to studio).  
Removed flag soup: `--weather` / `--predict` / `--hazard` → use subcommands.

---

## Map options (run · studio · hazard · report · geo)

| Flag | Default | Notes |
|------|---------|--------|
| `--limit N` | 400 | `0` = whole catalog (arch ceiling applies) |
| `--offline-demo` | off | Synthetic TLE (no network) |
| `--fleet ID` | `starlink` | H7: `oneweb`, `starlink,oneweb`, `debris` (5 public Celestrak clouds), … |
| `--country CC` | — | A: SATCAT/heuristic country (`US`, `UK`, …) |
| `--no-satcat` | off | skip country annotation |
| `--hot-only` / `--full-grid` | auto | Auto hot-only when limit≥1000 or 0 |
| `--prop auto\|sgp4\|approx` | auto | Propagator |
| `--grid DEG` | 5 | Cell size degrees |
| `--minutes N` | 0 | Forward prop minutes |
| `--cache PATH` | `out/starlink_tle_cache.txt` | Per-fleet caches: `out/tle_*.txt` |
| `--no-heatmap` | off | Skip PNG |
| `--snapshot-save [id]` | — | Write `out/snapshots/` (+ solar meta on save) |
| `--snapshot-load id` | — | Load instead of TLE build |
| `--snapshot-list` | — | List snapshots and exit |
| `--rpc-health` / `--rpc-push` / `--rpc-pull` | — | Optional Cynober DB bridge (**cynober-db ≥ 8.2.5**) |

### Studio-only

| Flag | Default |
|------|---------|
| `--host` | `127.0.0.1` |
| `--port` | `8765` |
| `--open-browser` | off |
| `--studio-mode 2d\|3d` | `2d` |
| `--live-feed` | off |
| `--interval SEC` | 900 |

### Reach (env — W1)

| Env | Default | Notes |
|-----|---------|--------|
| `CYNOBER_REACH` | `1` | `0` = product as before (no session root) |
| `CYNOBER_REACH_MODE` | `session` | `off` \| `session` \| `ghost` \| `impact` |

Studio UI load limit: **40 … 50 000** (SLA usable) + presets 400 / 2k / 10k / 50k.  
Export: `GET /api/export?format=json|md`. Ghost: `GET /api/ghost`.  
Live root: `GET/POST /api/attention` (`live` / `commit` / `restore`) — session-only GC; Impact reads `cell.depends_on`.

See [`REACH_STUDIO.md`](REACH_STUDIO.md).

### Solar net flags (weather · predict · hazard · report)

| Flag | Role |
|------|------|
| `--offline` | Cache/stub only |
| `--force` | Bypass weather cache TTL |

---

## Examples

```bat
:: map one-shot
python main.py --offline-demo --limit 40 --no-heatmap
python main.py --limit 12000 --hot-only --html

:: studio
python main.py studio --offline-demo --limit 40 --open-browser
python main.py studio --fleet oneweb --limit 200 --open-browser
python main.py studio --limit 12000 --open-browser

:: solar / geo
python main.py weather
python main.py weather --offline
python main.py predict --offline
python main.py hazard --offline-demo --limit 40 --offline --with-predict --no-heatmap
python main.py report --offline-demo --limit 40 --offline --json --md --save-snapshot
python main.py geo --offline-demo --limit 40 --no-heatmap

:: fleets + country (A)
python main.py fleets
python main.py --fleet iridium --limit 100 --offline-demo --no-heatmap
python main.py --fleet starlink,oneweb --limit 40 --offline-demo --no-heatmap
python main.py --fleet starlink --country US --limit 200 --offline-demo --no-heatmap

:: timeline (B)
python main.py timeline
python main.py timeline --compare snap_A snap_B

:: snapshots / RPC (optional; needs cynober-db>=8.2.5)
python main.py --offline-demo --limit 40 --snapshot-save
python main.py --snapshot-list
set CYNOBER_USER=admin
set CYNOBER_TOKEN=…
python main.py --rpc-health
```

RPC env: `CYNOBER_HOST` / `PORT` / `PROFILE` / `WORLD` / `USER` / `TOKEN` · `CYNOBER_RPC=0` off.  
See [README.md](../README.md#optional-cynober-db-rpc).

---

## Related docs

- [USER_GUIDE.en.md](USER_GUIDE.en.md) — user guide (EN)  
- [USER_GUIDE.md](USER_GUIDE.md) — instrukcja obsługi (PL)  
- [HAZARD_LAYER.md](HAZARD_LAYER.md) — H0–H8 solar + geo + UX  
- [STARLINK_ATOMS.md](STARLINK_ATOMS.md) — engine contract  
- [SLA_50K.md](SLA_50K.md) — scale budgets  
- [PROJECT_STATUS.md](PROJECT_STATUS.md) — COMPLETE (2026-08-14)  
- [README.md](../README.md) — product overview + HTTP API  

