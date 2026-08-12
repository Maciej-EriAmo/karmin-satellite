/* Cynober Studio — 2D density canvas + filters */
(() => {
  const $ = (id) => document.getElementById(id);

  const state = {
    version: 0,
    full: null, // last /api/data
    view: null, // density currently drawn (full or filtered)
    shell: "all",
    minCount: 1,
    pollMs: 5000,
    layer: "density", // density | hazard | blend
    hazard: null,
    nlat: 36,
    nlon: 72,
    nSats: 0, // for H8 adaptive pixels
    cellPx: 8,
  };
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
    ["density", "hazard", "blend"].forEach((L) => {
      const btn = $(`btn-layer-${L}`);
      if (btn) btn.classList.toggle("primary", L === layer);
    });
    const titles = {
      density: "density",
      hazard: "solar exposure (proxy)",
      blend: "density + hazard blend",
    };
    setText("map2d-title", titles[layer] || layer);
    setText(
      "layer-info",
      layer === "density"
        ? "density · solar overlay off"
        : layer === "hazard"
          ? "hazard · density off (research proxy)"
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

  /** @deprecated use drawMap */
  function drawDensity(density, nlat, nlon) {
    drawMap(density, nlat, nlon, state.layer || "density");
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
      const lat0 = -90 + (hot.ilat || 0) * 5;
      const lon0 = -180 + (hot.ilon || 0) * 5;
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
    const j = await resp.json();
    if (!resp.ok || j.status === "error") {
      throw new Error(j.message || resp.statusText);
    }
    return j;
  }

  async function loadData() {
    const j = await fetchJSON("/api/data");
    state.full = j.data;
    state.version = j.data.version || 0;
    if (j.data.fleet) {
      state.fleet = j.data.fleet;
      setText("fleet-info", `fleet ${j.data.fleet} · src ${j.data.tle_source || "—"}`);
      const sel = $("fleet-select");
      if (sel && ![...sel.options].some((o) => o.value === j.data.fleet)) {
        const opt = document.createElement("option");
        opt.value = j.data.fleet;
        opt.textContent = j.data.fleet;
        sel.appendChild(opt);
      }
      if (sel) sel.value = j.data.fleet.split(",")[0];
    }
    // if filter active, re-apply; else full
    if (state.shell !== "all" || state.minCount > 1) {
      await applyFilter();
    } else {
      drawFromPayload(j.data);
    }
    setText("err", "");
    loadGeo().catch(() => {});
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
      // merge option
      const merge = document.createElement("option");
      merge.value = "starlink,oneweb";
      merge.textContent = "Starlink + OneWeb (merge)";
      sel.appendChild(merge);
      if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
      else sel.value = cur.split(",")[0] || "starlink";
      setText("fleet-info", `fleet ${cur}`);
    } catch (e) {
      /* ignore */
    }
  }

  async function applyFleet() {
    const sel = $("fleet-select");
    const fleet = (sel && sel.value) || "starlink";
    setText("fleet-info", `loading ${fleet}…`);
    $("badge-status").textContent = "fleet…";
    const j = await fetchJSON("/api/fleet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fleet, limit: state.full?.limit || 0 }),
    });
    state.fleet = j.data.fleet;
    setText(
      "fleet-info",
      `fleet ${j.data.fleet} · n=${j.data.using} · ${j.data.src || ""}`
    );
    await loadData();
    if (window.CynoberGlobe && document.getElementById("panel-globe")?.style.display !== "none") {
      window.CynoberGlobe.refresh();
    }
    $("badge-status").textContent = "live";
    $("badge-status").classList.add("ok");
  }

  async function applyFilter() {
    const shell = state.shell || "all";
    const minCount = state.minCount || 1;
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
      const j = await fetchJSON("/api/version");
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

  /** H8: edge aura strength 0..1 from solar stress score + severity. */
  function applyEdgeAura(score, severity) {
    const s = Number(score);
    // quiet ~0.25, watch ~0.55, warning ~0.85+
    let strength = 0.28;
    if (!Number.isNaN(s)) {
      strength = Math.max(0.22, Math.min(0.95, 0.18 + (s / 100) * 0.85));
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
      badgeWx.textContent = `solar ${fc} · F${f107} · Kp ${kp}`;
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
      if (!cell) {
        tip.classList.remove("show");
        return;
      }
      const lat0 = -90 + ilat * (180 / d.nlat);
      const lon0 = -180 + ilon * (360 / d.nlon);
      const exp =
        d.exposures && d.exposures[idx] != null
          ? Number(d.exposures[idx]).toFixed(1)
          : "—";
      tip.innerHTML = `<b>cell:${ilat}:${ilon}</b><br/>count=${cell.count}<br/>exposure≈${exp}<br/>≈ ${lat0.toFixed(
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
    $("btn-fleet-apply")?.addEventListener("click", () => {
      applyFleet().catch((e) => setText("err", String(e.message || e)));
    });
    $("btn-layer-density")?.addEventListener("click", () => setLayer("density"));
    $("btn-layer-hazard")?.addEventListener("click", () => setLayer("hazard"));
    $("btn-layer-blend")?.addEventListener("click", () => setLayer("blend"));
    $("btn-reset")?.addEventListener("click", () => {
      state.shell = "all";
      state.minCount = 1;
      const r = $("min-count");
      if (r) r.value = "1";
      setText("min-count-val", "1");
      if (state.full) drawFromPayload(state.full);
      setText("filter-info", "all · min≥1");
      // re-check all radio
      const all = document.querySelector('input[name="shell"][value="all"]');
      if (all) all.checked = true;
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
    // re-fit adaptive cells when panel width changes
    let _rz = null;
    window.addEventListener("resize", () => {
      clearTimeout(_rz);
      _rz = setTimeout(() => {
        if (state.view) redrawMap();
      }, 120);
    });
    // default edge aura visible even before weather fetch
    applyEdgeAura(25, "INFO");
    loadWeatherHazard(false).catch(() => {
      setText("badge-weather", "solar offline");
      applyEdgeAura(25, "INFO");
    });
    loadData()
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
