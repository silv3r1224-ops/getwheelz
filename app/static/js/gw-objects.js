/* GW3D: workshop equipment as live ASCII / pixel art.
   Procedural three.js models (no asset files) are rendered into a tiny buffer, then every cell of that buffer is
   re-drawn on a 2D canvas as a glyph (ASCII) or a dithered square (PIXEL). Effects: decode-in reveal, a scanning
   sweep, cursor glitch, drag-to-rotate with inertia, parallax toward the pointer.

   Usage
     GW3D.mount(el, { object: 'wrench', mode: 'ascii' | 'pixel', onchange(meta, index, total) {} })  -> controller
        controller.setObject(id) / setMode(mode) / destroy()
     or declaratively:  <div data-gw-object="engine" data-gw-mode="pixel"></div>   (give it a height in CSS)
     Add data-gw-manual to an element you mount yourself. Optional: data-gw-cols="90", data-gw-spin="off".
   three.js is fetched lazily from unpkg (the only script CDN the site's CSP allows) the first time something mounts. */
(() => {
  'use strict';

  const THREE_SRC = 'https://unpkg.com/three@0.152.2/build/three.min.js';
  let threePromise = null;
  function loadThree() {
    if (window.THREE) return Promise.resolve(window.THREE);
    if (!threePromise) {
      threePromise = new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = THREE_SRC; s.crossOrigin = 'anonymous';
        s.onload = () => (window.THREE ? resolve(window.THREE) : reject(new Error('three missing')));
        s.onerror = () => reject(new Error('three failed to load'));
        document.head.appendChild(s);
      });
    }
    return threePromise;
  }

  /* ------------------------------------------------------------------ catalogue */
  const META = [
    { id: 'wrench',   name: 'Combination wrench', spec: 'Ring end + open end' },
    { id: 'engine',   name: 'Inline-4 engine',    spec: 'Four pistons, live' },
    { id: 'gears',    name: 'Gear train',         spec: '20T : 12T, 5:3 ratio' },
    { id: 'brake',    name: 'Brake rotor',        spec: 'Cross-drilled + caliper' },
    { id: 'wheel',    name: 'Alloy wheel',        spec: '10 spoke, low profile' },
    { id: 'turbo',    name: 'Turbocharger',       spec: 'Compressor + turbine' },
    { id: 'coilover', name: 'Coilover',           spec: 'Adjustable ride height' },
    { id: 'spark',    name: 'Spark plug',         spec: 'Live spark gap' }
  ];

  /* ------------------------------------------------------------------ models */
  /* Each factory returns { group, tilt:{x,y,z}, update(t, dt) }. Animate child nodes only (never the root),
     because the root is re-centred after measuring its bounding box. */
  function makeModels(THREE) {
    const STEEL = 0xd5dae2, IRON = 0x8d939e, DARK = 0x4b505a, CORAL = 0xee6b61, BRASS = 0xdcb870, WHITE = 0xf1f1ee;
    const phong = (color, o) => new THREE.MeshPhongMaterial(Object.assign({ color, shininess: 55, specular: 0x777777, flatShading: true }, o || {}));
    const mesh = (geo, mat, x, y, z) => { const m = new THREE.Mesh(geo, mat); m.position.set(x || 0, y || 0, z || 0); return m; };
    const extrude = (shape, depth, bevel) => {
      const b = bevel === undefined ? 0.03 : bevel;
      const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: true, bevelThickness: b, bevelSize: b, bevelSegments: 1, curveSegments: 12 });
      g.translate(0, 0, -depth / 2);
      return g;
    };
    const circlePath = (cx, cy, r) => { const p = new THREE.Path(); p.absarc(cx, cy, r, 0, Math.PI * 2, true); return p; };

    /* ---- wrench: tapered handle, hex ring end, slotted open end ---- */
    function wrench() {
      const g = new THREE.Group(), sway = new THREE.Group(); g.add(sway);
      const steel = phong(STEEL), coral = phong(CORAL);
      const L = 5.2, D = 0.3;
      const hs = new THREE.Shape();
      hs.moveTo(-L / 2, -0.3); hs.lineTo(L / 2, -0.22); hs.lineTo(L / 2, 0.22); hs.lineTo(-L / 2, 0.3); hs.closePath();
      sway.add(mesh(extrude(hs, D * 0.9, 0.03), steel));
      sway.add(mesh(new THREE.BoxGeometry(L * 0.5, 0.1, D * 0.9 + 0.06), coral, 0, 0, 0));

      const ring = new THREE.Shape();
      ring.absarc(0, 0, 0.8, 0, Math.PI * 2, false);
      const hole = new THREE.Path();
      for (let i = 0; i < 6; i++) { const a = (i / 6) * Math.PI * 2, x = 0.46 * Math.cos(a), y = 0.46 * Math.sin(a); if (i) hole.lineTo(x, y); else hole.moveTo(x, y); }
      hole.closePath(); ring.holes.push(hole);
      sway.add(mesh(extrude(ring, D, 0.04), steel, -L / 2 - 0.38, 0, 0));

      const r = 0.74, w = 0.34, a0 = Math.asin(w / r);
      const open = new THREE.Shape();
      open.moveTo(r * Math.cos(a0), w);
      for (let k = 1; k <= 24; k++) { const a = a0 + (Math.PI * 2 - 2 * a0) * (k / 24); open.lineTo(r * Math.cos(a), r * Math.sin(a)); }
      open.lineTo(-0.05, -w); open.lineTo(-0.05, w); open.closePath();
      const head = mesh(extrude(open, D, 0.04), steel, L / 2 + 0.45, 0, 0);
      head.rotation.z = 0.26;
      sway.add(head);
      return { group: g, tilt: { x: 0, y: 0, z: 0.42 }, update: t => { sway.rotation.z = Math.sin(t * 1.2) * 0.08; } };
    }

    /* ---- gear train: two meshing involute-ish gears ---- */
    function gearShape(n, ro, rr, hole, spokes) {
      const s = new THREE.Shape(), p = (Math.PI * 2) / n;
      for (let i = 0; i < n; i++) {
        const b = i * p - 0.3 * p;                                   // tooth centre sits on angle i*p
        [[b, rr], [b + 0.16 * p, ro], [b + 0.44 * p, ro], [b + 0.6 * p, rr]].forEach(([a, r], j) => {
          const x = r * Math.cos(a), y = r * Math.sin(a);
          if (i === 0 && j === 0) s.moveTo(x, y); else s.lineTo(x, y);
        });
      }
      s.closePath();
      s.holes.push(circlePath(0, 0, hole));
      for (let k = 0; k < spokes; k++) { const a = (k / spokes) * Math.PI * 2; s.holes.push(circlePath(Math.cos(a) * ro * 0.58, Math.sin(a) * ro * 0.58, ro * 0.17)); }
      return s;
    }
    function gears() {
      const g = new THREE.Group();
      const g1 = new THREE.Group(), g2 = new THREE.Group();
      g1.add(mesh(extrude(gearShape(20, 1.5, 1.26, 0.34, 5), 0.5, 0.03), phong(STEEL)));
      g1.add(mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.8, 16).rotateX(Math.PI / 2), phong(IRON)));
      g2.add(mesh(extrude(gearShape(12, 0.95, 0.72, 0.22, 0), 0.5, 0.03), phong(CORAL)));
      g2.add(mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.8, 12).rotateX(Math.PI / 2), phong(IRON)));
      g2.position.x = 2.215;
      g.add(g1, g2);
      return { group: g, tilt: { x: 0.5, y: -0.3, z: 0 }, update: t => { const th = t * 0.9; g1.rotation.z = th; g2.rotation.z = Math.PI / 12 - th * (20 / 12); } };
    }

    /* ---- brake rotor with drilled holes and a caliper ---- */
    function brake() {
      const g = new THREE.Group(), disc = new THREE.Group(); g.add(disc);
      const s = new THREE.Shape(); s.absarc(0, 0, 1.55, 0, Math.PI * 2, false);
      s.holes.push(circlePath(0, 0, 0.62));
      [[10, 1.0], [14, 1.3]].forEach(([n, rad], ri) => {
        for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2 + ri * 0.2; s.holes.push(circlePath(Math.cos(a) * rad, Math.sin(a) * rad, 0.075)); }
      });
      disc.add(mesh(extrude(s, 0.2, 0.02), phong(STEEL)));
      disc.add(mesh(new THREE.CylinderGeometry(0.8, 0.8, 0.46, 24).rotateX(Math.PI / 2), phong(IRON), 0, 0, -0.1));
      disc.add(mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.62, 16).rotateX(Math.PI / 2), phong(DARK), 0, 0, -0.1));
      for (let i = 0; i < 5; i++) { const a = (i / 5) * Math.PI * 2; disc.add(mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.7, 6).rotateX(Math.PI / 2), phong(STEEL), Math.cos(a) * 0.5, Math.sin(a) * 0.5, -0.1)); }
      const c = new THREE.Shape();
      c.absarc(0, 0, 1.8, -0.5, 0.5, false);
      c.absarc(0, 0, 1.05, 0.5, -0.5, true);
      c.closePath();
      g.add(mesh(extrude(c, 0.8, 0.04), phong(CORAL, { shininess: 30 })));
      g.add(mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.3, 8), phong(STEEL), 1.55, 0.7, 0));
      return { group: g, tilt: { x: 0.15, y: 0, z: 0 }, update: t => { disc.rotation.z = t * 1.6; } };
    }

    /* ---- alloy wheel + tyre ---- */
    function wheel() {
      const g = new THREE.Group(), spin = new THREE.Group(); g.add(spin);
      const tire = new THREE.TorusGeometry(1.3, 0.5, 10, 30); tire.scale(1, 1, 0.85);
      spin.add(mesh(tire, phong(0x2b2e35, { shininess: 10 })));
      const tread = new THREE.BoxGeometry(0.2, 0.22, 0.62), treadMat = phong(0x3d414a, { shininess: 8 });
      for (let i = 0; i < 30; i++) { const a = (i / 30) * Math.PI * 2, m = mesh(tread, treadMat, Math.cos(a) * 1.8, Math.sin(a) * 1.8, 0); m.rotation.z = a; spin.add(m); }
      const barrel = new THREE.CylinderGeometry(1.0, 1.0, 0.78, 28, 1, true).rotateX(Math.PI / 2);
      spin.add(mesh(barrel, phong(IRON, { side: THREE.DoubleSide })));
      [-0.39, 0.39].forEach((z, i) => spin.add(mesh(new THREE.TorusGeometry(1.0, 0.06, 6, 28), phong(i ? CORAL : STEEL), 0, 0, z)));
      for (let i = 0; i < 10; i++) {
        const a = (i / 10) * Math.PI * 2, m = mesh(new THREE.BoxGeometry(0.2, 0.9, 0.14), phong(i % 2 ? STEEL : 0xbfc5ce), Math.cos(a) * 0.62, Math.sin(a) * 0.62, 0.08);
        m.rotation.z = a - Math.PI / 2; spin.add(m);
      }
      spin.add(mesh(new THREE.CylinderGeometry(0.36, 0.36, 0.5, 16).rotateX(Math.PI / 2), phong(STEEL), 0, 0, 0.1));
      spin.add(mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.14, 12).rotateX(Math.PI / 2), phong(CORAL), 0, 0, 0.38));
      for (let i = 0; i < 5; i++) { const a = (i / 5) * Math.PI * 2; spin.add(mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.18, 6).rotateX(Math.PI / 2), phong(DARK), Math.cos(a) * 0.25, Math.sin(a) * 0.25, 0.36)); }
      return { group: g, tilt: { x: 0.1, y: 0.5, z: 0 }, update: t => { spin.rotation.z = -t * 1.4; } };
    }

    /* ---- turbocharger: volute, turbine housing and a spinning impeller ---- */
    function turbo() {
      const g = new THREE.Group();
      const steel = phong(STEEL), iron = phong(IRON), dark = phong(DARK), coral = phong(CORAL);
      g.add(mesh(new THREE.TorusGeometry(0.78, 0.34, 10, 28), steel, 0, 0, 0.55));
      g.add(mesh(new THREE.CylinderGeometry(1.05, 1.05, 0.18, 28).rotateX(Math.PI / 2), iron, 0, 0, 0.2));
      g.add(mesh(new THREE.CylinderGeometry(0.5, 0.8, 0.8, 24, 1, true).rotateX(Math.PI / 2), phong(STEEL, { side: THREE.DoubleSide }), 0, 0, 0.95));
      g.add(mesh(new THREE.CylinderGeometry(0.24, 0.24, 1.3, 12).rotateZ(Math.PI / 2), steel, 0.75, -0.78, 0.55));
      g.add(mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.1, 12).rotateZ(Math.PI / 2), coral, 1.42, -0.78, 0.55));
      g.add(mesh(new THREE.CylinderGeometry(0.42, 0.42, 1.0, 16).rotateX(Math.PI / 2), iron, 0, 0, -0.25));
      g.add(mesh(new THREE.TorusGeometry(0.44, 0.05, 6, 16), coral, 0, 0, -0.25));
      g.add(mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.5, 8), dark, 0, 0.62, -0.2));
      g.add(mesh(new THREE.TorusGeometry(0.9, 0.38, 10, 28), dark, 0, 0, -1.0));
      g.add(mesh(new THREE.CylinderGeometry(0.8, 0.5, 0.9, 24, 1, true).rotateX(Math.PI / 2), phong(DARK, { side: THREE.DoubleSide }), 0, 0, -1.75));
      const imp = new THREE.Group(); imp.position.z = 0.65; g.add(imp);
      for (let i = 0; i < 11; i++) {
        const piv = new THREE.Group(); piv.rotation.z = (i / 11) * Math.PI * 2;
        const blade = mesh(new THREE.BoxGeometry(0.55, 0.035, 0.3), phong(BRASS), 0.34, 0, 0); blade.rotation.x = 0.55;
        piv.add(blade); imp.add(piv);
      }
      imp.add(mesh(new THREE.ConeGeometry(0.17, 0.35, 12).rotateX(Math.PI / 2), phong(STEEL), 0, 0, 0.25));
      return { group: g, tilt: { x: -0.15, y: 0.45, z: 0 }, update: t => { imp.rotation.z = -t * 12; } };
    }

    /* ---- coilover: damper, adjuster collar and a breathing spring ---- */
    function coilover() {
      const g = new THREE.Group();
      const BASE = -1.3, SEAT = BASE + 1.2, SPRING_H = 2.1;
      g.add(mesh(new THREE.CylinderGeometry(0.32, 0.32, 2.2, 16), phong(DARK), 0, BASE + 1.1, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.28, 16), phong(CORAL), 0, BASE + 0.5, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.12, 16), phong(IRON), 0, BASE + 0.82, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.1, 24), phong(IRON), 0, SEAT - 0.05, 0));
      g.add(mesh(new THREE.TorusGeometry(0.28, 0.09, 6, 14), phong(STEEL), 0, BASE - 0.1, 0));
      g.add(mesh(new THREE.BoxGeometry(0.2, 0.32, 0.5), phong(IRON), 0, BASE + 0.12, 0));

      class Helix extends THREE.Curve {
        getPoint(t, target) { const a = t * 9 * Math.PI * 2; return (target || new THREE.Vector3()).set(0.62 * Math.cos(a), t * SPRING_H, 0.62 * Math.sin(a)); }
      }
      const spring = mesh(new THREE.TubeGeometry(new Helix(), 9 * 14, 0.06, 6, false), phong(STEEL), 0, SEAT, 0);
      g.add(spring);

      const top = new THREE.Group(); g.add(top);
      top.add(mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.1, 24), phong(IRON), 0, 0.05, 0));
      top.add(mesh(new THREE.CylinderGeometry(0.5, 0.62, 0.35, 16), phong(CORAL), 0, 0.28, 0));
      top.add(mesh(new THREE.CylinderGeometry(0.1, 0.1, 2.3, 10), phong(STEEL), 0, -1.1, 0));
      return {
        group: g, tilt: { x: 0.1, y: 0, z: 0.12 },
        update: t => { const H = SPRING_H + 0.28 * Math.sin(t * 2.2); top.position.y = SEAT + H; spring.scale.y = H / SPRING_H; }
      };
    }

    /* ---- spark plug with a flickering arc ---- */
    function spark() {
      const g = new THREE.Group();
      for (let i = 0; i < 9; i++) g.add(mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.09, 12), phong(i % 2 ? IRON : STEEL), 0, 0.06 + i * 0.1, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.46, 0.46, 0.45, 6), phong(STEEL), 0, 1.2, 0));
      const prof = [[0.2, 1.42], [0.3, 1.5], [0.3, 1.9], [0.34, 1.95], [0.34, 2.05], [0.3, 2.1], [0.3, 2.4], [0.34, 2.45], [0.34, 2.55], [0.3, 2.6], [0.3, 3.0], [0.2, 3.1], [0.2, 3.2]].map(([x, y]) => new THREE.Vector2(x, y));
      g.add(mesh(new THREE.LatheGeometry(prof, 20), phong(WHITE, { shininess: 90 })));
      g.add(mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.45, 8), phong(STEEL), 0, 3.45, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.12, 8), phong(IRON), 0, 3.7, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.45, 6), phong(BRASS), 0, -0.18, 0));
      g.add(mesh(new THREE.BoxGeometry(0.08, 0.64, 0.1), phong(IRON), 0.27, -0.32, 0));
      g.add(mesh(new THREE.BoxGeometry(0.29, 0.08, 0.1), phong(IRON), 0.125, -0.6, 0));
      const pts = new Float32Array(7 * 3);
      const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pts, 3));
      const arc = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xffffff })); arc.frustumCulled = false; g.add(arc);
      const glow = mesh(new THREE.SphereGeometry(0.12, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffffff }), 0.02, -0.48, 0); g.add(glow);
      return {
        group: g, tilt: { x: 0.1, y: 0, z: 0.25 },
        update: t => {
          const pos = geo.attributes.position, on = Math.sin(t * 17) + Math.sin(t * 29 + 1) > -0.7;
          arc.visible = on; glow.visible = on; glow.scale.setScalar(0.7 + 0.6 * Math.abs(Math.sin(t * 41)));
          for (let i = 0; i < 7; i++) { const k = i / 6, j = i === 0 || i === 6 ? 0 : 0.07; pos.setXYZ(i, 0.02 * k + (Math.random() - 0.5) * j, -0.405 - 0.155 * k, (Math.random() - 0.5) * j); }
          pos.needsUpdate = true;
        }
      };
    }

    /* ---- inline-4 engine with a real slider-crank (pistons and rods are driven by the crank angle) ---- */
    function engine() {
      const g = new THREE.Group();
      const steel = phong(STEEL), dark = phong(DARK), iron = phong(IRON), coral = phong(CORAL, { shininess: 30 });
      const X = [-1.275, -0.425, 0.425, 1.275], R = 0.28, LR = 0.95, PH = [0, Math.PI, Math.PI, 0], SPEED = 3.2;
      const add = (geo, m, x, y, z) => { const o = mesh(geo, m, x, y, z); g.add(o); return o; };

      add(new THREE.BoxGeometry(4.0, 0.7, 1.5), dark, 0, -0.75, 0);
      [-2.15, 2.15].forEach(x => add(new THREE.BoxGeometry(0.12, 1.1, 1.5), iron, x, -0.2, 0));
      [-0.85, 0, 0.85].forEach(x => add(new THREE.BoxGeometry(0.16, 0.5, 1.2), iron, x, -0.2, 0));
      const wire = new THREE.MeshBasicMaterial({ color: 0xaab0ba, wireframe: true });
      X.forEach(x => add(new THREE.CylinderGeometry(0.42, 0.42, 1.5, 12, 3, true), wire, x, 1.05, 0));
      add(new THREE.BoxGeometry(4.0, 0.45, 1.45), steel, 0, 2.02, 0);
      add(new THREE.BoxGeometry(3.6, 0.3, 0.95), coral, 0, 2.4, 0);
      X.forEach(x => { add(new THREE.CylinderGeometry(0.09, 0.09, 0.55, 8), phong(WHITE), x, 2.8, 0); add(new THREE.CylinderGeometry(0.14, 0.14, 0.12, 8), dark, x, 3.1, 0); });
      add(new THREE.CylinderGeometry(0.34, 0.34, 3.8, 16).rotateZ(Math.PI / 2), steel, 0, 2.05, 1.55);
      X.forEach(x => add(new THREE.CylinderGeometry(0.13, 0.13, 0.9, 10).rotateX(Math.PI / 2), steel, x, 2.05, 1.1));
      add(new THREE.BoxGeometry(3.4, 0.25, 0.35), dark, 0, 1.9, -1.0);
      X.forEach(x => add(new THREE.CylinderGeometry(0.11, 0.11, 0.6, 8).rotateX(Math.PI / 2), dark, x, 1.9, -0.8));

      const shaft = new THREE.Group(); g.add(shaft);
      shaft.add(mesh(new THREE.CylinderGeometry(0.14, 0.14, 4.8, 12).rotateZ(Math.PI / 2), steel));
      shaft.add(mesh(new THREE.CylinderGeometry(0.55, 0.55, 0.3, 20).rotateZ(Math.PI / 2), iron, -2.55, 0, 0));
      shaft.add(mesh(new THREE.BoxGeometry(0.34, 0.1, 0.5), coral, -2.55, 0.5, 0));
      shaft.add(mesh(new THREE.CylinderGeometry(0.85, 0.85, 0.3, 28).rotateZ(Math.PI / 2), dark, 2.55, 0, 0));
      shaft.add(mesh(new THREE.BoxGeometry(0.34, 0.1, 0.5), coral, 2.55, 0.7, 0));

      const throws = [], pistons = [], rods = [];
      X.forEach((x, i) => {
        const t = new THREE.Group(); t.position.x = x; g.add(t);
        t.add(mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.4, 10).rotateZ(Math.PI / 2), steel, 0, R, 0));
        [-0.2, 0.2].forEach(dx => t.add(mesh(new THREE.BoxGeometry(0.09, R + 0.5, 0.34), iron, dx, R / 2, 0)));
        throws.push(t);
        const p = new THREE.Group(); p.position.x = x; g.add(p);
        p.add(mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.5, 16), steel, 0, 0.2, 0));
        [0.28, 0.36].forEach(y => p.add(mesh(new THREE.TorusGeometry(0.34, 0.025, 4, 16).rotateX(Math.PI / 2), dark, 0, y, 0)));
        p.add(mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.5, 8).rotateZ(Math.PI / 2), dark, 0, 0, 0));
        pistons.push(p);
        const rod = mesh(new THREE.BoxGeometry(0.14, LR, 0.12), phong(IRON), x, 0, 0); g.add(rod); rods.push(rod);
      });

      return {
        group: g, tilt: { x: 0.25, y: 0, z: 0 },
        update: t => {
          shaft.rotation.x = t * SPEED;
          for (let i = 0; i < 4; i++) {
            const phi = t * SPEED + PH[i], py = R * Math.cos(phi) + Math.sqrt(LR * LR - Math.pow(R * Math.sin(phi), 2));
            throws[i].rotation.x = phi;
            pistons[i].position.y = py;
            const pinY = R * Math.cos(phi), pinZ = R * Math.sin(phi);
            rods[i].position.set(X[i], (py + pinY) / 2, pinZ / 2);               // midpoint between crank pin and piston pin (z = 0)
            rods[i].rotation.x = Math.atan2(-pinZ, py - pinY);
          }
        }
      };
    }

    return { wrench, engine, gears, brake, wheel, turbo, coilover, spark };
  }

  /* ------------------------------------------------------------------ renderer */
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const hash = (x, y) => { const n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return n - Math.floor(n); };
  const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  const RAMP = ' .:-=+*#%@';
  const GLITCH = '01<>/\\|[]{}';
  const ATLAS = RAMP + GLITCH;
  const ASCII_COLORS = ['rgba(139,230,223,.38)', '#8be6df', '#ff9584', '#ffffff', '#d7f36b'];
  const PIXEL_PALETTE = ['#101216', '#33222c', '#7d3643', '#ee6b61', '#ff9584', '#fff3ea'];

  function mount(el, userOpts) {
    const ds = el.dataset;
    const o = Object.assign({ object: 'wrench', mode: 'ascii', cols: 0, spin: true, interactive: true, onchange: null }, userOpts || {});
    if (ds.gwObject) o.object = ds.gwObject;
    if (ds.gwMode) o.mode = ds.gwMode;
    if (ds.gwCols) o.cols = parseInt(ds.gwCols, 10) || 0;
    if (ds.gwSpin === 'off') o.spin = false;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { o.spin = false; o.interactive = false; }

    const canvas = document.createElement('canvas');
    canvas.className = 'gw-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    el.appendChild(canvas);
    const ctx = canvas.getContext('2d');
    el.dataset.gwMode = o.mode;

    let THREE = null, renderer, scene, camera, models, sctx, sampler;
    let spinner, tilt, current = null, atlas = [];
    let W = 0, H = 0, dpr = 1, cols = 0, rows = 0, cw = 0, ch = 0, gw = 0, gh = 0;
    let ready = false, dead = false, visible = true, raf = 0, dirty = true;
    let time = 0, last = 0, lastDraw = 0, reveal = 0, state = 'in', queue = null;
    let yaw = 0, pitch = 0, vYaw = 0, vPitch = 0, px = 0.5, py = 0.5, tYaw = 0, tPitch = 0;
    let dragging = false, dragX = 0, dragY = 0, hover = false, pcx = -99, pcy = -99;

    /* ---------- model management ---------- */
    function disposeNode(n) { n.traverse(c => { if (c.geometry) c.geometry.dispose(); if (c.material) (Array.isArray(c.material) ? c.material : [c.material]).forEach(m => m.dispose()); }); }
    function build(id) {
      const factory = models[id] || models.wrench;
      const m = factory();
      const box = new THREE.Box3().setFromObject(m.group);
      const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
      const holder = new THREE.Group(), offset = new THREE.Group();
      offset.position.copy(c).negate(); offset.add(m.group);
      holder.add(offset);
      holder.scale.setScalar(4.7 / Math.max(size.x, size.y, size.z, 0.001));
      return { id, holder, m };
    }
    function swapObject(id) {
      if (current) { tilt.remove(current.holder); disposeNode(current.holder); }
      current = build(id);
      tilt.rotation.set(current.m.tilt.x || 0, current.m.tilt.y || 0, current.m.tilt.z || 0);
      tilt.add(current.holder);
      o.object = id;
      const i = Math.max(0, META.findIndex(x => x.id === id));
      el.dataset.gwObject = id;
      if (o.onchange) o.onchange(META[i], i, META.length);
    }

    /* ---------- layout ---------- */
    function layout() {
      if (!ready) return;
      const r = el.getBoundingClientRect();
      W = Math.max(40, r.width); H = Math.max(40, r.height);
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      if (o.mode === 'ascii') {
        cols = o.cols || clamp(Math.round(W / 8), 44, 150);
        cw = W / cols; ch = cw * 2; rows = Math.max(8, Math.floor(H / ch)); ch = H / rows;
      } else {
        cols = o.cols || clamp(Math.round(W / 6), 60, 220);
        cw = W / cols; ch = cw; rows = Math.max(8, Math.ceil(H / ch));
      }
      renderer.setSize(cols, rows, false);
      camera.aspect = W / H; camera.updateProjectionMatrix();
      sampler.width = cols; sampler.height = rows;
      if (o.mode === 'ascii') buildAtlas();
      el.dataset.gwGrid = cols + '\u00d7' + rows;
      dirty = true;
    }
    function buildAtlas() {
      gw = Math.max(2, Math.ceil(cw * dpr)); gh = Math.max(2, Math.ceil(ch * dpr));
      const font = Math.min(ch * 0.9, (cw / 0.6) * 0.98) * dpr;
      atlas = ASCII_COLORS.map(color => {
        const c = document.createElement('canvas'); c.width = gw * ATLAS.length; c.height = gh;
        const x = c.getContext('2d');
        x.font = `700 ${font}px ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace`;
        x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillStyle = color;
        for (let i = 1; i < ATLAS.length; i++) x.fillText(ATLAS[i], i * gw + gw / 2, gh / 2 + font * 0.04);
        return c;
      });
    }

    /* ---------- drawing ---------- */
    function draw(data) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const rv = reveal * 1.12, ascii = o.mode === 'ascii';
      const sweep = ((time * 0.32) % 1.7) - 0.35, R = 7, R2 = R * R, aspect = ch / cw;
      let lastFill = '';
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          const i = (y * cols + x) * 4;
          let lum = (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) / 255;
          if (lum < 0.045) continue;
          const nx = x / cols - 0.5, ny = (y / rows - 0.5) * (H / W);
          const thr = hash(x, y) * 0.6 + Math.min(1, Math.sqrt(nx * nx + ny * ny) * 1.6) * 0.4;
          if (thr > rv) continue;
          const edge = reveal < 1 && rv - thr < 0.08;
          lum = clamp((lum - 0.04) * 1.35);
          const sd = (y / rows - sweep) * 7; lum = clamp(lum + 0.32 * Math.exp(-sd * sd));
          let near = 0;
          if (hover && !reduce) { const dx = x - pcx, dy = (y - pcy) * aspect, d2 = dx * dx + dy * dy; if (d2 < R2) near = 1 - Math.sqrt(d2) / R; }
          if (near) lum = clamp(lum + near * 0.45);
          if (ascii) {
            let idx = clamp(Math.round(lum * (RAMP.length - 1)), 1, RAMP.length - 1), b = lum < 0.3 ? 0 : lum < 0.58 ? 1 : lum < 0.82 ? 2 : 3;
            if (edge) { idx = RAMP.length + Math.floor(Math.random() * GLITCH.length); b = 4; }
            else if (near && Math.random() < near * 0.5) idx = RAMP.length + Math.floor(Math.random() * GLITCH.length);
            ctx.drawImage(atlas[b], idx * gw, 0, gw, gh, x * cw, y * ch, cw, ch);
          } else {
            const lv = PIXEL_PALETTE.length - 1, v = lum * lv + (BAYER[(y & 3) * 4 + (x & 3)] / 16 - 0.5) * 0.9 + 0.5;
            const fill = edge ? '#ffffff' : PIXEL_PALETTE[clamp(Math.floor(v), 0, lv)];
            if (fill !== lastFill) { ctx.fillStyle = fill; lastFill = fill; }
            ctx.fillRect(x * cw, y * ch, cw + 0.6, ch + 0.6);
          }
        }
      }
    }

    /* ---------- loop ---------- */
    function frame(now) {
      raf = 0;
      if (dead || !ready) return;
      if (!visible || document.hidden) { last = 0; return; }
      const needs = !reduce || dirty || state !== 'in' || reveal < 1;
      if (!needs) { raf = requestAnimationFrame(frame); return; }
      if (now - lastDraw < 32) { raf = requestAnimationFrame(frame); return; }      // ~30 fps keeps it light
      const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016); last = now; lastDraw = now;
      if (!reduce) time += dt;

      if (reduce) { reveal = 1; state = 'in'; if (queue) applyQueue(); }
      else if (state === 'out') { reveal -= dt / 0.38; if (reveal <= 0) { reveal = 0; applyQueue(); state = 'in'; } }
      else if (reveal < 1) reveal = Math.min(1, reveal + dt / 1.1);

      if (o.spin && !dragging) yaw += dt * 0.45;
      if (!dragging) { yaw += vYaw; pitch += vPitch; vYaw *= 0.94; vPitch *= 0.94; }
      if (o.interactive && !dragging) { tYaw += ((px - 0.5) * 0.7 - tYaw) * 0.06; tPitch += ((py - 0.5) * 0.35 - tPitch) * 0.06; }
      pitch = clamp(pitch, -0.9, 0.9);
      spinner.rotation.y = yaw + tYaw;
      spinner.rotation.x = pitch + tPitch;
      if (current) current.m.update(reduce ? 0.6 : time, dt);

      renderer.render(scene, camera);
      sctx.drawImage(renderer.domElement, 0, 0);
      draw(sctx.getImageData(0, 0, cols, rows).data);
      dirty = false;
      raf = requestAnimationFrame(frame);
    }
    const kick = () => { dirty = true; if (!raf && ready && !dead) raf = requestAnimationFrame(frame); };
    function applyQueue() {
      if (!queue) return;
      const q = queue; queue = null;
      if (q.mode && q.mode !== o.mode) { o.mode = q.mode; el.dataset.gwMode = o.mode; layout(); }
      if (q.object && q.object !== o.object) swapObject(q.object);
    }
    function request(q) {
      queue = Object.assign(queue || {}, q);
      if (!ready) { if (q.object) o.object = q.object; if (q.mode) { o.mode = q.mode; el.dataset.gwMode = q.mode; } queue = null; return; }
      if (reduce) { applyQueue(); reveal = 1; kick(); return; }
      state = 'out'; kick();
    }

    /* ---------- pointer ---------- */
    const onMove = e => {
      const r = el.getBoundingClientRect();
      px = clamp((e.clientX - r.left) / r.width); py = clamp((e.clientY - r.top) / r.height);
      pcx = (e.clientX - r.left) / cw; pcy = (e.clientY - r.top) / ch; hover = true;
      if (dragging) {
        const dx = e.clientX - dragX, dy = e.clientY - dragY; dragX = e.clientX; dragY = e.clientY;
        vYaw = dx * 0.0045; vPitch = dy * 0.003; yaw += vYaw; pitch += vPitch;
      }
    };
    const onDown = e => { if (!o.interactive || (e.pointerType === 'mouse' && e.button !== 0)) return; dragging = true; dragX = e.clientX; dragY = e.clientY; el.classList.add('is-dragging'); try { el.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ } };
    const onUp = () => { dragging = false; el.classList.remove('is-dragging'); };
    const onLeave = () => { hover = false; px = 0.5; py = 0.5; };
    if (o.interactive) {
      el.addEventListener('pointermove', onMove); el.addEventListener('pointerdown', onDown);
      el.addEventListener('pointerup', onUp); el.addEventListener('pointercancel', onUp); el.addEventListener('pointerleave', onLeave);
    }

    /* ---------- boot ---------- */
    const io = new IntersectionObserver(es => { visible = es[0].isIntersecting; if (visible) { last = 0; kick(); } });
    io.observe(el);
    let ro = null;
    const api = {
      el, get meta() { return META.find(m => m.id === o.object); },
      setObject(id) { if (id !== o.object || queue) request({ object: id }); },
      setMode(mode) { if (mode !== o.mode || queue) request({ mode }); },
      destroy() {
        dead = true; cancelAnimationFrame(raf); io.disconnect(); if (ro) ro.disconnect();
        el.removeEventListener('pointermove', onMove); el.removeEventListener('pointerdown', onDown);
        el.removeEventListener('pointerup', onUp); el.removeEventListener('pointercancel', onUp); el.removeEventListener('pointerleave', onLeave);
        if (current) disposeNode(current.holder);
        if (renderer) { renderer.dispose(); const gl = renderer.getContext && renderer.getContext(); const ext = gl && gl.getExtension && gl.getExtension('WEBGL_lose_context'); if (ext) ext.loseContext(); }
        canvas.remove();
      }
    };

    loadThree().then(T => {
      if (dead) return;
      THREE = T; models = makeModels(THREE);
      renderer = new THREE.WebGLRenderer({ antialias: false, alpha: false, powerPreference: 'low-power' });
      renderer.setPixelRatio(1); renderer.setClearColor(0x000000, 1);
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100); camera.position.set(0, 0, 10);
      scene.add(new THREE.AmbientLight(0xffffff, 0.5));
      const key = new THREE.DirectionalLight(0xffffff, 1.0); key.position.set(3, 4, 6); scene.add(key);
      const fill = new THREE.DirectionalLight(0x9fe8e0, 0.45); fill.position.set(-5, -1, 3); scene.add(fill);
      const rim = new THREE.DirectionalLight(0xffffff, 0.7); rim.position.set(0, 3, -5); scene.add(rim);
      spinner = new THREE.Group(); tilt = new THREE.Group(); spinner.add(tilt); scene.add(spinner);
      sampler = document.createElement('canvas'); sctx = sampler.getContext('2d', { willReadFrequently: true });
      ready = true;
      swapObject(o.object);
      layout();
      reveal = reduce ? 1 : 0; state = 'in';
      ro = new ResizeObserver(() => { layout(); kick(); }); ro.observe(el);
      kick();
    }).catch(() => { el.classList.add('gw-failed'); canvas.remove(); });

    return api;
  }

  /* declarative use: <div data-gw-object="engine"></div> mounts lazily when it nears the viewport */
  function autoInit() {
    const els = document.querySelectorAll('[data-gw-object]:not([data-gw-manual])');
    if (!els.length) return;
    const io = new IntersectionObserver((es, obs) => es.forEach(e => { if (e.isIntersecting) { obs.unobserve(e.target); mount(e.target); } }), { rootMargin: '300px' });
    els.forEach(e => io.observe(e));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', autoInit); else autoInit();

  window.GW3D = { mount, META, _makeModels: makeModels };
})();
