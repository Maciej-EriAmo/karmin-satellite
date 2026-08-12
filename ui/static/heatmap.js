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
  };

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
    const w = Math.max(360, nlon * 8);
    const h = Math.max(180, nlat * 8);
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#08060a";
    ctx.fillRect(0, 0, w, h);

    const dens = density || [];
    const maxC = dens.reduce((m, d) => Math.max(m, d.count || 0), 1);
    const base = baseScoreFromHazard();
    const exposures = dens.map((d) =>
      exposureForCell(d.count || 0, maxC, base)
    );
    const maxExp = Math.max(base, ...exposures, 1);
    const cw = w / nlon;
    const ch = h / nlat;
    const mode = layer || "density";

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
        // weight hazard by relative exposure
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
      ctx.fillRect(x, y, Math.ceil(cw), Math.ceil(ch));
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
      w,
      h,
      layer: mode,
    };
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
    drawMap(density, nlat, nlon, state.layer || "density");
    updateStats(data.summary, data);
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
    // if filter active, re-apply; else full
    if (state.shell !== "all" || state.minCount > 1) {
      await applyFilter();
    } else {
      drawFromPayload(j.data);
    }
    setText("err", "");
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
    drawMap(dens, nlat, nlon, state.layer || "density");
    setText("stat-cells", d.count_cells);
    setText("stat-sats", d.count_sats);
    setText("stat-version", d.version);
    setText("filter-info", `${d.shell} · min≥${d.min_count} · cells ${d.count_cells}`);
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

  async function loadWeatherHazard(force) {
    const q = force ? "?force=1" : "";
    const j = await fetchJSON(`/api/hazard${q}`);
    state.hazard = j.data;
    renderHazard(j.data);
  }

  function setupTooltip() {
    const canvas = $("heatmap");
    const tip = $("tooltip");
    if (!canvas || !tip) return;
    canvas.addEventListener("mousemove", (ev) => {
      const d = state._draw;
      if (!d) return;
      const rect = canvas.getBoundingClientRect();
      const sx = canvas.width / rect.width;
      const sy = canvas.height / rect.height;
      const x = (ev.clientX - rect.left) * sx;
      const y = (ev.clientY - rect.top) * sy;
      const ilon = Math.floor(x / d.cw);
      const ilat = d.nlat - 1 - Math.floor(y / d.ch);
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
    loadWeatherHazard(false).catch(() => {
      setText("badge-weather", "solar offline");
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
