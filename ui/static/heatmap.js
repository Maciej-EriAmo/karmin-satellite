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

  function drawDensity(density, nlat, nlon) {
    const canvas = $("heatmap");
    if (!canvas) return;
    const w = Math.max(360, nlon * 8);
    const h = Math.max(180, nlat * 8);
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#08060a";
    ctx.fillRect(0, 0, w, h);

    const maxC = density.reduce((m, d) => Math.max(m, d.count || 0), 1);
    const cw = w / nlon;
    const ch = h / nlat;

    for (const d of density) {
      const T = densityToT(d.count || 0, maxC);
      const [r, g, b] = tToRgb(T);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      const x = d.ilon * cw;
      const y = (nlat - 1 - d.ilat) * ch;
      ctx.fillRect(x, y, Math.ceil(cw), Math.ceil(ch));
    }

    // store for tooltip
    state._draw = { nlat, nlon, maxC, density, cw, ch, w, h };
  }

  function drawFromPayload(data) {
    const nlat = data.nlat || 36;
    const nlon = data.nlon || 72;
    const density = data.density || [];
    state.view = density;
    drawDensity(density, nlat, nlon);
    updateStats(data.summary, data);
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
    drawDensity(d.density || [], nlat, nlon);
    setText("stat-cells", d.count_cells);
    setText("stat-sats", d.count_sats);
    setText("stat-version", d.version);
    setText("filter-info", `${d.shell} · min≥${d.min_count} · cells ${d.count_cells}`);
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
      const cell = d.density.find((c) => c.ilat === ilat && c.ilon === ilon);
      if (!cell) {
        tip.classList.remove("show");
        return;
      }
      const lat0 = -90 + ilat * (180 / d.nlat);
      const lon0 = -180 + ilon * (360 / d.nlon);
      tip.innerHTML = `<b>cell:${ilat}:${ilon}</b><br/>count=${cell.count}<br/>≈ ${lat0.toFixed(
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
    loadData()
      .catch((e) => setText("err", String(e.message || e)))
      .then(() => {
        setInterval(() => {
          pollVersion();
        }, state.pollMs);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
