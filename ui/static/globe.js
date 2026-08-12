/* Cynober Studio — S2b 3D globe (Three.js CDN)
 *
 * TODO (later): solar radiation intensity layer on globe quads
 * (same exposure proxy as 2D hazard, or X-ray/F10.7-driven tint).
 * Do not block 2D H2 work — density quads only for now.
 */
(() => {
  const $ = (id) => document.getElementById(id);

  const G = {
    renderer: null,
    scene: null,
    camera: null,
    earth: null,
    cellGroup: null,
    anim: null,
    ro: null,
    dragging: false,
    lastX: 0,
    lastY: 0,
    version: -1,
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

  function initScene() {
    const host = $("globe-host");
    if (!host || G.renderer) return;
    const w = host.clientWidth || 720;
    const h = Math.max(360, Math.floor(w * 0.55));
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x08060a);
    const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 100);
    camera.position.set(0, 0.35, 2.6);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h);
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

    // wireframe outline
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
    G.cellGroup = cellGroup;

    // drag rotate
    const el = renderer.domElement;
    el.style.cursor = "grab";
    el.addEventListener("pointerdown", (e) => {
      G.dragging = true;
      G.lastX = e.clientX;
      G.lastY = e.clientY;
      el.setPointerCapture(e.pointerId);
      el.style.cursor = "grabbing";
    });
    el.addEventListener("pointerup", (e) => {
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
      const ww = host.clientWidth || 720;
      const hh = Math.max(360, Math.floor(ww * 0.55));
      camera.aspect = ww / hh;
      camera.updateProjectionMatrix();
      renderer.setSize(ww, hh);
    }
    window.addEventListener("resize", onResize);

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
    // rgb(r,g,b)
    const m = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(css || "");
    if (!m) return 0xb01030;
    return (parseInt(m[1]) << 16) + (parseInt(m[2]) << 8) + parseInt(m[3]);
  }

  function loadCells(data) {
    if (!G.cellGroup) return;
    while (G.cellGroup.children.length) {
      const c = G.cellGroup.children.pop();
      if (c.geometry) c.geometry.dispose();
      if (c.material) c.material.dispose();
    }
    const cells = data.cells || [];
    for (const cell of cells) {
      const q = cell.quad;
      if (!q || q.length < 4) continue;
      // two triangles: 0-1-2 and 0-2-3
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
      const mat = new THREE.MeshBasicMaterial({
        color: parseColor(cell.color),
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.85,
      });
      G.cellGroup.add(new THREE.Mesh(geo, mat));
    }
    G.version = data.version || 0;
    const meta = data.meta || {};
    const el = $("globe-meta");
    if (el) {
      el.textContent = `cells ${meta.count_cells ?? cells.length} · v${G.version}`;
    }
  }

  async function fetchSphere() {
    const resp = await fetch("/api/sphere");
    const j = await resp.json();
    if (j.status === "error") throw new Error(j.message || "sphere failed");
    return j.data;
  }

  async function refresh() {
    ensureThree(async () => {
      initScene();
      try {
        const data = await fetchSphere();
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
    if (on) refresh();
  }

  window.CynoberGlobe = { show, refresh, loadCells };
})();
