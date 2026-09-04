# Karmin Satellite — project status

**Status: COMPLETE** (2026-08-14) — product closed. No open tracks.

Research workbench for public satellite density + solar context on a thermal-atom substrate.

## Shipped

| Track | Deliverable |
|-------|-------------|
| MVP 0–5 | Engine, 2D/3D UI, live feeder, snapshots, library/analyze, SLA 50k |
| H0–H8 | Solar weather → hazard → predict → report → geo → 3D radiation → adaptive UX |
| H7 | Multi-fleet Celestrak catalogs |
| **A** | SATCAT / country filter (`engine/satcat.py`, `--country`, UI) |
| **B** | Snapshot timeline + density compare (`engine/analytics.py`, `/api/timeline`) |
| **C** | EN UI strings, version ETag poll (304), structured logging |
| **D** | Close-out — no mandatory backlog |
| **Reach F0+W1–W5** | Session root · ghost · impact · resonance · system tick · [`REACH_STUDIO.md`](REACH_STUDIO.md) |
| **Live root** | Session-only Store root · vacuum vs ghost · Impact reads `cell.depends_on` |
| **Debris** | `Load debris` · `--fleet debris` · 5 public Celestrak event clouds |

## Intentionally out of scope

- Operational SSA / mission certification  
- Edit-atoms, agent sat evolution  
- Native Rust slab in Studio path  
- Space-Track authenticated feeds  

## Optional later (only if needed)

- Deeper charts / batch multi-state analytics  
- More SATCAT fields (owner, launch site)  
- Long soak ops tests  

## How to run

```bat
python main.py studio --offline-demo --limit 40 --open-browser
python main.py fleets
python main.py timeline
python main.py --fleet starlink --country US --limit 200
```

Docs: [CLI.md](CLI.md) · [HAZARD_LAYER.md](HAZARD_LAYER.md) · [README.md](../README.md)

**MIT** — [Maciej-EriAmo/karmin-satellite](https://github.com/Maciej-EriAmo/karmin-satellite)  
