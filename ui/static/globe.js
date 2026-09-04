/* Karmin Satellite — S2b / H6 3D globe (Three.js CDN)
 *
 * Layers: density | radiation (H6 intensity) | blend
 * Radiation = solar score × density weight (same proxy as 2D hazard).
 */
(() => {
  const $ = (id) => document.getElementById(id);

  const G = {
    renderer: null,
    scene: null,
    camera: null,
    earth: null,
    wire: null,
    cellGroup: null,
    anim: null,
    ro: null,
    dragging: false,
    lastX: 0,
    lastY: 0,
    version: -1,
    layer: "density", // density | radiation | blend
  };

  function ensureThree(cb) {
    if (window.THREE) {
      cb();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://unpkg.com/three@0.160.0/build/three.min.js";
    s.onload = () => cb();
    s.onerror = () => {
      const err = $("err");
      if (err) err.textContent = "Three.js CDN load failed";
    };
    document.head.appendChild(s);
  }

  function hostSize() {
    const host = $("globe-host");
    const wrap = $("globe-wrap") || host;
    const w = Math.max(480, (wrap && wrap.clientWidth) || host?.clientWidth || 960);
    // fill the enlarged viz frame (CSS sets min ~62vh)
    const h = Math.max(
      480,
      (wrap && wrap.clientHeight) || host?.clientHeight || Math.floor(w * 0.72)
    );
    return { w, h };
  }

  function initScene() {
    const host = $("globe-host");
    if (!host || G.renderer) return;
    const { w, h } = hostSize();
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x08060a);
    const camera = new THREE.PerspectiveCamera(42, w / h, 0.01, 100);
    // slightly closer so Earth fills the larger frame
    camera.position.set(0, 0.28, 2.15);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);
    host.innerHTML = "";
    host.appendChild(renderer.domElement);

    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    scene.add(ambient);
    const dir = new THREE.DirectionalLight(0xffe0d0, 0.85);
    dir.position.set(3, 2, 4);
    scene.add(dir);

    const earth = new THREE.Mesh(
      new THREE.SphereGeometry(0.98, 64, 64),
      new THREE.MeshPhongMaterial({
        color: 0x0a1840,
        emissive: 0x050812,
        shininess: 8,
      })
    );
    scene.add(earth);

    const wire = new THREE.Mesh(
      new THREE.SphereGeometry(0.985, 32, 24),
      new THREE.MeshBasicMaterial({
        color: 0x2a4060,
        wireframe: true,
        transparent: true,
        opacity: 0.15,
      })
    );
    scene.add(wire);

    const cellGroup = new THREE.Group();
    scene.add(cellGroup);

    G.renderer = renderer;
    G.scene = scene;
    G.camera = camera;
    G.earth = earth;
    G.wire = wire;
    G.cellGroup = cellGroup;

    const el = renderer.domElement;
    el.style.cursor = "grab";
    el.addEventListener("pointerdown", (e) => {
      G.dragging = true;
      G.lastX = e.clientX;
      G.lastY = e.clientY;
      el.setPointerCapture(e.pointerId);
      el.style.cursor = "grabbing";
    });
    el.addEventListener("pointerup", () => {
      G.dragging = false;
      el.style.cursor = "grab";
    });
    el.addEventListener("pointermove", (e) => {
      if (!G.dragging) return;
      const dx = e.clientX - G.lastX;
      const dy = e.clientY - G.lastY;
      G.lastX = e.clientX;
      G.lastY = e.clientY;
      cellGroup.rotation.y += dx * 0.005;
      earth.rotation.y += dx * 0.005;
      wire.rotation.y += dx * 0.005;
      cellGroup.rotation.x += dy * 0.004;
      earth.rotation.x += dy * 0.004;
      wire.rotation.x += dy * 0.004;
      cellGroup.rotation.x = Math.max(-1.2, Math.min(1.2, cellGroup.rotation.x));
      earth.rotation.x = cellGroup.rotation.x;
      wire.rotation.x = cellGroup.rotation.x;
    });
    el.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        camera.position.z = Math.max(
          1.4,
          Math.min(5, camera.position.z + e.deltaY * 0.002)
        );
      },
      { passive: false }
    );

    function onResize() {
      const { w: ww, h: hh } = hostSize();
      camera.aspect = ww / hh;
      camera.updateProjectionMatrix();
      renderer.setSize(ww, hh, false);
    }
    window.addEventListener("resize", onResize);
    // ResizeObserver: viz-wrap grows after layout / mode switch
    if (typeof ResizeObserver !== "undefined") {
      const wrap = $("globe-wrap") || host;
      G.ro = new ResizeObserver(() => onResize());
      G.ro.observe(wrap);
    }

    function animate() {
      G.anim = requestAnimationFrame(animate);
      if (!G.dragging) {
        earth.rotation.y += 0.0008;
        wire.rotation.y += 0.0008;
        cellGroup.rotation.y += 0.0008;
      }
      renderer.render(scene, camera);
    }
    animate();
  }

  function parseColor(css) {
    const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(css || "");
    if (!m) return 0xb01030;
    return (parseInt(m[1], 10) << 16) + (parseInt(m[2], 10) << 8) + parseInt(m[3], 10);
  }

  function setLayer(layer) {
    const L = layer || "density";
    G.layer = L === "hazard" || L === "intensity" ? "radiation" : L;
    ["density", "radiation", "blend"].forEach((id) => {
      const btn = $(`btn-globe-${id}`);
      if (btn) btn.classList.toggle("primary", id === G.layer);
    });
    const info = $("globe-layer-info");
    if (info) {
      const labels = {
        density: "density thermal",
        radiation: "exposure (2D hazard on globe)",
        blend: "density + exposure",
      };
      info.textContent = labels[G.layer] || G.layer;
    }
    refresh();
  }

  function loadCells(data) {
    if (!G.cellGroup) return;
    while (G.cellGroup.children.length) {
      const c = G.cellGroup.children.pop();
      if (c.geometry) c.geometry.dispose();
      if (c.material) c.material.dispose();
    }
    const cells = data.cells || [];
    const layer = data.layer || G.layer || "density";
    for (const cell of cells) {
      const q = cell.quad;
      if (!q || q.length < 4) continue;
      const positions = new Float32Array([
        q[0][0], q[0][1], q[0][2],
        q[1][0], q[1][1], q[1][2],
        q[2][0], q[2][1], q[2][2],
        q[0][0], q[0][1], q[0][2],
        q[2][0], q[2][1], q[2][2],
        q[3][0], q[3][1], q[3][2],
      ]);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geo.computeVertexNormals();
      const op =
        cell.opacity != null
          ? Number(cell.opacity)
          : layer === "radiation"
            ? 0.75
            : 0.85;
      const mat = new THREE.MeshBasicMaterial({
        color: parseColor(cell.color),
        side: THREE.DoubleSide,
        transparent: true,
        opacity: Math.max(0.2, Math.min(1, op)),
        depthWrite: false,
      });
      G.cellGroup.add(new THREE.Mesh(geo, mat));
    }
    G.version = data.version || 0;
    const meta = data.meta || {};
    const solar = data.solar || {};
    const el = $("globe-meta");
    if (el) {
      const parts = [
        `cells ${meta.count_cells ?? cells.length}`,
        `v${G.version}`,
        layer,
      ];
      if (solar.base_score != null) {
        parts.push(`stress ${Number(solar.base_score).toFixed(0)}`);
      }
      if (solar.max_exposure != null && layer !== "density") {
        parts.push(`max exp ${Number(solar.max_exposure).toFixed(0)}`);
      }
      el.textContent = parts.join(" · ");
    }
    // soft ambient tint on earth for radiation layers
    if (G.earth && G.earth.material) {
      if (layer === "radiation" && solar.available !== false) {
        G.earth.material.emissive = new THREE.Color(0x1a0520);
        G.earth.material.color = new THREE.Color(0x0c1028);
      } else if (layer === "blend") {
        G.earth.material.emissive = new THREE.Color(0x100818);
        G.earth.material.color = new THREE.Color(0x0a1840);
      } else {
        G.earth.material.emissive = new THREE.Color(0x050812);
        G.earth.material.color = new THREE.Color(0x0a1840);
      }
    }
  }

  function sphereQuery() {
    const params = new URLSearchParams();
    params.set("layer", G.layer || "density");
    // reuse 2D filter state when available
    try {
      if (window.CynoberStudioState) {
        const st = window.CynoberStudioState;
        if (st.shell && st.shell !== "all") params.set("shell", st.shell);
        if (st.minCount) params.set("min_count", String(st.minCount));
      }
    } catch (_) {
      /* ignore */
    }
    return params.toString();
  }

  async function fetchSphere() {
    const q = sphereQuery();
    const resp = await fetch(`/api/sphere?${q}`);
    const j = await resp.json();
    if (j.status === "error") throw new Error(j.message || "sphere failed");
    return j.data;
  }

  async function refresh() {
    ensureThree(async () => {
      initScene();
      try {
        const data = await fetchSphere();
        if (data.layer) G.layer = data.layer;
        loadCells(data);
        const err = $("err");
        if (err) err.textContent = "";
      } catch (e) {
        const err = $("err");
        if (err) err.textContent = String(e.message || e);
      }
    });
  }

  function show(on) {
    const g = $("panel-globe");
    const h = $("panel-heatmap");
    if (g) g.style.display = on ? "" : "none";
    if (h) h.style.display = on ? "none" : "";
    if (on) {
      // sync 2D hazard → 3D radiation when user was on hazard layer
      try {
        if (window.CynoberStudioState && window.CynoberStudioState.layer === "hazard") {
          G.layer = "radiation";
        } else if (
          window.CynoberStudioState &&
          window.CynoberStudioState.layer === "blend"
        ) {
          G.layer = "blend";
        }
      } catch (_) {
        /* ignore */
      }
      // wait one frame so enlarged panel has real clientWidth/Height
      requestAnimationFrame(() => {
        setLayer(G.layer);
        window.dispatchEvent(new Event("resize"));
      });
    }
  }

  function wireGlobeLayers() {
    $("btn-globe-density")?.addEventListener("click", () => setLayer("density"));
    $("btn-globe-radiation")?.addEventListener("click", () => setLayer("radiation"));
    $("btn-globe-blend")?.addEventListener("click", () => setLayer("blend"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireGlobeLayers);
  } else {
    wireGlobeLayers();
  }

  function latLonToVec(lat, lon, r) {
    const phi = ((90 - lat) * Math.PI) / 180;
    const theta = ((lon + 180) * Math.PI) / 180;
    return new THREE.Vector3(
      -r * Math.sin(phi) * Math.cos(theta),
      r * Math.cos(phi),
      r * Math.sin(phi) * Math.sin(theta)
    );
  }

  function showDelta(delta) {
    ensureThree(() => {
      initScene();
      if (!G.cellGroup) return;
      while (G.cellGroup.children.length) {
        const c = G.cellGroup.children.pop();
        if (c.geometry) c.geometry.dispose();
        if (c.material) c.material.dispose();
      }
      const cells = (delta && delta.cells_changed) || [];
      const nlat = Number(delta.nlat) || 36;
      const nlon = Number(delta.nlon) || 72;
      const dlat = 180 / nlat;
      const dlon = 360 / nlon;
      const maxAbs = Math.max(
        1,
        ...cells.map((c) => Math.abs(Number(c.delta) || 0))
      );
      cells.forEach((c) => {
        const ilat = Number(c.ilat);
        const ilon = Number(c.ilon);
        if (!Number.isFinite(ilat) || !Number.isFinite(ilon)) return;
        const lat0 = -90 + ilat * dlat;
        const lon0 = -180 + ilon * dlon;
        const lat1 = lat0 + dlat;
        const lon1 = lon0 + dlon;
        const r = 1.02;
        const corners = [
          latLonToVec(lat0, lon0, r),
          latLonToVec(lat0, lon1, r),
          latLonToVec(lat1, lon1, r),
          latLonToVec(lat1, lon0, r),
        ];
        const positions = new Float32Array([
          corners[0].x, corners[0].y, corners[0].z,
          corners[1].x, corners[1].y, corners[1].z,
          corners[2].x, corners[2].y, corners[2].z,
          corners[0].x, corners[0].y, corners[0].z,
          corners[2].x, corners[2].y, corners[2].z,
          corners[3].x, corners[3].y, corners[3].z,
        ]);
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geo.computeVertexNormals();
        const dlt = Number(c.delta) || 0;
        const t = Math.min(1, Math.abs(dlt) / maxAbs);
        const up = c.kind === "appeared" || dlt > 0;
        const color = up
          ? new THREE.Color(0.15 + 0.2 * t, 0.75 + 0.2 * t, 0.35)
          : new THREE.Color(0.85 + 0.1 * t, 0.25, 0.3);
        const mat = new THREE.MeshBasicMaterial({
          color,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.5 + 0.45 * t,
          depthWrite: false,
        });
        G.cellGroup.add(new THREE.Mesh(geo, mat));
      });
      const el = $("globe-meta");
      if (el) {
        el.textContent = `delta · +${delta.appeared || 0} / −${delta.vanished || 0} · cells ${cells.length} · research`;
      }
      const info = $("globe-layer-info");
      if (info) info.textContent = "delta A→B (changes only)";
      G.layer = "delta";
    });
  }

  window.CynoberGlobe = {
    show,
    refresh,
    loadCells,
    setLayer,
    showDelta,
    getLayer: () => G.layer,
  };
})();
