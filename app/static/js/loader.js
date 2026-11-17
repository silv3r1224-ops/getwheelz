/* Preloader controller. Counts 0 -> 100 against real page load (it never claims 100 before the
   window "load" event, and never finishes faster than MIN so the intro can play), then lifts the curtain.
   First visit in a session gets the full intro; later page loads get a quick version.
   Add/remove classes on .site-loader: is-quick, is-ready, is-leaving, is-done. */
(() => {
  const root = document.documentElement;
  const loader = document.querySelector('.site-loader');
  if (!loader) return;

  /* Mailbox shortcut: coming from the mailbox button skips the preloader
     entirely — no counting, no curtain. header.js sets the flag on click,
     and it is consumed here (and only here). */
  try {
    if (sessionStorage.getItem('gw:skip-loader') === '1') {
      sessionStorage.removeItem('gw:skip-loader');
      loader.classList.add('is-done');
      root.classList.remove('is-loading');
      dispatchEvent(new Event('fw:loaded'));
      return;
    }
  } catch (e) { /* storage blocked: run the loader as usual */ }

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { loader.classList.add('is-done'); return; }

  let quick = false;
  try { quick = sessionStorage.getItem('fw:intro') === '1'; sessionStorage.setItem('fw:intro', '1'); } catch (e) { /* storage blocked: always full intro */ }
  loader.classList.toggle('is-quick', quick);
  root.classList.add('is-loading');

  /* Flow-trace pacing: the full intro draws the whole wordmark over ~2.4s so it
     finishes as the counter hits 100 and the curtain lifts; the quick repeat-
     visit version keeps a short, snappy trace. */
  const tr = quick
      ? { draw: .45, start: .05 }
      : { draw: 1.5, start: .18 };
  loader.style.setProperty('--tr-draw', `${tr.draw}s`);
  loader.style.setProperty('--tr-start', `${tr.start}s`);

  const num = loader.querySelector('.ld-num');
  const bar = loader.querySelector('.ld-bar i');
  const status = loader.querySelector('.ld-status');
  const MIN = quick ? 500 : 1680;                                   // base duration; grows to match the pen draw if the asset is later
  const STEPS = [[0, 'Starting up'], [25, 'Finding workshops'], [55, 'Tuning the map'], [85, 'Almost there'], [100, 'Ready']];

  let loaded = document.readyState === 'complete';
  let shown = 0, step = -1, leaving = false;
  const t0 = performance.now();
  addEventListener('load', () => { loaded = true; }, { once: true });
  /* The page's own DOM is the real gate; external resources (map tiles,
     fonts, third-party widgets) must not hold the curtain hostage. */
  if (document.readyState === 'loading') {
    addEventListener('DOMContentLoaded', () => {
      setTimeout(() => { loaded = true; }, 600);
    }, { once: true });
  } else {
    setTimeout(() => { loaded = true; }, 600);
  }

  const finish = () => {
    if (loader.classList.contains('is-done')) return;
    loader.classList.add('is-done');
    root.classList.remove('is-loading');
    dispatchEvent(new Event('fw:loaded'));
  };
  setTimeout(finish, 6000);                                         // last-resort failsafe
  addEventListener('pageshow', e => { if (e.persisted) finish(); }); // back/forward cache: never show a stale loader

  /* The Getwheelz handwriting wordmark (brand asset — getwheelz_handwriting.svg
     in ref-assets, transformed into static/uploads/branding/getwheelz-handwriting-loader.svg).
     The asset embeds its own stroke-draw animation: 132 pen strokes, each clipped
     to its glyph region, animate stroke-dashoffset in sequence, so the filled
     wordmark appears stroke-by-stroke exactly like handwriting. A --k CSS var
     scales the whole timeline (7.84s at k=1) to match our intro pacing. */
  const trace = loader.querySelector('.ld-trace');
  const ghost = trace && trace.querySelector('.ld-flow-ghost');

  const HW_TOTAL = 7.84;                                           // asset timeline at --k:1 (seconds)
  let tDraw0 = null;                                               // draw clock starts when the wordmark is ready
  let wmReady = false, wmFailed = false;

  async function setWordmark() {
    try {
      const res = await fetch('/static/uploads/branding/getwheelz-handwriting-loader.svg');
      if (!res.ok) return;
      const svgText = await res.text();
      const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');

      const defs = doc.querySelector('defs');
      const style = doc.querySelector('style');
      const fillPath = doc.querySelector('path.ld-flow');
      if (!defs || !style || !fillPath) return;

      const d = fillPath.getAttribute('d');
      if (ghost) ghost.setAttribute('d', d);

      /* scale the handwriting timeline to this mode's draw window */
      const k = Math.max(0.02, tr.draw / HW_TOTAL);
      if (trace) trace.style.setProperty('--k', String(k));

      /* adopt the asset's defs, style, and masked fill path into the trace */
      if (trace) {
        trace.appendChild(defs);
        trace.appendChild(style);
        const flow = doc.createElementNS('http://www.w3.org/2000/svg', 'path');
        for (const attr of ['fill', 'fill-rule', 'mask', 'd']) {
          const v = fillPath.getAttribute(attr);
          if (v) flow.setAttribute(attr, v);
        }
        flow.classList.add('ld-flow');
        trace.appendChild(flow);
      }

      tDraw0 = performance.now();                                  // now start the reveal clock
      wmReady = true;
      /* sync % with the pen: the counter must hit 100 exactly when the last
         stroke lands, even if the wordmark asset took a moment to arrive */
      duration = Math.max(MIN, (tDraw0 - t0) + tr.start * 1000 + tr.draw * 1000);
    } catch (e) {
      wmFailed = true;
      /* wordmark unavailable: run the loader without the trace */
    }
  }
  setTimeout(() => { if (!wmReady) wmFailed = true; }, 4000);        // never let a stuck fetch hold the page

  setWordmark();                                                     // load + apply the wordmark art

  function leave() {
    if (leaving) return;
    leaving = true;
    loader.classList.add('is-ready');
    dispatchEvent(new Event('fw:curtain'));                        // curtain starts lifting: start post-loader reveals now
    setTimeout(() => {
      loader.classList.add('is-leaving');
      loader.addEventListener('animationend', e => {
        if (e.target === loader && e.animationName === 'ld-exit') finish();
      });
      setTimeout(finish, 1600);                                     // in case animationend never fires
    }, quick ? 60 : 160);
  }

  let duration = MIN;                                             // grows to pen duration once the wordmark is ready
  function frame(now) {
    const eased = 1 - Math.pow(1 - Math.min(1, (now - t0) / duration), 3); // easeOutCubic over duration
    shown = loaded ? eased * 100 : Math.min(92, eased * 100);           // exact tracking: no creep, no stall
    if (loaded && eased >= 1) shown = 100;

    const pct = shown >= 100 ? 100 : Math.min(99, Math.floor(shown));
    num.textContent = String(pct).padStart(3, '0');
    bar.style.transform = `scaleX(${(shown / 100).toFixed(4)})`;
    let s = 0;
    for (let i = 0; i < STEPS.length; i++) if (pct >= STEPS[i][0]) s = i;
    if (s !== step) { step = s; status.textContent = STEPS[s][1]; }

    /* don't leave until the wordmark drawing has played out its full stroke
       sequence; if it never loads, wmFailed lets the loader proceed anyway */
    if (pct >= 100 && (wmFailed || (wmReady && tDraw0 !== null && (now - tDraw0) >= tr.start * 1000 + tr.draw * 1000))) leave();
    else requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
