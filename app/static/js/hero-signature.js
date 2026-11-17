/* Hero signature trace.
   The signature asset is a single FILLED path (a calligraphic silhouette), so a
   stroke-dashoffset trick can't trace it. Instead:

   - A wipe <rect> inside the mask is grown left→right (0 → viewBox width);
     the filled ink is revealed progressively behind it. One rect is cheap to
     rasterize, so there is nothing heavy to pre-build.
   - A pen nib (a small circle) rides the sampled path at the x position of
     the wipe edge, so the reveal reads as "writing from left to right".

   The path is sampled in small chunks spread across animation frames while the
   preloader is still covering the screen — sampling the whole path at once
   is a ~1.8s main-thread block (getPointAtLength is expensive), which would
   freeze the loader at 99-100%. The trace starts the moment the loader's
   curtain begins to lift (fw:curtain). Honors prefers-reduced-motion. */
(() => {
  const wrap = document.querySelector('.lp-signature-hero');
  if (!wrap) return;

  const SVGNS = 'http://www.w3.org/2000/svg';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const ink = wrap.querySelector('.sig-ink');
  const ghost = wrap.querySelector('.sig-ghost');
  const finalEl = wrap.querySelector('.sig-final');
  const wipe = ink && ink.querySelector('#sig-wipe');
  const pen = ink && ink.querySelector('.sig-pen');

  let built = false;      // paths added, mask/pen present
  let sampled = false;    // lr ready
  let playing = false;
  let done = false;
  let wantPlay = false;

  let samples = [];       // path points [{x,y}, …]
  let lr = [];            // same points sorted by x (left→right writing order)

  function showFinal() {
    if (done) return;
    done = true;
    if (finalEl) finalEl.classList.add('is-shown');
    wrap.classList.add('is-ready');
  }

  async function prepare() {
    try {
      const res = await fetch('/static/uploads/branding/signature-hero.svg');
      if (!res.ok) throw new Error('fetch failed');
      const doc = new DOMParser().parseFromString(await res.text(), 'image/svg+xml');
      const srcPath = doc.querySelector('path');
      const d = srcPath && srcPath.getAttribute('d');
      if (!d || !ink || !ghost || !finalEl || !wipe || !pen) throw new Error('asset malformed');

      const addPath = (svg, extra) => {
        const p = document.createElementNS(SVGNS, 'path');
        p.setAttribute('d', d);
        if (extra) for (const k in extra) p.setAttribute(k, extra[k]);
        svg.appendChild(p);
      };
      addPath(ghost);
      addPath(finalEl);
      addPath(ink, { mask: 'url(#sig-mask)' });
      built = true;

      if (reduced) { showFinal(); return; }

      /* Sample the path in rAF chunks so the main thread never blocks on
         getPointAtLength (≈2ms per point in software rendering). */
      const tmp = document.createElementNS(SVGNS, 'path');
      tmp.setAttribute('d', d);
      const total = tmp.getTotalLength();
      const STEP = 32;
      const N = Math.floor(total / STEP) + 1;
      const CHUNK = 48;   // points per frame (~100ms each)
      let t = 0;
      let k = 0;

      const stepChunk = () => {
        const until = k + CHUNK;
        for (; k < until && k < N; k++, t += STEP) {
          const pt = tmp.getPointAtLength(Math.min(t, total));
          samples.push({ x: pt.x, y: pt.y });
        }
        if (k < N) {
          requestAnimationFrame(stepChunk);
        } else {
          if (samples.length < 2) { showFinal(); return; }
          lr = samples.slice().sort((a, b) => a.x - b.x || a.y - b.y);
          sampled = true;
          if (wantPlay) play();
        }
      };
      requestAnimationFrame(stepChunk);
    } catch (e) {
      showFinal();
    }
  }

  function play() {
    if (playing || done) return;
    if (!sampled) { wantPlay = true; return; }
    playing = true;

    /* Make the signature visible as soon as the trace starts, so the writing
       is actually seen (the wrapper stays hidden until now). */
    wrap.classList.add('is-ready');

    const DUR = 1800;               // trace duration (ms)
    const t0 = performance.now();

    wipe.setAttribute('width', '0');
    void wipe.getBoundingClientRect();

    const ease = p => 1 - Math.pow(1 - p, 3);

    function frame() {
      /* Use our own clock: the rAF timestamp can be stale (older than t0)
         right after a long main-thread stall. */
      const p = Math.min(1, Math.max(0, (performance.now() - t0) / DUR));
      const e = ease(p);
      const idx = Math.min(lr.length - 1, Math.floor(e * (lr.length - 1)));
      const q = lr[idx];

      wipe.setAttribute('width', String(q.x));
      pen.setAttribute('cx', String(q.x));
      pen.setAttribute('cy', String(q.y));

      if (p < 1) {
        requestAnimationFrame(frame);
      } else {
        /* Reveal complete: hide the wipe (full ink) and crossfade to the
           final layer shortly after. */
        wipe.style.opacity = '0';
        pen.style.opacity = '0';
        setTimeout(showFinal, 600);
      }
    }

    requestAnimationFrame(frame);
  }

  if (reduced) { showFinal(); return; }

  /* Build as soon as the DOM is ready: the fetch + path additions are cheap,
     and the sampling is chunked across animation frames, so nothing blocks
     the loader. */
  prepare();

  /* The trace starts a little before the loader's curtain lifts — while the
     loader is still covering the screen, so the early part is invisible
     anyway — meaning the signature is already partially written the moment
     the curtain clears, and the tail of the writing is visible immediately.
     (The wrapper is made visible at play() start, so the reveal is seen.) */
  let started = false;
  let timer = null;
  const startTrace = () => {
    if (started) return;            /* timer + loaded failsafe both fire — run once */
    started = true;
    clearTimeout(timer);
    play();
  };

  if (document.documentElement.classList.contains('is-loading')) {
    let quick = false;
    try { quick = sessionStorage.getItem('fw:intro') === '1'; } catch (e) {}
    if (document.documentElement.classList.contains('is-quick')) quick = true;
    const delay = quick ? 450 : 1350;   // ms before the curtain lifts
    timer = setTimeout(startTrace, delay);
    /* Failsafe: if the loader is still covering the screen when it finishes,
       start then. */
    addEventListener('fw:loaded', startTrace, { once: true });
  } else {
    startTrace();
  }
})();
