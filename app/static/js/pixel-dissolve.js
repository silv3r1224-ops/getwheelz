/* Scroll-driven pixel dissolve for the landing page image sections (.lp-px).
   Per section, p = scroll progress through the tall section:
     0.00-0.32  page      -> image   (pixel wavefront rises)
     0.32-0.68  image held, text fades in/out
     0.68-1.00  image     -> page
   The canvas is transparent wherever the "page" should show, so the real body
   background (grid lines, glow, dark/light theme) shows through with no seam.

   Smoothness: scroll progress is eased (so wheel steps glide), pixel cells fade
   in over a soft edge instead of popping, and fully-revealed cells are painted
   in ONE clipped draw call instead of thousands. */
(() => {
  const zones = document.querySelectorAll('.lp-px');
  if (!zones.length) return;

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const smooth = t => t * t * (3 - 2 * t);
  const IN = 0.36, OUT = 0.64;
  const PAGE = 0, IMG = 1;
  const EASE_MS = 125;      // higher = floatier scroll, lower = snappier
  const SOFT = 3;          // soft-edge width in cells

  zones.forEach(zone => {
    const canvas = zone.querySelector('.lp-px-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const layer = document.createElement('canvas');   // image, pre-fitted and darkened
    const img = new Image();
    const focus = parseFloat(canvas.dataset.pxFocus || '0.5');
    let loaded = false, W = 0, H = 0, dpr = 1, cell = 12, cols = 0, rows = 0, rnd = null;
    let cur = null, running = false, last = 0, raf = 0;

    zone.style.setProperty('--px-text', '0');          // text hidden until the image is revealed

    function paintLayer() {
      layer.width = W * dpr; layer.height = H * dpr;
      const g = layer.getContext('2d');
      g.fillStyle = '#09090b'; g.fillRect(0, 0, layer.width, layer.height);
      if (!loaded) return;
      const s = Math.max(layer.width / img.naturalWidth, layer.height / img.naturalHeight);
      const w = img.naturalWidth * s, h = img.naturalHeight * s;
      g.filter = 'grayscale(.85) contrast(1.15) brightness(.6)';
      g.drawImage(img, (layer.width - w) * focus, (layer.height - h) / 2, w, h);
      g.filter = 'none';
      g.fillStyle = 'rgba(8,9,11,.3)'; g.fillRect(0, 0, layer.width, layer.height);
    }

    function resize() {
      dpr = Math.min(devicePixelRatio || 1, 2);
      W = canvas.clientWidth; H = canvas.clientHeight;
      if (!W || !H) return;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);            // draw in CSS pixels from here on
      cell = Math.max(8, Math.round(W / 110));
      cols = Math.ceil(W / cell); rows = Math.ceil(H / cell);
      rnd = Float32Array.from({ length: cols * rows }, Math.random);
      paintLayer();
      const p = progress(); if (p !== null) render(cur ?? p);
    }

    function progress() {
      const r = zone.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) return null;   // off-screen: nothing to do
      return clamp(-r.top / Math.max(1, r.height - innerHeight));
    }

    // paint the "to" state over the "from" state inside `region`
    const paintFull = (kind) => {
      if (kind === PAGE) ctx.clearRect(0, 0, W, H); else ctx.drawImage(layer, 0, 0, W, H);
    };

    function render(p) {
      if (!W || !H) return;

      let tx = smooth(clamp((p - 0.30) / 0.12)) * smooth(clamp((OUT - p) / 0.10));
      if (reduce) tx = p > IN / 2 && p < (1 + OUT) / 2 ? 1 : 0;
      zone.style.setProperty('--px-text', tx.toFixed(3));
      zone.classList.toggle('is-readable', tx > 0.6);

      let from, to, t;
      if (p < OUT) { from = PAGE; to = IMG;  t = clamp(p / IN); }
      else         { from = IMG;  to = PAGE; t = clamp((p - OUT) / (1 - OUT)); }
      if (reduce) t = t > 0.5 ? 1 : 0;                   // reduced motion: hard cut, no sweep
      else t = smooth(t) * 0.55 + t * 0.45;              // gentle ease at both ends of each dissolve

      ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      if (t <= 0) { ctx.save(); paintFull(from); ctx.restore(); return; }
      if (t >= 1) { ctx.save(); paintFull(to); ctx.restore(); return; }

      const band = H * 0.28, soft = cell * SOFT;
      const front = (H + 2 * band) * (1 - t) - band;
      paintFull(from);

      // 1) everything below the noisy band is fully "to"; 2) full cells inside the band;
      //    all merged into one clip path -> one paint call
      const clip = new Path2D();
      const solid = Math.min(H, Math.max(0, front + band + soft));
      if (solid < H) clip.rect(0, solid, W, H - solid);
      const partial = [];                                 // cells still fading: [x, y, alpha]
      const r0 = Math.max(0, Math.floor((front - band) / cell));
      const r1 = Math.min(rows - 1, Math.ceil((front + band + soft) / cell));
      for (let y = r0; y <= r1; y++) {
        let run = -1;
        for (let x = 0; x <= cols; x++) {
          let a = 0;
          if (x < cols) {
            const jag = (rnd[y * cols + x] ** 2 - 0.25) * band * 1.6;
            a = clamp((y * cell - (front + jag)) / soft);
          }
          if (a >= 1) { if (run < 0) run = x; continue; }
          if (run >= 0) { clip.rect(run * cell, y * cell, (x - run) * cell, cell); run = -1; }
          if (a > 0) partial.push(x, y, a);
        }
      }

      ctx.save();
      ctx.clip(clip);
      paintFull(to);
      ctx.restore();

      for (let i = 0; i < partial.length; i += 3) {
        const x = partial[i] * cell, y = partial[i + 1] * cell, a = partial[i + 2];
        if (to === PAGE) {
          ctx.globalCompositeOperation = 'destination-out';
          ctx.fillStyle = `rgba(0,0,0,${a})`;
          ctx.fillRect(x, y, cell, cell);
        } else {
          ctx.globalCompositeOperation = 'source-over';
          ctx.globalAlpha = a;
          ctx.drawImage(layer, x * dpr, y * dpr, cell * dpr, cell * dpr, x, y, cell, cell);
        }
      }
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
    }

    // eased progress loop: runs only while scrolling / catching up
    function tick(now) {
      const p = progress();
      if (p === null) { cur = null; running = false; return; }
      if (cur === null || reduce) cur = p;
      const dt = Math.min(64, now - last || 16); last = now;
      cur += (p - cur) * (1 - Math.exp(-dt / EASE_MS));
      if (Math.abs(p - cur) < 0.0003) cur = p;
      render(cur);
      if (cur !== p) raf = requestAnimationFrame(tick); else running = false;
    }
    function kick() {
      if (running) return;
      running = true; last = performance.now();
      raf = requestAnimationFrame(tick);
    }

    addEventListener('scroll', kick, { passive: true });
    new ResizeObserver(resize).observe(canvas);

    img.onload = () => { loaded = true; paintLayer(); kick(); };
    img.src = canvas.dataset.pxImage;
    resize();
  });
})();
