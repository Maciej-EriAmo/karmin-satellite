/* Karmin Satellite — 2D density canvas + filters */
(() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    version: 0,
    full: null, // last /api/data
    view: null, // density currently drawn (full or filtered)
    shell: "all",
    minCount: 1,
    pollMs: 5000,
    layer: "density", // density | hazard | blend | ghost
    hazard: null,
    nlat: 36,
    nlon: 72,
    nSats: 0, // for H8 adaptive pixels
    cellPx: 8,
    fleet: "starlink",
    country: "",
    loadLimit: 400, // UI slider; 0 = full catalog
    versionEtag: null,
    reachView: false,
    reachEnabled: true,
    ghost: null,
    ghostUnder: true,
    sotCells: 0,
    impactHighlight: null,
    lastImpact: null,
    resoHighlight: null,
    lastTick: null,
    liveRoot: false,
    attention: null,
    deltaMode: false,
    delta: null, // last /api/delta payload
    deltaPoll: null,
  };

  function readLoadLimit() {
    const full = $("load-limit-full");
    if (full && full.checked) return 0;
    const r = $("load-limit");
    if (!r) return state.loadLimit || 400;
    const v = parseInt(r.value, 10);
    return Number.isFinite(v) ? v : 400;
  }

  function syncLoadLimitUI(limit) {
    const lim = limit == null ? state.loadLimit : Number(limit);
    state.loadLimit = lim;
    const full = $("load-limit-full");
    const r = $("load-limit");
    const lab = $("load-limit-val");
    if (full) full.checked = lim === 0;
    if (r) {
      r.disabled = lim === 0;
      if (lim > 0) {
        const lo = parseInt(r.min, 10) || 40;
        const hi = parseInt(r.max, 10) || 50000;
        r.value = String(Math.max(lo, Math.min(hi, lim)));
      }
    }
    if (lab) {
      lab.textContent = lim === 0 ? "full (0)" : String(lim > 0 ? lim : r?.value || 400);
    }
    const num = $("load-limit-num");
    if (num) {
      num.disabled = lim === 0;
      if (lim > 0) num.value = String(lim);
    }
    document.querySelectorAll("#limit-presets [data-limit]").forEach((btn) => {
      const v = parseInt(btn.getAttribute("data-limit"), 10);
      btn.classList.toggle("active", lim > 0 && v === lim);
    });
  }
  // shared with globe.js for shell/min_count + layer handoff
  window.CynoberStudioState = state;

  /**
   * H8: CSS pixels per cell.
   * - few sats → coarser integer blocks (readable demo / shell filter)
   * - many sats → fill panel width (cell = availW/nlon), sharp density field
   * Never: tiny buffer stretched to 100% (blur) or forced 18px on 12k.
   */
  function adaptiveCellPx({ nSats, nHotCells, nlon, availW }) {
    const n = Math.max(1, Number(nSats) || Number(nHotCells) || 1);
    const cols = Math.max(1, Number(nlon) || 72);
    const fit = Math.max(1, (Number(availW) || 960) / cols); // float OK

    // large catalog: one cell spans the panel evenly (sharp, no upscale blur)
    if (n >= 2000) return fit;
    if (n >= 800) return Math.min(3, fit);
    if (n >= 200) return Math.min(5, fit);
    if (n >= 80) return Math.min(7, fit);
    // demo / tight filter
    return Math.min(10, fit);
  }

  function tToRgb(T, T_MAX = 100) {
    const x = Math.max(0, Math.min(1, T / T_MAX));
    if (x < 0.33) {
      const k = x / 0.33;
      return [0, Math.floor(40 + 80 * k), Math.floor(80 + 175 * k)];
    }
    if (x < 0.66) {
      const k = (x - 0.33) / 0.33;
      return [Math.floor(255 * k), Math.floor(200 + 55 * k), Math.floor(255 * (1 - k))];
    }
    const k = (x - 0.66) / 0.34;
    return [255, Math.floor(255 * (1 - k)), 0];
  }

  function densityToT(count, maxCount) {
    const T_WARM = 40;
    const T_MAX = 100;
    const cold = 8;
    if (count <= 0) return cold;
    const mc = maxCount <= 0 ? 1 : maxCount;
    const t =
      T_WARM +
      (T_MAX - T_WARM) * (Math.log1p(count) / Math.log1p(mc));
    return Math.max(cold, Math.min(T_MAX, t));
  }

  function setText(id, v) {
    const el = $(id);
    if (el) el.textContent = v == null ? "—" : String(v);
  }

  function updateStats(summary, meta) {
    if (!summary) return;
    if (summary.sats != null) state.nSats = Number(summary.sats) || 0;
    setText("stat-sats", summary.sats);
    setText("stat-cells", summary.cells);
    setText("stat-hot", summary.hot_cells);
    setText("stat-prop", summary.prop_ms != null ? summary.prop_ms.toFixed(1) : "—");
    setText("stat-version", summary.version ?? state.version);
    setText("stat-errors", summary.prop_errors ?? 0);
    setText("stat-src", meta?.tle_source || "—");
    setText("stat-using", meta?.using ?? "—");
    const feeder = meta?.feeder;
    if (feeder && feeder.running) {
      $("badge-status").textContent = "feeder";
      $("badge-status").classList.add("ok");
      setText(
        "stat-feeder",
        `on · ${feeder.stats?.successes ?? 0} ok · every ${feeder.interval_sec}s`
      );
    } else {
      setText("stat-feeder", feeder ? "stopped" : "off");
    }
    const shells = summary.shells || {};
    const box = $("shell-list");
    if (box) {
      box.innerHTML = "";
      const entries = Object.entries(shells).sort((a, b) => b[1] - a[1]);
      const max = entries.reduce((m, [, n]) => Math.max(m, n), 1);
      for (const [name, n] of entries) {
        const row = document.createElement("div");
        row.className = "stat";
        row.innerHTML = `<span>${name}</span><b>${n}</b>`;
        box.appendChild(row);
      }
      // shell radios
      const radioBox = $("shell-radios");
      if (radioBox) {
        const current = state.shell;
        radioBox.innerHTML = "";
        const allLab = document.createElement("label");
        allLab.className = "row";
        allLab.innerHTML = `<input type="radio" name="shell" value="all" ${
          current === "all" ? "checked" : ""
        }/> All`;
        radioBox.appendChild(allLab);
        for (const [name] of entries) {
          const val = name.replace(/^shell:/, "");
          const lab = document.createElement("label");
          lab.className = "row";
          lab.innerHTML = `<input type="radio" name="shell" value="${val}" ${
            current === val || current === name ? "checked" : ""
          }/> ${name}`;
          radioBox.appendChild(lab);
        }
        radioBox.querySelectorAll('input[name="shell"]').forEach((input) => {
          input.addEventListener("change", () => {
            if (input.checked) {
              state.shell = input.value;
              applyFilter();
            }
          });
        });
      }
    }
    $("badge-status").textContent = "live";
    $("badge-status").classList.add("ok");
  }

  /** Purple→magenta→red ramp for solar exposure proxy (distinct from density T). */
  function ghostToRgb(kind) {
    if (kind === "retained") return [150, 80, 220];
    return [70, 50, 110];
  }

  function hazardToRgb(exposure, maxExp) {
    const mc = maxExp > 0 ? maxExp : 100;
    const x = Math.max(0, Math.min(1, (exposure || 0) / mc));
    if (x < 0.4) {
      const k = x / 0.4;
      return [
        Math.floor(20 + 80 * k),
        Math.floor(10 + 20 * k),
        Math.floor(60 + 100 * k),
      ];
    }
    if (x < 0.75) {
      const k = (x - 0.4) / 0.35;
      return [
        Math.floor(100 + 120 * k),
        Math.floor(30 + 40 * k),
        Math.floor(160 + 40 * k),
      ];
    }
    const k = (x - 0.75) / 0.25;
    return [Math.floor(220 + 35 * k), Math.floor(40 * (1 - k)), Math.floor(80 * (1 - k))];
  }

  function baseScoreFromHazard() {
    const h = state.hazard;
    if (!h) return 20;
    const shell = state.shell || "all";
    if (shell !== "all" && h.groups) {
      const sk = String(shell).startsWith("shell:") ? shell : `shell:${shell}`;
      const g = h.groups.find((x) => x.kind === "shell" && x.group_id === sk);
      if (g) return Number(g.score) || h.global_score || 20;
    }
    return Number(h.global_score) || 20;
  }

  function exposureForCell(count, maxC, baseScore) {
    const mc = maxC <= 0 ? 1 : maxC;
    const c = count || 0;
    const weight = 0.3 + 0.7 * (Math.log1p(c) / Math.log1p(mc));
    return Math.max(0, Math.min(100, baseScore * weight));
  }

  function redrawMap() {
    const density = state.view || [];
    const nlat = state.nlat || 36;
    const nlon = state.nlon || 72;
    drawMap(density, nlat, nlon, state.layer || "density");
  }

  function setLayer(layer) {
    state.layer = layer;
    ["density", "hazard", "blend", "ghost"].forEach((L) => {
      const btn = $(`btn-layer-${L}`);
      if (btn) btn.classList.toggle("primary", L === layer);
    });
    const titles = {
      density: "density",
      hazard: "solar exposure (proxy)",
      blend: "density + hazard blend",
      ghost: "ghost · retained / cold",
    };
    setText("map2d-title", titles[layer] || layer);
    setText(
      "layer-info",
      layer === "density"
        ? "density · solar overlay off"
        : layer === "hazard"
          ? "hazard · density off (research proxy)"
          : layer === "ghost"
            ? "ghost · retained TOMB + cold in session reach"
            : "blend · density hue + exposure weight"
    );
    redrawMap();
  }

  function drawMap(density, nlat, nlon, layer) {
    const canvas = $("heatmap");
    if (!canvas) return;
    const dens = density || [];
    const nHot = dens.length;
    // nSats: filter sum of counts when filtered, else summary sats
    let nSats = state.nSats || 0;
    if (state.shell !== "all" || state.minCount > 1) {
      nSats = dens.reduce((s, d) => s + (d.count || 0), 0) || nHot;
    }

    const wrap = $("map-wrap");
    const availW = Math.max(
      320,
      (wrap && wrap.clientWidth) || canvas.parentElement?.clientWidth || 960
    );
    const cellPx = adaptiveCellPx({
      nSats: nSats || nHot,
      nHotCells: nHot,
      nlon,
      availW,
    });
    state.cellPx = cellPx;

    // Exact CSS size = grid × cellPx (1:1). DPR buffer for retina sharpness.
    const cssW = Math.max(1, nlon * cellPx);
    const cssH = Math.max(1, nlat * cellPx);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.style.width = `${cssW}px`;
    canvas.style.maxWidth = "100%";
    canvas.style.height = "auto";
    canvas.style.aspectRatio = `${nlon} / ${nlat}`;
    canvas.width = Math.max(1, Math.round(cssW * dpr));
    canvas.height = Math.max(1, Math.round(cssH * dpr));
    // integer blocks when coarse; auto when filling panel (subpixel cells)
    canvas.style.imageRendering = cellPx >= 3 ? "pixelated" : "auto";

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = cellPx < 2;
    ctx.fillStyle = "#08060a";
    ctx.fillRect(0, 0, cssW, cssH);

    const ghosts = (state.ghost && state.ghost.cells) || [];
    const ghostAt = new Map();
    ghosts.forEach((g) => ghostAt.set(`${g.ilat}:${g.ilon}`, g));
    const drawGhostUnder =
      state.ghostUnder && state.layer !== "ghost" && ghosts.length > 0;

    const maxC = dens.reduce((m, d) => Math.max(m, d.count || 0), 1);
    const base = baseScoreFromHazard();
    const exposures = dens.map((d) =>
      exposureForCell(d.count || 0, maxC, base)
    );
    const maxExp = Math.max(base, ...exposures, 1);
    const cw = cellPx;
    const ch = cellPx;
    const mode = layer || "density";
    const gap = cellPx >= 5 ? 1 : 0;

    const paintGhost = (g, alpha) => {
      const [r, gv, b] = ghostToRgb(g.kind);
      ctx.fillStyle = `rgba(${r},${gv},${b},${alpha})`;
      const x = g.ilon * cellPx;
      const y = (nlat - 1 - g.ilat) * cellPx;
      ctx.fillRect(x, y, Math.max(1, cellPx - gap), Math.max(1, cellPx - gap));
    };

    if (mode === "ghost") {
      ghosts.forEach((g) => paintGhost(g, g.kind === "retained" ? 0.92 : 0.55));
    } else if (drawGhostUnder) {
      ghosts.forEach((g) => paintGhost(g, g.kind === "retained" ? 0.55 : 0.28));
    }

    if (mode !== "ghost") {
    for (let i = 0; i < dens.length; i++) {
      const d = dens[i];
      const exp = exposures[i];
      let r, g, b;
      if (mode === "hazard") {
        [r, g, b] = hazardToRgb(exp, maxExp);
      } else if (mode === "blend") {
        const T = densityToT(d.count || 0, maxC);
        const [dr, dg, db] = tToRgb(T);
        const [hr, hg, hb] = hazardToRgb(exp, maxExp);
        const a = Math.max(0.25, Math.min(0.75, exp / maxExp));
        r = Math.floor(dr * (1 - a) + hr * a);
        g = Math.floor(dg * (1 - a) + hg * a);
        b = Math.floor(db * (1 - a) + hb * a);
      } else {
        const T = densityToT(d.count || 0, maxC);
        [r, g, b] = tToRgb(T);
      }
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      const x = d.ilon * cw;
      const y = (nlat - 1 - d.ilat) * ch;
      const rw = Math.max(1, cw - gap);
      const rh = Math.max(1, ch - gap);
      ctx.fillRect(x, y, rw, rh);
    }
    }

    const flashes = [state.impactHighlight, state.resoHighlight].filter(Boolean);
    flashes.forEach((flash) => {
      if (!flash || flash.until <= Date.now() || !flash.cells || !flash.cells.length) {
        return;
      }
      flash.cells.forEach((c) => {
        const x = c.ilon * cw;
        const y = (nlat - 1 - c.ilat) * ch;
        let stroke;
        if (flash.kind === "reso") {
          stroke = "rgba(32,208,224,0.95)";
        } else {
          stroke = c.emptied
            ? "rgba(255,70,36,0.95)"
            : "rgba(255,196,64,0.9)";
        }
        ctx.strokeStyle = stroke;
        ctx.lineWidth = Math.max(1.5, cellPx * 0.2);
        ctx.strokeRect(
          x + 0.5,
          y + 0.5,
          Math.max(1, cw - gap - 1),
          Math.max(1, ch - gap - 1)
        );
      });
    });

    state._draw = {
      nlat,
      nlon,
      maxC,
      maxExp,
      base,
      density: dens,
      exposures,
      cw,
      ch,
      w: cssW,
      h: cssH,
      cssW,
      cssH,
      layer: mode,
      cellPx,
      nSats: nSats || nHot,
      ghostAt,
    };

    const pxInfo = $("map-px-info");
    if (pxInfo) {
      const pxLabel =
        cellPx >= 2 && cellPx === Math.floor(cellPx)
          ? `${cellPx}px`
          : `${cellPx.toFixed(1)}px`;
      pxInfo.textContent = `cell ${pxLabel} · n≈${nSats || nHot} · hot=${nHot}`;
    }
  }

  function percentile(sorted, p) {
    if (!sorted.length) return 0;
    const i = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
    return sorted[i];
  }

  function analyzeDensity(density) {
    const dens = density || [];
    const counts = dens.map((d) => d.count || 0).sort((a, b) => a - b);
    const sum = counts.reduce((a, b) => a + b, 0);
    const maxC = counts.length ? counts[counts.length - 1] : 0;
    let hot = null;
    for (const d of dens) {
      if ((d.count || 0) === maxC) {
        hot = d;
        break;
      }
    }
    const top = dens
      .slice()
      .sort((a, b) => (b.count || 0) - (a.count || 0))
      .slice(0, 8);
    setText("an-cells", dens.length);
    setText("an-sum", sum);
    setText("an-max", maxC);
    if (hot) {
      const degLat = 180 / Math.max(1, state.nlat || 36);
      const degLon = 360 / Math.max(1, state.nlon || 72);
      const lat0 = -90 + (hot.ilat || 0) * degLat;
      const lon0 = -180 + (hot.ilon || 0) * degLon;
      setText(
        "an-hotspot",
        `cell:${hot.ilat}:${hot.ilon} · ~${lat0.toFixed(0)}°,${lon0.toFixed(0)}°`
      );
    } else {
      setText("an-hotspot", "—");
    }
    setText(
      "an-pct",
      counts.length
        ? `${percentile(counts, 50)} / ${percentile(counts, 90)}`
        : "—"
    );
    const box = $("an-top");
    if (box) {
      box.innerHTML = top
        .map(
          (d) =>
            `<div><span>cell:${d.ilat}:${d.ilon}</span><b>${d.count}</b></div>`
        )
        .join("");
    }
  }

  function drawFromPayload(data) {
    const nlat = data.nlat || 36;
    const nlon = data.nlon || 72;
    const density = data.density || [];
    state.nlat = nlat;
    state.nlon = nlon;
    state.view = density;
    // stats first so adaptiveCellPx sees nSats
    updateStats(data.summary, data);
    if (data.using != null && !state.nSats) {
      state.nSats = Number(data.using) || 0;
    }
    drawMap(density, nlat, nlon, state.layer || "density");
    analyzeDensity(density);
  }

  async function fetchJSON(url, opts) {
    const resp = await fetch(url, opts);
    if (resp.status === 304) {
      return { status: "not_modified", _status: 304 };
    }
    const j = await resp.json();
    if (!resp.ok || j.status === "error") {
      throw new Error(j.message || resp.statusText);
    }
    const et = resp.headers.get("ETag");
    if (et) j._etag = et;
    return j;
  }

  function fillCountrySelect(countries, current) {
    const sel = $("country-select");
    if (!sel) return;
    const cur = (current || "").toUpperCase();
    const entries = Object.entries(countries || {}).sort((a, b) => b[1] - a[1]);
    sel.innerHTML = `<option value="">All countries</option>`;
    entries.forEach(([code, n]) => {
      if (!code || code === "?") return;
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = `${code} (${n})`;
      sel.appendChild(opt);
    });
    if (cur && ![...sel.options].some((o) => o.value === cur)) {
      const opt = document.createElement("option");
      opt.value = cur;
      opt.textContent = cur;
      sel.appendChild(opt);
    }
    if (cur) sel.value = cur;
  }

  function updateWowBar() {
    const liveBtn = $("btn-live-wow");
    if (liveBtn) liveBtn.classList.toggle("wow-on", !!state.liveRoot);
    const att = state.attention;
    if (att && att.line) {
      setText("wow-live", att.live ? att.line : "catalog root");
    } else {
      setText("wow-live", state.liveRoot ? "session-only GC" : "catalog root");
    }
    const on = !!state.reachView;
    const btn = $("btn-reach-wow");
    if (btn) {
      btn.classList.toggle("wow-on", on);
      btn.classList.toggle("primary", on);
      btn.textContent = on ? "Reach ON" : "Reach view";
    }
    const t = $("reach-toggle");
    if (t) t.checked = on;
    const r = (state.full && state.full.reach) || {};
    const g = state.ghost || {};
    const sot =
      state.sotCells ||
      (state.full && !state.reachView && state.full.density
        ? state.full.density.length
        : 0);
    if (on && r.n_sats != null) {
      setText("wow-reach", `${r.n_sats} sats · ${r.n_cells} cells`);
    } else if (on) {
      setText("wow-reach", "on");
    } else {
      setText("wow-reach", "off · full SoT");
    }
    if (g.n_cells != null) {
      setText(
        "wow-ghost",
        `${g.n_cells} cells · ${g.n_sats || 0} sat retained`
      );
      setText(
        "stat-ghost",
        `${g.n_cells} cells · ret ${g.n_retained || 0} · cold ${g.n_cold || 0}`
      );
    } else {
      setText("wow-ghost", "—");
      setText("stat-ghost", "—");
    }
    const imp = state.lastImpact;
    if (imp && imp.line) {
      setText("wow-impact", imp.line);
    } else {
      setText("wow-impact", "—");
    }
    if (state.lastTick && state.lastTick.n_fleets != null) {
      setText(
        "wow-tick",
        `${state.lastTick.n_fleets} fleets · ${
          (state.lastTick.decisions || []).length
        } dec`
      );
    }
    setText("wow-sot", sot ? `${sot} cells` : "—");
    const badgeG = $("badge-reach");
    if (badgeG && g.n_cells) badgeG.classList.add("ghost");
  }

  function updateReachStatus(data) {
    const on = !!state.reachView;
    const r = (data && data.reach) || {};
    const nSats = r.n_sats;
    const nCells = r.n_cells;
    const badge = $("badge-reach");
    if (badge) {
      badge.classList.toggle("reach", on);
      if (!state.reachEnabled) {
        badge.textContent = "reach off";
      } else if (on && nSats != null) {
        badge.textContent = `reach: ${nSats} sats · ${nCells} cells`;
      } else if (on) {
        badge.textContent = "reach on";
      } else {
        badge.textContent = "reach off";
      }
    }
    if (nSats != null) {
      setText("stat-reach", `${nSats} sats · ${nCells} cells`);
      setText(
        "reach-info",
        `reach: ${nSats} sats · ${nCells} cells`
      );
    } else if (!state.reachEnabled) {
      setText("stat-reach", "flag off");
      setText("reach-info", "off · product as before (CYNOBER_REACH=0)");
    } else if (on) {
      setText("stat-reach", "on");
      setText("reach-info", "on · session root");
    } else {
      setText("stat-reach", "off");
      setText("reach-info", "off · full density (SoT)");
    }
    updateWowBar();
  }

  async function loadGhost() {
    try {
      const j = await fetchJSON("/api/ghost");
      state.ghost = j.data || null;
      updateWowBar();
      if (state.view) redrawMap();
    } catch (e) {
      state.ghost = null;
    }
  }

  function exportFile(format) {
    const reach = state.reachView ? "1" : "0";
    const sats = $("export-sats")?.checked ? "1" : "0";
    const q = new URLSearchParams({
      format,
      reach,
      sats,
    });
    window.location.href = `/api/export?${q}`;
    setText("snap-info", `download ${format}…`);
  }

  function renderImpact(data) {
    state.lastImpact = data;
    const panel = $("impact-panel");
    if (panel) panel.hidden = false;
    setText("impact-line", data.line || "—");
    const rb = data.reach_before || {};
    const ra = data.reach_after || {};
    const haz = data.hazard_delta_estimate || {};
    const hs = (haz.shells || [])[0];
    const hazLine = hs
      ? `${hs.shell}  n ${hs.n_before}→${hs.n_after}  score ${hs.score_before}→${hs.score_after}`
      : "hazard  —";
    const log = [
      data.simulate ? "simulate · density SoT unchanged" : "APPLIED cool · density SoT unchanged",
      `scope  ${data.or_shell || data.or_fleet || "explicit sats"}`,
      `−${data.cool_n || 0} sat  ·  ${data.n_affected || 0} cells hit  ·  ${data.n_emptied || 0} emptied`,
      `reach  ${rb.n_sats ?? "—"} → ${ra.n_sats ?? "—"} sats`,
      hazLine,
    ].join("\n");
    const pre = $("impact-log");
    if (pre) pre.textContent = log;
    updateWowBar();
    const btn = $("btn-impact-wow");
    if (btn) {
      btn.classList.add("wow-on");
      setTimeout(() => btn.classList.remove("wow-on"), 5000);
    }
  }

  function flashImpact(data) {
    const cells = data.affected_cells || [];
    state.impactHighlight = {
      kind: "impact",
      until: Date.now() + 5000,
      cells,
    };
    redrawMap();
    clearTimeout(state._impactTimer);
    state._impactTimer = setTimeout(() => {
      state.impactHighlight = null;
      redrawMap();
    }, 5100);
  }

  function flashResonance(data) {
    const cells = data.cells || [];
    state.resoHighlight = {
      kind: "reso",
      until: Date.now() + 5000,
      cells,
    };
    redrawMap();
    clearTimeout(state._resoTimer);
    state._resoTimer = setTimeout(() => {
      state.resoHighlight = null;
      redrawMap();
    }, 5100);
  }

  function renderDecisions(data) {
    state.lastTick = data;
    const panel = $("decisions-panel");
    if (panel) panel.hidden = false;
    const log = data.log || data.decisions || [];
    const lines = log.slice(-10).map((d) => {
      const act = (d.action || "?").padEnd(9, " ");
      return `${act} ${d.node || "?"}  ·  ${d.reason || ""}`;
    });
    const pre = $("decisions-log");
    if (pre) {
      const head = `settled ${data.ticked ?? 0} tick(s) · advisory log · density SoT`;
      pre.textContent = [head, ...lines].join("\n") || "no decisions";
    }
    updateWowBar();
    const btn = $("btn-tick-wow");
    if (btn) {
      btn.classList.add("wow-on");
      setTimeout(() => btn.classList.remove("wow-on"), 1600);
    }
  }

  async function runResonance(q) {
    const query = (q || "").trim();
    if (!query) return;
    const params = new URLSearchParams({ q: query, k: "20" });
    const j = await fetchJSON(`/api/resonance?${params}`);
    const d = j.data || {};
    setText(
      "snap-info",
      `search ${d.mode || "off"} · ${d.n_hits || 0} hits · ${d.n_cells || 0} cells`
    );
    flashResonance(d);
  }

  function renderLive(data) {
    state.attention = data;
    state.liveRoot = !!data.live;
    const panel = $("live-panel");
    if (panel) panel.hidden = false;
    setText("live-line", data.line || "—");
    const log = [
      `roots     ${(data.roots || []).join(" · ") || "—"}`,
      `sats      ${data.sats ?? data.remaining_sats ?? "—"}   cells ${data.cells ?? data.remaining_cells ?? "—"}`,
      `vacuumed  ${data.vacuumed ?? 0}   retained ${data.retained ?? 0}`,
      `graph     ${data.graph_edges ?? 0} depends_on edges on cell atoms`,
    ].join("\n");
    const pre = $("live-log");
    if (pre) pre.textContent = log;
    updateWowBar();
  }

  async function setLiveRoot(on) {
    const j = await fetchJSON("/api/attention", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(on ? { live: true } : { restore: true }),
    });
    renderLive(j.data || {});
    if (on && state.reachView && state.shell && state.shell !== "all") {
      await commitLive();
    } else if (on && !state.reachView) {
      setReachView(true);
    } else {
      await loadData();
    }
  }

  async function commitLive() {
    $("badge-status").textContent = "vacuum…";
    const j = await fetchJSON("/api/attention", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ commit: true }),
    });
    renderLive(j.data || {});
    await loadData();
    loadGhost().catch(() => {});
    $("badge-status").textContent = "live";
  }

  async function runSystemTick() {
    $("badge-status").textContent = "tick…";
    const j = await fetchJSON("/api/system_tick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settle_local: 1 }),
    });
    renderDecisions(j.data || {});
    $("badge-status").textContent = "live";
  }

  async function runImpact() {
    $("badge-status").textContent = "impact…";
    const shell = state.shell || "all";
    const body = { simulate: true };
    if (shell && shell !== "all") {
      body.or_shell = String(shell).startsWith("shell:")
        ? shell
        : `shell:${shell}`;
    } else {
      const shells = (state.full && state.full.shells) || {};
      const keys = Object.keys(shells);
      if (keys.length) {
        body.or_shell = keys.sort((a, b) => (shells[b] || 0) - (shells[a] || 0))[0];
      }
    }
    const j = await fetchJSON("/api/impact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    renderImpact(j.data || {});
    flashImpact(j.data || {});
    $("badge-status").textContent = "live";
  }

  async function demoGhost() {
    $("badge-status").textContent = "ghost…";
    const j = await fetchJSON("/api/ghost/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ n: 8 }),
    });
    state.ghost = j.data || null;
    updateWowBar();
    setText(
      "snap-info",
      `ghost demo · cooled ${j.data?.cooled ?? 0} · cells ${j.data?.n_cells ?? 0}`
    );
    redrawMap();
    $("badge-status").textContent = "live";
  }

  async function probeReach() {
    try {
      const j = await fetchJSON("/api/reach");
      const d = j.data || {};
      state.reachEnabled = !!d.enabled;
      const t = $("reach-toggle");
      if (t) t.disabled = !state.reachEnabled;
      const wow = $("btn-reach-wow");
      if (wow) wow.disabled = !state.reachEnabled;
      const gd = $("btn-ghost-demo");
      if (gd) gd.disabled = !state.reachEnabled;
      if (!state.reachEnabled) {
        state.reachView = false;
        if (t) t.checked = false;
      }
      updateReachStatus(d.enabled ? { reach: d } : null);
    } catch (e) {
      state.reachEnabled = false;
      const t = $("reach-toggle");
      if (t) t.disabled = true;
    }
  }

  async function postSession() {
    const shell = state.shell || "all";
    const minCount = state.minCount || 1;
    const fleet = state.fleet || "";
    const country = state.country || "";
    const j = await fetchJSON("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        shell,
        fleet,
        country: country || "",
        min_count: minCount,
      }),
    });
    return j.data || {};
  }

  async function loadData() {
    const url = state.reachView ? "/api/data?reach=1" : "/api/data";
    const j = await fetchJSON(url);
    state.full = j.data;
    state.version = j.data.version || 0;
    if (!state.reachView && j.data.density) {
      state.sotCells = j.data.density.length;
    }
    if (j.data.limit != null) {
      syncLoadLimitUI(j.data.limit);
    }
    if (j.data.fleet) {
      state.fleet = j.data.fleet;
      state.country = j.data.country || "";
      const lim = j.data.limit != null ? j.data.limit : state.loadLimit;
      setText(
        "fleet-info",
        `fleet ${j.data.fleet}${j.data.country ? " · " + j.data.country : ""} · limit ${lim === 0 ? "full" : lim} · src ${j.data.tle_source || "—"}`
      );
      const sel = $("fleet-select");
      if (sel && ![...sel.options].some((o) => o.value === j.data.fleet)) {
        const opt = document.createElement("option");
        opt.value = j.data.fleet;
        opt.textContent = j.data.fleet;
        sel.appendChild(opt);
      }
      if (sel) sel.value = j.data.fleet.split(",")[0];
    }
    const countries =
      (j.data.summary && j.data.summary.countries) || j.data.countries || {};
    fillCountrySelect(countries, state.country);
    if (state.reachView) {
      drawFromPayload(j.data);
      updateReachStatus(j.data);
      const sc = (j.data.reach && j.data.reach.scope) || {};
      setText(
        "filter-info",
        `${sc.shell || state.shell || "all"} · min≥${sc.min_count || state.minCount || 1} · reach`
      );
    } else if (state.shell !== "all" || state.minCount > 1) {
      await applyFilter();
      updateReachStatus(null);
    } else {
      drawFromPayload(j.data);
      updateReachStatus(null);
    }
    setText("err", "");
    loadGeo().catch(() => {});
    loadGhost().catch(() => {});
    loadEventAlert().catch(() => {});
  }

  function renderEventAlert(data) {
    const bar = $("event-alert");
    const line = $("event-alert-line");
    if (!bar) return;
    if (data && data.alert) {
      bar.hidden = false;
      if (line) line.textContent = data.line || "EM storm watch";
    } else {
      bar.hidden = true;
      if (line) line.textContent = (data && data.line) || "quiet";
    }
  }

  async function loadEventAlert() {
    const j = await fetchJSON("/api/alert");
    renderEventAlert(j.data || {});
  }

  async function loadFleetList() {
    try {
      const j = await fetchJSON("/api/fleets");
      const sel = $("fleet-select");
      if (!sel) return;
      const cur = (j.data && j.data.current) || "starlink";
      const fleets = (j.data && j.data.fleets) || [];
      sel.innerHTML = "";
      fleets.forEach((f) => {
        const opt = document.createElement("option");
        opt.value = f.id;
        opt.textContent = f.label + (f.note ? ` — ${f.note}` : "");
        sel.appendChild(opt);
      });
      const merge = document.createElement("option");
      merge.value = "starlink,oneweb";
      merge.textContent = "Starlink + OneWeb (merge)";
      sel.appendChild(merge);
      const debris = document.createElement("option");
      debris.value = "debris";
      debris.textContent = "Public debris (5 event clouds)";
      sel.appendChild(debris);
      const all = document.createElement("option");
      all.value = "all";
      all.textContent = "All curated fleets (merge, no active / no debris)";
      sel.appendChild(all);
      if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
      else if (String(cur).includes(",")) {
        // keep multi as custom option
        const opt = document.createElement("option");
        opt.value = cur;
        opt.textContent = `Current merge: ${cur}`;
        sel.appendChild(opt);
        sel.value = cur;
      } else sel.value = cur.split(",")[0] || "starlink";
      const lim = state.full?.limit != null ? state.full.limit : state.loadLimit;
      syncLoadLimitUI(lim);
      setText(
        "fleet-info",
        `fleet ${cur} · limit ${lim === 0 ? "full" : lim}`
      );
    } catch (e) {
      /* ignore */
    }
  }

  async function applyFleet(fleetOverride) {
    const sel = $("fleet-select");
    const csel = $("country-select");
    const fleet = fleetOverride || (sel && sel.value) || "starlink";
    const country = (csel && csel.value) || "";
    const limit = readLoadLimit();
    const limitLabel = limit === 0 ? "full" : String(limit);
    setText(
      "fleet-info",
      `loading ${fleet}${country ? " · " + country : ""} · limit ${limitLabel}…`
    );
    $("badge-status").textContent = "loading…";
    const btn = $("btn-load-sats");
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Loading…";
    }
    try {
      const j = await fetchJSON("/api/fleet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fleet,
          country: country || null,
          limit,
        }),
      });
      state.fleet = j.data.fleet;
      state.country = j.data.country || "";
      state.loadLimit = j.data.limit != null ? j.data.limit : limit;
      syncLoadLimitUI(state.loadLimit);
      setText(
        "fleet-info",
        `fleet ${j.data.fleet}${state.country ? " · " + state.country : ""} · n=${j.data.using} · limit ${state.loadLimit === 0 ? "full" : state.loadLimit} · ${j.data.src || ""}`
      );
      if (j.data.summary && j.data.summary.countries) {
        fillCountrySelect(j.data.summary.countries, state.country);
      }
      if (state.reachView) {
        await postSession();
      }
      await loadData();
      if (
        window.CynoberGlobe &&
        document.getElementById("panel-globe")?.style.display !== "none"
      ) {
        window.CynoberGlobe.refresh();
      }
      $("badge-status").textContent = "live";
      $("badge-status").classList.add("ok");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Load satellites";
      }
    }
  }

  async function loadTimeline() {
    const j = await fetchJSON("/api/timeline?limit=30");
    const box = $("timeline-list");
    const frames = (j.data && j.data.frames) || [];
    if (!box) return;
    if (!frames.length) {
      box.innerHTML = `<div class="snap-row"><span class="meta">no snapshots yet — Save a frame first</span></div>`;
      setText("timeline-info", "timeline empty");
      return;
    }
    box.innerHTML = frames
      .slice()
      .reverse()
      .slice(0, 20)
      .map(
        (f) =>
          `<div class="snap-row"><div><div>${f.snapshot_id || "—"}</div>` +
          `<div class="meta">${f.created_at || ""} · cells ${f.cells ?? "—"} · Σ ${f.sum_count ?? "—"} · haz ${f.hazard_score ?? "—"}</div></div></div>`
      )
      .join("");
    setText("timeline-info", `${frames.length} frames · oldest→newest metrics`);
  }

  async function compareNewestTimeline() {
    const j = await fetchJSON("/api/timeline?limit=5");
    const frames = (j.data && j.data.frames) || [];
    if (frames.length < 2) {
      setText("timeline-info", "need ≥2 snapshots to compare");
      return;
    }
    const a = frames[frames.length - 2].snapshot_id;
    const b = frames[frames.length - 1].snapshot_id;
    await runDeltaCompare(a, b);
  }

  function renderDeltaHazard(d) {
    const strip = $("delta-hazard-strip");
    const line = $("delta-haz-line");
    const hz = (d && d.hazard_delta) || {};
    if (!strip || !line) return;
    if (!hz.available) {
      strip.hidden = true;
      return;
    }
    strip.hidden = false;
    const a = hz.a || {};
    const b = hz.b || {};
    const ds =
      hz.delta_score == null
        ? "—"
        : (hz.delta_score >= 0 ? "+" : "") + Number(hz.delta_score).toFixed(2);
    line.textContent = `score ${a.score ?? "—"}→${b.score ?? "—"} (Δ ${ds}) · sev ${a.severity ?? "—"}→${b.severity ?? "—"}`;
  }

  function drawDeltaMap(d) {
    const canvas = $("heatmap");
    if (!canvas || !d) return;
    const cells = d.cells_changed || [];
    let nlat = Number(d.nlat) || state.nlat || 36;
    let nlon = Number(d.nlon) || state.nlon || 72;
    if (state.full) {
      nlat = state.full.nlat || nlat;
      nlon = state.full.nlon || nlon;
    }
    state.nlat = nlat;
    state.nlon = nlon;
    const wrap = $("map-wrap");
    const availW = Math.max(
      320,
      (wrap && wrap.clientWidth) || canvas.parentElement?.clientWidth || 960
    );
    const cellPx = Math.max(2, Math.floor(availW / nlon));
    state.cellPx = cellPx;
    const cssW = Math.max(1, nlon * cellPx);
    const cssH = Math.max(1, nlat * cellPx);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.style.width = `${cssW}px`;
    canvas.style.maxWidth = "100%";
    canvas.style.height = "auto";
    canvas.style.aspectRatio = `${nlon} / ${nlat}`;
    canvas.width = Math.max(1, Math.round(cssW * dpr));
    canvas.height = Math.max(1, Math.round(cssH * dpr));
    canvas.style.imageRendering = cellPx >= 3 ? "pixelated" : "auto";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#08060a";
    ctx.fillRect(0, 0, cssW, cssH);
    const maxAbs = Math.max(
      1,
      ...cells.map((c) => Math.abs(Number(c.delta) || 0))
    );
    cells.forEach((c) => {
      const ilat = Number(c.ilat);
      const ilon = Number(c.ilon);
      if (!Number.isFinite(ilat) || !Number.isFinite(ilon)) return;
      const dlt = Number(c.delta) || 0;
      const t = Math.min(1, Math.abs(dlt) / maxAbs);
      let fill;
      if (c.kind === "appeared" || dlt > 0) {
        fill = `rgba(${Math.round(40 + 80 * t)},${Math.round(180 + 60 * t)},${Math.round(90 + 40 * t)},${0.45 + 0.5 * t})`;
      } else {
        fill = `rgba(${Math.round(200 + 40 * t)},${Math.round(60 + 40 * (1 - t))},${Math.round(70 + 30 * (1 - t))},${0.45 + 0.5 * t})`;
      }
      ctx.fillStyle = fill;
      ctx.fillRect(ilon * cellPx, (nlat - 1 - ilat) * cellPx, cellPx, cellPx);
    });
    setText(
      "map2d-title",
      `delta · +${d.appeared || 0} / −${d.vanished || 0} · ΔΣ ${d.delta_sum_count ?? "—"}`
    );
    setText(
      "map-px-info",
      `delta cells ${cells.length} · px ${cellPx} · research · not SSA`
    );
  }

  async function runDeltaCompare(a, b) {
    const c = await fetchJSON(
      `/api/delta?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`
    );
    const d = c.data || {};
    state.delta = d;
    const sat = d.sats_delta || {};
    const satLine = sat.available
      ? ` · sat lost ${sat.lost_n || 0} / new ${sat.gained_n || 0}`
      : "";
    setText(
      "timeline-info",
      `Δ ${a} → ${b}: ΔΣ=${d.delta_sum_count ?? "—"} grew=${d.grew} shrunk=${d.shrunk} new=${d.appeared} gone=${d.vanished}${satLine}`
    );
    renderDeltaHazard(d);
    if (state.deltaMode) drawDeltaMap(d);
    await loadDeltaLog();
    if (window.CynoberGlobe && document.getElementById("panel-globe")?.style.display !== "none") {
      window.CynoberGlobe.showDelta(d);
    }
    return d;
  }

  async function runDeltaLive() {
    const c = await fetchJSON("/api/delta?live=1");
    const d = c.data || {};
    state.delta = d;
    setText(
      "timeline-info",
      `liveΔ vs baseline: ΔΣ=${d.delta_sum_count ?? "—"} appeared=${d.appeared} vanished=${d.vanished}`
    );
    renderDeltaHazard(d);
    if (state.deltaMode) drawDeltaMap(d);
    await loadDeltaLog();
    if (window.CynoberGlobe && document.getElementById("panel-globe")?.style.display !== "none") {
      window.CynoberGlobe.showDelta(d);
    }
    return d;
  }

  async function armDeltaBaseline() {
    const j = await fetchJSON("/api/delta/baseline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const d = (j && j.data) || {};
    setText(
      "timeline-info",
      `baseline armed · ${d.snapshot_id || "—"} · cells ${d.cells ?? "—"}`
    );
    await loadDeltaLog();
  }

  async function loadDeltaLog() {
    const j = await fetchJSON("/api/delta/log?limit=40");
    const box = $("delta-log");
    if (!box) return;
    const entries = (j.data && j.data.entries) || [];
    if (!entries.length) {
      box.textContent = "(empty — arm baseline or compare snapshots)";
      return;
    }
    box.textContent = entries
      .map((e) => {
        const t = (e.iso || "").replace("T", " ").replace("Z", "");
        return `${t}  [${e.kind}] ${e.message}`;
      })
      .join("\n");
  }

  function enterDeltaMode() {
    state.deltaMode = true;
    setText("layer-info", "DELTA · only changes · green↑ red↓ · vanished ≈ density loss");
    if (state.delta) drawDeltaMap(state.delta);
    else {
      compareNewestTimeline().catch(() =>
        setText("timeline-info", "Save ≥2 snapshots or Arm baseline + Live Δ")
      );
    }
    loadDeltaLog().catch(() => {});
    if (state.deltaPoll) clearInterval(state.deltaPoll);
    state.deltaPoll = setInterval(() => {
      loadDeltaLog().catch(() => {});
    }, 4000);
  }

  function leaveDeltaMode() {
    state.deltaMode = false;
    if (state.deltaPoll) {
      clearInterval(state.deltaPoll);
      state.deltaPoll = null;
    }
    const strip = $("delta-hazard-strip");
    if (strip) strip.hidden = true;
    if (state.full) drawFromPayload(state.full);
  }

  window.CynoberDelta = {
    enter: enterDeltaMode,
    leave: leaveDeltaMode,
    compare: runDeltaCompare,
    live: runDeltaLive,
  };

  async function applyFilter() {
    const shell = state.shell || "all";
    const minCount = state.minCount || 1;
    if (state.reachView && state.reachEnabled) {
      await postSession();
      await loadData();
      return;
    }
    if (shell === "all" && minCount <= 1 && state.full) {
      drawFromPayload(state.full);
      return;
    }
    const q = new URLSearchParams({
      shell: String(shell),
      min_count: String(minCount),
    });
    const j = await fetchJSON(`/api/filter?${q}`);
    const d = j.data;
    const nlat = state.full?.nlat || 36;
    const nlon = state.full?.nlon || 72;
    // merge filter into view using full summary for shells
    const dens = d.density || [];
    state.nlat = nlat;
    state.nlon = nlon;
    state.view = dens;
    // H8: group/shell filter → fewer sats → larger pixels
    state.nSats = Number(d.count_sats) || dens.reduce((s, x) => s + (x.count || 0), 0);
    drawMap(dens, nlat, nlon, state.layer || "density");
    setText("stat-cells", d.count_cells);
    setText("stat-sats", d.count_sats);
    setText("stat-version", d.version);
    setText(
      "filter-info",
      `${d.shell} · min≥${d.min_count} · cells ${d.count_cells} · ~${state.cellPx}px`
    );
    analyzeDensity(dens);
  }

  async function refreshMap() {
    $("badge-status").textContent = "refresh…";
    $("badge-status").classList.remove("ok");
    await fetchJSON("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes: 0, reload_tle: false }),
    });
    await loadData();
    if (window.CynoberGlobe && document.getElementById("panel-globe")?.style.display !== "none") {
      window.CynoberGlobe.refresh();
    }
  }

  async function saveSnapshot() {
    const j = await fetchJSON("/api/snapshot/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const d = j.data || {};
    setText(
      "snap-info",
      `saved ${d.snapshot_id || "?"} · cells ${d.cells_count ?? "—"}`
    );
    await listSnapshots();
  }

  async function listSnapshots() {
    const box = $("snap-list");
    if (!box) return;
    const j = await fetchJSON("/api/snapshots");
    const items = j.data || [];
    if (!items.length) {
      box.innerHTML = `<div class="snap-row"><span class="meta">No local snapshots yet. Save a frame first.</span></div>`;
      setText("library-info", "empty");
      return;
    }
    box.innerHTML = "";
    for (const m of items.slice(0, 40)) {
      const row = document.createElement("div");
      row.className = "snap-row";
      if (state.loadedSnap === m.snapshot_id) row.classList.add("active");
      const left = document.createElement("div");
      left.innerHTML = `<div><b>${m.snapshot_id}</b></div>
        <div class="meta">cells ${m.cells_count ?? "—"} · sats ${m.sats_count ?? "—"} · v${m.version ?? 0}<br/>${m.created_at || ""}</div>`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Load";
      btn.title = "Load into Studio and redraw 2D/3D";
      btn.addEventListener("click", () => {
        loadSnapshot(m.snapshot_id).catch((e) =>
          setText("err", String(e.message || e))
        );
      });
      row.appendChild(left);
      row.appendChild(btn);
      box.appendChild(row);
    }
    setText("library-info", `${items.length} snapshot(s)`);
  }

  async function loadSnapshot(snapshotId) {
    $("badge-status").textContent = "load…";
    $("badge-status").classList.remove("ok");
    const j = await fetchJSON("/api/snapshot/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot_id: snapshotId }),
    });
    const d = j.data || {};
    state.loadedSnap = d.snapshot_id || snapshotId;
    setText(
      "snap-info",
      `loaded ${state.loadedSnap} · cells ${d.cells ?? "—"} · sats ${d.sats ?? "—"}`
    );
    // reset filter to full view of loaded frame
    state.shell = "all";
    state.minCount = 1;
    const r = $("min-count");
    if (r) r.value = "1";
    setText("min-count-val", "1");
    setText("filter-info", "all · min≥1 (loaded frame)");
    await loadData();
    if (window.CynoberGlobe) window.CynoberGlobe.refresh();
    await listSnapshots();
    $("badge-status").textContent = "snapshot";
    $("badge-status").classList.add("ok");
  }

  async function pushRpc() {
    $("badge-status").textContent = "push…";
    const j = await fetchJSON("/api/rpc/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const d = j.data || {};
    setText(
      "snap-info",
      `rpc-push ${d.snapshot_id || "?"} · ${d.bytes_sent ?? "?"} B · cells ${d.cells ?? "—"}`
    );
    $("badge-status").textContent = "live";
    $("badge-status").classList.add("ok");
    await listSnapshots();
  }

  async function pollVersion() {
    try {
      const headers = {};
      if (state.versionEtag) headers["If-None-Match"] = state.versionEtag;
      const j = await fetchJSON("/api/version", { headers });
      if (j._status === 304 || j.status === "not_modified") {
        return; // C: unchanged — skip redraw
      }
      if (j._etag) state.versionEtag = j._etag;
      if (j.version !== state.version) {
        await loadData();
      }
    } catch (e) {
      /* ignore poll errors */
    }
  }

  function setHazardBadgeClass(el, severity) {
    if (!el) return;
    el.classList.remove("ok", "warn", "danger");
    const s = String(severity || "").toUpperCase();
    if (s === "WARNING") el.classList.add("danger");
    else if (s === "WATCH") el.classList.add("warn");
    else el.classList.add("ok");
  }

  /** H8: edge aura from real solar score. No invented glow without weather. */
  function applyEdgeAura(score, severity) {
    const s = Number(score);
    let strength = 0;
    if (score != null && !Number.isNaN(s)) {
      strength = Math.max(0, Math.min(0.95, (s / 100) * 0.85));
    }
    const sev = String(severity || "INFO").toUpperCase();
    if (sev === "WARNING") strength = Math.max(strength, 0.72);
    else if (sev === "WATCH") strength = Math.max(strength, 0.48);

    ["map-wrap", "globe-wrap"].forEach((id) => {
      const el = $(id);
      if (el) el.style.setProperty("--aura-strength", String(strength.toFixed(3)));
    });
    ["map-aura", "globe-aura"].forEach((id) => {
      const el = $(id);
      if (!el) return;
      el.dataset.severity = sev === "WARNING" || sev === "WATCH" ? sev : "INFO";
      el.title = `edge aura · stress≈${Number.isNaN(s) ? "—" : s.toFixed(0)} · ${sev}`;
    });
  }

  function renderHazard(data) {
    if (!data) return;
    state.hazard = data;
    const w = data.weather || {};
    setText("wx-flare", w.flare_class || "—");
    setText("wx-f107", w.f107 != null ? Number(w.f107).toFixed(0) : "—");
    setText("wx-kp", w.kp != null ? Number(w.kp).toFixed(2) : "—");
    setText("wx-mode", w.mode || "—");
    setText("wx-stress", data.global_score != null ? Number(data.global_score).toFixed(0) : "—");
    setText("wx-sev", data.severity || "—");
    applyEdgeAura(data.global_score, data.severity);
    const disc = $("wx-disclaimer");
    if (disc) {
      disc.textContent = data.disclaimer || "Public indices · research proxy";
    }
    const badgeWx = $("badge-weather");
    if (badgeWx) {
      const fc = w.flare_class || "?";
      const f107 = w.f107 != null ? Number(w.f107).toFixed(0) : "—";
      const kp = w.kp != null ? Number(w.kp).toFixed(1) : "—";
      const wxMode = w.mode && w.mode !== "live" ? ` · ${w.mode}` : "";
      badgeWx.textContent = `solar ${fc} · F${f107} · Kp ${kp}${wxMode}`;
      setHazardBadgeClass(badgeWx, data.severity);
    }
    const badgeHz = $("badge-hazard");
    if (badgeHz) {
      badgeHz.textContent =
        data.badge ||
        `hazard ${data.global_score != null ? Number(data.global_score).toFixed(0) : "—"} · ${data.severity || ""}`;
      setHazardBadgeClass(badgeHz, data.severity);
    }
    const box = $("hazard-shell-list");
    if (box) {
      const shells = (data.groups || []).filter((g) => g.kind === "shell");
      if (!shells.length) {
        box.innerHTML = `<div><span>no shells</span><b>—</b></div>`;
      } else {
        box.innerHTML = shells
          .slice(0, 12)
          .map(
            (g) =>
              `<div><span>${g.group_id} · n=${g.n_sats}</span><b>${Number(
                g.score
              ).toFixed(0)} ${g.severity}</b></div>`
          )
          .join("");
      }
    }
    // refresh overlay colors when weather updates
    if (state.view && (state.layer === "hazard" || state.layer === "blend")) {
      redrawMap();
    }
  }

  function renderPredict(data) {
    if (!data) return;
    state.predict = data;
    const box = $("predict-horizons");
    if (box) {
      const rows = data.horizons || [];
      if (!rows.length) {
        box.innerHTML = `<div><span>no horizons</span><b>—</b></div>`;
      } else {
        const nowLine = `<div><span>now</span><b>${
          data.now_score != null ? Number(data.now_score).toFixed(0) : "—"
        } ${data.now_severity || ""}</b></div>`;
        const hz = rows
          .map(
            (h) =>
              `<div><span>${h.label} · ${h.flare_class || "?"} · Kp ${
                h.kp != null ? Number(h.kp).toFixed(1) : "—"
              }</span><b>${Number(h.global_score).toFixed(0)} ${
                h.severity || ""
              }</b></div>`
          )
          .join("");
        box.innerHTML = nowLine + hz;
      }
    }
    const meth = $("predict-method");
    if (meth) {
      const sn = data.series_used || {};
      const snParts = Object.keys(sn)
        .filter((k) => sn[k])
        .map((k) => `${k}=${sn[k]}`)
        .join(" · ");
      meth.textContent = [
        data.method || "—",
        snParts || "no series",
        data.badge || "",
      ]
        .filter(Boolean)
        .join(" · ");
    }
  }

  async function loadWeatherHazard(force) {
    const q = force ? "?force=1" : "";
    const j = await fetchJSON(`/api/hazard${q}`);
    state.hazard = j.data;
    renderHazard(j.data);
    try {
      const p = await fetchJSON(`/api/predict${q}`);
      renderPredict(p.data);
    } catch (e) {
      const box = $("predict-horizons");
      if (box) box.innerHTML = `<div><span>predict</span><b>offline</b></div>`;
    }
    loadGeo().catch(() => {});
  }

  function renderGeo(data) {
    if (!data) return;
    state.geo = data;
    const frac =
      data.sunlit_frac != null
        ? `${(Number(data.sunlit_frac) * 100).toFixed(0)}% (${data.sunlit}/${data.n_with_pos})`
        : "—";
    setText("geo-sunlit", frac);
    setText(
      "geo-alt-med",
      data.median_alt_km != null ? `${Number(data.median_alt_km).toFixed(0)} km` : "—"
    );
    const lo = data.min_alt_km != null ? Number(data.min_alt_km).toFixed(0) : "—";
    const hi = data.max_alt_km != null ? Number(data.max_alt_km).toFixed(0) : "—";
    setText("geo-alt-range", `${lo}–${hi} km`);
    const badge = $("geo-badge");
    if (badge) badge.textContent = data.badge || data.disclaimer || "";
    const box = $("geo-bands");
    if (box) {
      const bands = (data.bands || []).filter((b) => (b.n_sats || 0) > 0);
      if (!bands.length) {
        box.innerHTML = `<div><span>no alt data</span><b>—</b></div>`;
      } else {
        box.innerHTML = bands
          .map(
            (b) =>
              `<div><span>${b.band} · n=${b.n_sats}</span><b>${(
                Number(b.sunlit_frac || 0) * 100
              ).toFixed(0)}% lit · ${Number(b.mean_alt_km || 0).toFixed(0)} km</b></div>`
          )
          .join("");
      }
    }
  }

  async function loadGeo() {
    const j = await fetchJSON("/api/geo");
    renderGeo(j.data);
  }

  function setupTooltip() {
    const canvas = $("heatmap");
    const tip = $("tooltip");
    if (!canvas || !tip) return;
    canvas.addEventListener("mousemove", (ev) => {
      const d = state._draw;
      if (!d) return;
      const rect = canvas.getBoundingClientRect();
      // map pointer through displayed box → grid indices (not raw buffer px)
      const x = ((ev.clientX - rect.left) / Math.max(1, rect.width)) * d.nlon;
      const y = ((ev.clientY - rect.top) / Math.max(1, rect.height)) * d.nlat;
      const ilon = Math.floor(x);
      const ilat = d.nlat - 1 - Math.floor(y);
      const idx = d.density.findIndex((c) => c.ilat === ilat && c.ilon === ilon);
      const cell = idx >= 0 ? d.density[idx] : null;
      const gh0 = d.ghostAt && d.ghostAt.get(`${ilat}:${ilon}`);
      if (!cell && !gh0) {
        tip.classList.remove("show");
        return;
      }
      const lat0 = -90 + ilat * (180 / d.nlat);
      const lon0 = -180 + ilon * (360 / d.nlon);
      const exp =
        idx >= 0 && d.exposures && d.exposures[idx] != null
          ? Number(d.exposures[idx]).toFixed(1)
          : "—";
      const gh = gh0;
      const ghostLine = gh
        ? `<br/>${gh.kind} · T=${gh.T} · in session reach`
        : "";
      const count = cell ? cell.count : "—";
      tip.innerHTML = `<b>cell:${ilat}:${ilon}</b><br/>count=${count}<br/>exposure≈${exp}${ghostLine}<br/>≈ ${lat0.toFixed(
        1
      )}°, ${lon0.toFixed(1)}°`;
      tip.style.left = `${ev.clientX - rect.left + 12}px`;
      tip.style.top = `${ev.clientY - rect.top + 12}px`;
      tip.classList.add("show");
    });
    canvas.addEventListener("mouseleave", () => tip.classList.remove("show"));
  }

  function wire() {
    $("btn-refresh")?.addEventListener("click", () => {
      refreshMap().catch((e) => {
        setText("err", String(e.message || e));
      });
    });
    $("btn-snapshot")?.addEventListener("click", () => {
      saveSnapshot().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-rpc-push")?.addEventListener("click", () => {
      pushRpc().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-snap-refresh")?.addEventListener("click", () => {
      listSnapshots().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-weather")?.addEventListener("click", () => {
      loadWeatherHazard(true).catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-load-sats")?.addEventListener("click", () => {
      applyFleet().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-load-debris")?.addEventListener("click", () => {
      const sel = $("fleet-select");
      if (sel && [...sel.options].some((o) => o.value === "debris")) {
        sel.value = "debris";
      }
      applyFleet("debris").catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-fleet-apply")?.addEventListener("click", () => {
      applyFleet().catch((e) => setText("err", String(e.message || e)));
    });
    const loadLim = $("load-limit");
    if (loadLim) {
      loadLim.addEventListener("input", () => {
        if ($("load-limit-full")?.checked) return;
        setText("load-limit-val", loadLim.value);
        state.loadLimit = parseInt(loadLim.value, 10) || 400;
      });
    }
    $("load-limit-full")?.addEventListener("change", (ev) => {
      const on = !!ev.target.checked;
      if (on) {
        syncLoadLimitUI(0);
      } else {
        const r = $("load-limit");
        syncLoadLimitUI(parseInt(r?.value || "400", 10) || 400);
      }
    });
    syncLoadLimitUI(state.loadLimit);
    $("btn-timeline")?.addEventListener("click", () => {
      loadTimeline().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-timeline-compare")?.addEventListener("click", () => {
      compareNewestTimeline().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-delta-baseline")?.addEventListener("click", () => {
      armDeltaBaseline().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-delta-live")?.addEventListener("click", () => {
      runDeltaLive().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-layer-density")?.addEventListener("click", () => setLayer("density"));
    $("btn-layer-hazard")?.addEventListener("click", () => setLayer("hazard"));
    $("btn-layer-blend")?.addEventListener("click", () => setLayer("blend"));
    $("btn-layer-ghost")?.addEventListener("click", () => setLayer("ghost"));
    $("btn-reset")?.addEventListener("click", () => {
      state.shell = "all";
      state.minCount = 1;
      const r = $("min-count");
      if (r) r.value = "1";
      setText("min-count-val", "1");
      setText("filter-info", "all · min≥1");
      // re-check all radio
      const all = document.querySelector('input[name="shell"][value="all"]');
      if (all) all.checked = true;
      if (state.reachView) {
        applyFilter().catch((e) => setText("err", String(e.message || e)));
      } else if (state.full) {
        drawFromPayload(state.full);
      }
    });
    function setReachView(on) {
      state.reachView = !!on && state.reachEnabled;
      const t = $("reach-toggle");
      if (t) t.checked = state.reachView;
      updateWowBar();
      if (state.reachView) {
        applyFilter().catch((e) => setText("err", String(e.message || e)));
      } else {
        loadData().catch((e) => setText("err", String(e.message || e)));
      }
    }
    $("reach-toggle")?.addEventListener("change", (ev) => {
      setReachView(!!ev.target.checked);
    });
    $("btn-live-wow")?.addEventListener("click", () => {
      setLiveRoot(!state.liveRoot).catch((e) =>
        setText("err", String(e.message || e))
      );
    });
    $("btn-commit-wow")?.addEventListener("click", () => {
      commitLive().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-restore-wow")?.addEventListener("click", () => {
      setLiveRoot(false).catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-reach-wow")?.addEventListener("click", () => {
      setReachView(!state.reachView);
    });
    $("btn-impact-wow")?.addEventListener("click", () => {
      runImpact().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-impact")?.addEventListener("click", () => {
      runImpact().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-tick-wow")?.addEventListener("click", () => {
      runSystemTick().catch((e) => setText("err", String(e.message || e)));
    });
    const reso = $("resonance-q");
    if (reso) {
      reso.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          runResonance(reso.value).catch((e) =>
            setText("err", String(e.message || e))
          );
        }
      });
    }
    $("ghost-under")?.addEventListener("change", (ev) => {
      state.ghostUnder = !!ev.target.checked;
      redrawMap();
    });
    $("btn-ghost-demo")?.addEventListener("click", () => {
      demoGhost().catch((e) => setText("err", String(e.message || e)));
    });
    const doExport = (fmt) => exportFile(fmt);
    $("btn-export-json")?.addEventListener("click", () => doExport("json"));
    $("btn-export-md")?.addEventListener("click", () => doExport("md"));
    $("btn-export-json-wow")?.addEventListener("click", () => doExport("json"));
    $("btn-export-md-wow")?.addEventListener("click", () => doExport("md"));
    document.querySelectorAll("#limit-presets [data-limit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const full = $("load-limit-full");
        if (full) full.checked = false;
        const v = parseInt(btn.getAttribute("data-limit"), 10);
        if (Number.isFinite(v)) syncLoadLimitUI(v);
      });
    });
    $("load-limit-num")?.addEventListener("change", () => {
      const num = $("load-limit-num");
      const v = parseInt(num && num.value, 10);
      if (Number.isFinite(v)) {
        syncLoadLimitUI(Math.max(40, Math.min(50000, v)));
      }
    });
    $("fleet-select")?.addEventListener("change", () => {
      if (!state.reachView) return;
      const sel = $("fleet-select");
      state.fleet = (sel && sel.value) || state.fleet;
      applyFilter().catch((e) => setText("err", String(e.message || e)));
    });
    $("country-select")?.addEventListener("change", () => {
      if (!state.reachView) return;
      const csel = $("country-select");
      state.country = (csel && csel.value) || "";
      applyFilter().catch((e) => setText("err", String(e.message || e)));
    });
    const range = $("min-count");
    if (range) {
      range.addEventListener("input", () => {
        state.minCount = parseInt(range.value, 10) || 1;
        setText("min-count-val", String(state.minCount));
      });
      range.addEventListener("change", () => {
        applyFilter().catch((e) => setText("err", String(e.message || e)));
      });
    }
    setupTooltip();
    listSnapshots().catch(() => {});
    loadFleetList().catch(() => {});
    loadTimeline().catch(() => {});
    fetchJSON("/api/rpc/status")
      .then((j) => {
        const btn = $("btn-rpc-push");
        if (btn && j.data && j.data.available) btn.hidden = false;
      })
      .catch(() => {});
    // re-fit adaptive cells when panel width changes
    let _rz = null;
    window.addEventListener("resize", () => {
      clearTimeout(_rz);
      _rz = setTimeout(() => {
        if (state.view) redrawMap();
      }, 120);
    });
    applyEdgeAura(null, "");
    loadWeatherHazard(false).catch(() => {
      setText("badge-weather", "solar offline");
      applyEdgeAura(null, "");
    });
    probeReach()
      .catch(() => {})
      .then(() => loadData())
      .catch((e) => setText("err", String(e.message || e)))
      .then(() => {
        setInterval(() => {
          pollVersion();
        }, state.pollMs);
        // weather slower than map poll
        setInterval(() => {
          loadWeatherHazard(false).catch(() => {});
        }, Math.max(state.pollMs * 12, 60000));
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
