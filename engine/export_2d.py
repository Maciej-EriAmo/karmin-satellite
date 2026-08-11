"""2D export: heatmap PNG, report payload, standalone HTML."""
from __future__ import annotations

import base64
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from engine.grid import density_to_T, t_to_rgb
from engine.map import StarlinkAtomMap

def render_heatmap_png(
    amap: StarlinkAtomMap,
    path: Path,
    *,
    width: int = 720,
    height: int = 360,
) -> Path:
    try:
        from PIL import Image
    except ImportError as e:
        raise SystemExit("Pillow wymagany: pip install pillow") from e

    deg = amap.grid_deg
    nlat = int(math.ceil(180.0 / deg))
    nlon = int(math.ceil(360.0 / deg))
    grid = Image.new("RGB", (nlon, nlat), (8, 12, 28))
    px = grid.load()
    # z density array (działa też przy hot-only)
    max_c = max(amap.density.values()) if amap.density else 1
    if amap.density:
        for (ilat, ilon), c in amap.density.items():
            if 0 <= ilat < nlat and 0 <= ilon < nlon:
                y = nlat - 1 - ilat
                px[ilon, y] = t_to_rgb(density_to_T(c, max_count=max_c))
    else:
        for a in amap.iter_cells():
            v = a.metadata.get("v") or {}
            ilat, ilon = int(v.get("ilat", 0)), int(v.get("ilon", 0))
            if 0 <= ilat < nlat and 0 <= ilon < nlon:
                y = nlat - 1 - ilat
                px[ilon, y] = t_to_rgb(float(a.T))
    out = grid.resize((width, height), Image.Resampling.NEAREST)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, format="PNG")
    return path


def export_report_payload(
    amap: StarlinkAtomMap,
    *,
    src: str = "",
    using: int = 0,
    elapsed_s: float = 0.0,
    heatmap_path: Optional[Path] = None,
    top_n: int = 40,
) -> dict:
    """JSON pod stronę HTML / API (bez binarnych blobów poza opcjonalnym b64)."""
    summ = amap.summary()
    deg = amap.grid_deg
    nlat = int(math.ceil(180.0 / deg))
    nlon = int(math.ceil(360.0 / deg))
    dens = [
        {"ilat": ilat, "ilon": ilon, "count": int(c)}
        for (ilat, ilon), c in sorted(amap.density.items(), key=lambda x: -x[1])
    ]
    cells = list(amap.iter_cells())
    cells.sort(key=lambda a: float(a.T), reverse=True)
    top = []
    for a in cells[:top_n]:
        v = a.metadata.get("v") or {}
        top.append(
            {
                "id": str(a.id),
                "T": round(float(a.T), 2),
                "state": str(a.state),
                "E": str(a.E),
                "count": v.get("count"),
                "lat0": v.get("lat0"),
                "lon0": v.get("lon0"),
            }
        )
    heat_b64 = None
    heat_name = None
    if heatmap_path and Path(heatmap_path).is_file():
        heat_name = Path(heatmap_path).name
        heat_b64 = base64.b64encode(Path(heatmap_path).read_bytes()).decode("ascii")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tle_source": src,
        "using": using,
        "elapsed_s": round(elapsed_s, 3),
        "grid_deg": deg,
        "nlat": nlat,
        "nlon": nlon,
        "version": getattr(amap, "version", 0),
        "summary": summ,
        "shells": summ.get("shells") or {},
        "density": dens,
        "top_cells": top,
        "heatmap_file": heat_name,
        "heatmap_png_b64": heat_b64,
        "law": "temperatura mowi KIEDY, osiagalnosc mowi CZY",
        "project": "Cynober Studio · Starlink atoms · bubbles",
    }


def write_html_report(payload: dict, path: Path) -> Path:
    """Samowystarczalna strona HTML (file://) — canvas + przyciski wizualizacji."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # osobny JSON obok HTML (łatwy podgląd / fetch przy serwerze)
    json_path = path.with_suffix(".json")
    slim = dict(payload)
    # w pliku JSON nie dubluj mega b64 jeśli HTML go embeduje — zostaw referencję
    slim_for_file = {k: v for k, v in slim.items() if k != "heatmap_png_b64"}
    if payload.get("heatmap_file"):
        slim_for_file["heatmap_file"] = payload["heatmap_file"]
    json_path.write_text(
        json.dumps(slim_for_file, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    data_js = json.dumps(payload, ensure_ascii=False)
    # escape </script> in JSON
    data_js = data_js.replace("</", "<\\/")

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Cynober Studio · Starlink atoms</title>
<style>
  :root {{
    --bg: #0c0a0f;
    --panel: #16121c;
    --ink: #f2e8e8;
    --muted: #9a8a92;
    --crimson: #b01030;
    --hot: #ff3b1f;
    --warm: #f0a030;
    --cold: #3a6a9a;
    --line: #2a2230;
    --ok: #3dba7a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 20% -10%, #2a1020 0%, var(--bg) 55%);
    color: var(--ink); min-height: 100vh;
  }}
  header {{
    padding: 1.1rem 1.4rem; border-bottom: 1px solid var(--line);
    display: flex; flex-wrap: wrap; gap: .8rem; align-items: baseline;
    justify-content: space-between;
  }}
  header h1 {{ margin: 0; font-size: 1.25rem; letter-spacing: .02em; }}
  header h1 span {{ color: var(--crimson); }}
  header .sub {{ color: var(--muted); font-size: .85rem; }}
  main {{
    display: grid;
    grid-template-columns: minmax(260px, 320px) 1fr;
    gap: 1rem; padding: 1rem; max-width: 1400px; margin: 0 auto;
  }}
  @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} }}
  .panel {{
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; padding: 1rem;
  }}
  .panel h2 {{
    margin: 0 0 .75rem; font-size: .78rem; text-transform: uppercase;
    letter-spacing: .12em; color: var(--muted);
  }}
  .stat {{
    display: flex; justify-content: space-between; padding: .35rem 0;
    border-bottom: 1px solid #221c28; font-size: .92rem;
  }}
  .stat b {{ color: var(--warm); font-variant-numeric: tabular-nums; }}
  .shell-bar {{
    display: grid; grid-template-columns: 72px 1fr 40px; gap: .4rem;
    align-items: center; margin: .35rem 0; font-size: .82rem;
  }}
  .shell-bar .track {{
    height: 8px; background: #221820; border-radius: 4px; overflow: hidden;
  }}
  .shell-bar .fill {{ height: 100%; background: linear-gradient(90deg, var(--crimson), var(--hot)); }}
  .btns {{ display: flex; flex-wrap: wrap; gap: .45rem; margin: .5rem 0 1rem; }}
  button {{
    appearance: none; border: 1px solid var(--line); background: #1e1824;
    color: var(--ink); border-radius: 8px; padding: .45rem .7rem;
    font-size: .82rem; cursor: pointer;
  }}
  button:hover {{ border-color: var(--crimson); }}
  button.active {{
    background: linear-gradient(180deg, #3a1520, #241018);
    border-color: var(--crimson); color: #ffd0d0;
  }}
  label.chk {{ font-size: .82rem; color: var(--muted); display: flex; gap: .35rem; align-items: center; }}
  .viz-wrap {{
    position: relative; background: #08060a; border-radius: 10px;
    border: 1px solid var(--line); overflow: hidden;
  }}
  canvas, .heat-img {{
    display: block; width: 100%; height: auto; image-rendering: pixelated;
  }}
  .heat-img {{ display: none; }}
  .heat-img.show {{ display: block; }}
  canvas.hide {{ display: none; }}
  table {{
    width: 100%; border-collapse: collapse; font-size: .8rem; margin-top: .5rem;
  }}
  th, td {{ text-align: left; padding: .35rem .4rem; border-bottom: 1px solid var(--line); }}
  th {{ color: var(--muted); font-weight: 600; }}
  tr:hover td {{ background: #1c1620; }}
  .pill {{
    display: inline-block; padding: .1rem .4rem; border-radius: 999px;
    font-size: .72rem; background: #2a1820; color: var(--hot);
  }}
  .pill.warm {{ color: var(--warm); background: #2a2418; }}
  footer {{
    max-width: 1400px; margin: 0 auto; padding: 0 1rem 1.5rem;
    color: var(--muted); font-size: .78rem;
  }}
  #status {{ min-height: 1.2em; color: var(--ok); font-size: .82rem; margin-top: .4rem; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>Cynober · <span>Studio</span> · Starlink</h1>
    <div class="sub">multi-task: Store · bubbles · T-heatmap · SGP4 · HTML view</div>
  </div>
  <div class="sub" id="genAt"></div>
</header>
<main>
  <aside class="panel">
    <h2>Wyniki</h2>
    <div id="stats"></div>
    <h2 style="margin-top:1.2rem">Bąble shell</h2>
    <div id="shells"></div>
    <h2 style="margin-top:1.2rem">Wizualizacja</h2>
    <div class="btns" id="modeBtns">
      <button type="button" data-mode="canvas" class="active">Canvas density</button>
      <button type="button" data-mode="png">PNG heatmap</button>
      <button type="button" data-mode="both">Oba</button>
    </div>
    <div class="btns" id="palBtns">
      <button type="button" data-pal="thermal" class="active">Thermal</button>
      <button type="button" data-pal="crimson">Crimson</button>
      <button type="button" data-pal="mono">Mono</button>
    </div>
    <div class="btns">
      <button type="button" id="btnHot">Tylko HOT bins</button>
      <button type="button" id="btnAll">Wszystkie biny</button>
      <button type="button" id="btnGrid">Siatka on/off</button>
      <button type="button" id="btnLabels">Etykiety max</button>
    </div>
    <label class="chk"><input type="range" id="minCount" min="1" max="20" value="1"/> min count: <span id="minCountVal">1</span></label>
    <div id="status"></div>
    <h2 style="margin-top:1.2rem">Top komórki</h2>
    <div style="overflow:auto; max-height: 320px;">
      <table>
        <thead><tr><th>id</th><th>T</th><th>n</th><th>E</th></tr></thead>
        <tbody id="topBody"></tbody>
      </table>
    </div>
  </aside>
  <section class="panel">
    <h2>Mapa</h2>
    <div class="viz-wrap">
      <img id="heatPng" class="heat-img" alt="heatmap PNG"/>
      <canvas id="cv" width="720" height="360"></canvas>
    </div>
    <p class="sub" style="margin:.6rem 0 0">
      Atomy <code>starlink:cell</code> · T = gęstość · bąble <code>shell:*</code> ·
      law: temperature says WHEN, reachability says WHETHER.
    </p>
  </section>
</main>
<footer>
  Cynober Studio · public TLE (Celestrak). Generated by
  <code>python main.py --html</code>. JSON: <span id="jsonName"></span>
</footer>
<script id="payload" type="application/json">{data_js}</script>
<script>
(function() {{
  const DATA = JSON.parse(document.getElementById('payload').textContent);
  const S = DATA.summary || {{}};
  const cv = document.getElementById('cv');
  const ctx = cv.getContext('2d');
  const img = document.getElementById('heatPng');
  let palette = 'thermal';
  let mode = 'canvas';
  let onlyHot = false;
  let showGrid = false;
  let showLabels = true;
  let minCount = 1;

  document.getElementById('genAt').textContent = (DATA.generated_at || '') +
    (DATA.tle_source ? ' · ' + DATA.tle_source : '');
  document.getElementById('jsonName').textContent = (location.pathname.replace(/\\.html?$/i, '.json').split('/').pop()) || 'starlink_report.json';

  function el(tag, html) {{
    const n = document.createElement(tag);
    if (html != null) n.innerHTML = html;
    return n;
  }}

  function fillStats() {{
    const box = document.getElementById('stats');
    const rows = [
      ['Satelity', S.sats],
      ['Komórki (atomy)', S.cells],
      ['HOT cells', S.hot_cells],
      ['WARM cells', S.warm_cells],
      ['Prop', S.prop + (S.sgp4 ? ' (sgp4 OK)' : '')],
      ['hot_only', S.hot_only ? 'tak' : 'nie'],
      ['prop_ms', (S.prop_ms != null ? S.prop_ms.toFixed(1) : '?')],
      ['using TLE', DATA.using],
      ['grid', DATA.grid_deg + '°'],
      ['elapsed', DATA.elapsed_s + 's'],
    ];
    box.innerHTML = '';
    rows.forEach(([k,v]) => {{
      const d = el('div', '<span>'+k+'</span><b>'+v+'</b>');
      d.className = 'stat';
      box.appendChild(d);
    }});
    if (S.max_cell) {{
      const d = el('div', '<span>max_cell</span><b>'+S.max_cell.id+' · T='+S.max_cell.T+' · n='+S.max_cell.count+'</b>');
      d.className = 'stat';
      box.appendChild(d);
    }}
  }}

  function fillShells() {{
    const shells = DATA.shells || {{}};
    const box = document.getElementById('shells');
    box.innerHTML = '';
    const vals = Object.values(shells);
    const max = Math.max(1, ...vals);
    Object.keys(shells).sort().forEach(k => {{
      const n = shells[k];
      const row = el('div');
      row.className = 'shell-bar';
      row.innerHTML = '<span>'+k.replace('shell:','')+'°</span><div class="track"><div class="fill" style="width:'+(100*n/max)+'%"></div></div><span>'+n+'</span>';
      box.appendChild(row);
    }});
    if (!vals.length) box.textContent = '(brak)';
  }}

  function fillTop() {{
    const tb = document.getElementById('topBody');
    tb.innerHTML = '';
    (DATA.top_cells || []).forEach(c => {{
      const tr = document.createElement('tr');
      const pill = c.T >= 70 ? 'pill' : 'pill warm';
      tr.innerHTML = '<td>'+c.id+'</td><td><span class="'+pill+'">'+c.T+'</span></td><td>'+(c.count??'')+'</td><td>'+c.E+'</td>';
      tb.appendChild(tr);
    }});
  }}

  function colorThermal(t01) {{
    if (t01 < 0.33) {{
      const k = t01/0.33;
      return [0, 40+80*k, 80+175*k];
    }}
    if (t01 < 0.66) {{
      const k = (t01-0.33)/0.33;
      return [255*k, 200+55*k, 255*(1-k)];
    }}
    const k = (t01-0.66)/0.34;
    return [255, 255*(1-k), 0];
  }}
  function colorCrimson(t01) {{
    return [40+200*t01, 8+30*t01, 20+40*(1-t01)];
  }}
  function colorMono(t01) {{
    const v = 20 + 220*t01;
    return [v, v*0.85, v*0.9];
  }}
  function pickColor(t01) {{
    if (palette === 'crimson') return colorCrimson(t01);
    if (palette === 'mono') return colorMono(t01);
    return colorThermal(t01);
  }}

  function maxCount() {{
    let m = 1;
    (DATA.density || []).forEach(d => {{ if (d.count > m) m = d.count; }});
    return m;
  }}

  function densityToT01(count, maxC) {{
    if (count <= 0) return 0;
    return Math.log(1+count) / Math.log(1+maxC);
  }}

  function draw() {{
    const nlat = DATA.nlat || 36, nlon = DATA.nlon || 72;
    const W = cv.width, H = cv.height;
    ctx.fillStyle = '#08060a';
    ctx.fillRect(0,0,W,H);
    const cw = W / nlon, ch = H / nlat;
    const maxC = maxCount();
    const hotThresh = 0.7; // ~ T_HOT scale on log density
    let drawn = 0;
    (DATA.density || []).forEach(d => {{
      if (d.count < minCount) return;
      const t01 = densityToT01(d.count, maxC);
      if (onlyHot && t01 < hotThresh) return;
      const [r,g,b] = pickColor(t01);
      ctx.fillStyle = 'rgb('+r+','+g+','+b+')';
      const x = d.ilon * cw;
      const y = (nlat - 1 - d.ilat) * ch;
      ctx.fillRect(x, y, Math.ceil(cw)+0.5, Math.ceil(ch)+0.5);
      drawn++;
    }});
    if (showGrid) {{
      ctx.strokeStyle = 'rgba(255,255,255,0.08)';
      ctx.lineWidth = 1;
      for (let i=0;i<=nlon;i++) {{
        ctx.beginPath(); ctx.moveTo(i*cw,0); ctx.lineTo(i*cw,H); ctx.stroke();
      }}
      for (let j=0;j<=nlat;j++) {{
        ctx.beginPath(); ctx.moveTo(0,j*ch); ctx.lineTo(W,j*ch); ctx.stroke();
      }}
    }}
    if (showLabels && DATA.top_cells && DATA.top_cells[0]) {{
      const c = DATA.top_cells[0];
      // rough place from E "lat,lon"
      const parts = String(c.E||'').split(',');
      if (parts.length >= 2) {{
        const lat = parseFloat(parts[0]), lon = parseFloat(parts[1]);
        if (!isNaN(lat) && !isNaN(lon)) {{
          const x = ((lon + 180) / 360) * W;
          const y = ((90 - lat) / 180) * H;
          ctx.fillStyle = '#fff';
          ctx.font = '12px sans-serif';
          ctx.fillText('★ '+c.id+' n='+c.count, x+4, y-4);
          ctx.beginPath();
          ctx.arc(x,y,4,0,Math.PI*2);
          ctx.fillStyle = '#ff3b1f';
          ctx.fill();
        }}
      }}
    }}
    document.getElementById('status').textContent =
      'canvas bins=' + drawn + ' · palette=' + palette +
      (onlyHot ? ' · HOT filter' : '') + ' · minCount=' + minCount;
  }}

  function applyMode() {{
    const showCv = mode === 'canvas' || mode === 'both';
    const showPng = mode === 'png' || mode === 'both';
    cv.classList.toggle('hide', !showCv);
    img.classList.toggle('show', showPng && !!img.src);
    if (showCv) draw();
  }}

  // PNG
  if (DATA.heatmap_png_b64) {{
    img.src = 'data:image/png;base64,' + DATA.heatmap_png_b64;
  }} else if (DATA.heatmap_file) {{
    img.src = DATA.heatmap_file;
  }}

  document.getElementById('modeBtns').addEventListener('click', e => {{
    const b = e.target.closest('button[data-mode]');
    if (!b) return;
    mode = b.dataset.mode;
    [...document.getElementById('modeBtns').children].forEach(x => x.classList.toggle('active', x===b));
    applyMode();
  }});
  document.getElementById('palBtns').addEventListener('click', e => {{
    const b = e.target.closest('button[data-pal]');
    if (!b) return;
    palette = b.dataset.pal;
    [...document.getElementById('palBtns').children].forEach(x => x.classList.toggle('active', x===b));
    draw();
  }});
  document.getElementById('btnHot').onclick = () => {{ onlyHot = true; draw(); }};
  document.getElementById('btnAll').onclick = () => {{ onlyHot = false; draw(); }};
  document.getElementById('btnGrid').onclick = () => {{ showGrid = !showGrid; draw(); }};
  document.getElementById('btnLabels').onclick = () => {{ showLabels = !showLabels; draw(); }};
  const rng = document.getElementById('minCount');
  const maxC = maxCount();
  rng.max = Math.max(2, Math.min(50, maxC));
  rng.oninput = () => {{
    minCount = parseInt(rng.value, 10) || 1;
    document.getElementById('minCountVal').textContent = minCount;
    draw();
  }};

  fillStats();
  fillShells();
  fillTop();
  applyMode();
}})();
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path
