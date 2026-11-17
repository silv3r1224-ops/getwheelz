/* Pinned horizontal scroll for the "Who it's for" section.
   While the section is on screen it stays pinned under the navbar and the page's
   vertical scroll slides its cards sideways; once the last card is reached the page
   carries on scrolling vertically. No dependencies. Skipped for reduced motion. */
(() => {
  const sec = document.querySelector('[data-hscroll]');
  if (!sec) return;
  const pin = sec.querySelector('.lp-hs-pin');
  const track = sec.querySelector('.lp-hs-track');
  if (!pin || !track) return;
  const cards = [...sec.querySelectorAll('.lp-role')];
  const countEl = sec.querySelector('.lp-hs-count');
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));

  /* keep the "01 / 05" chapter nav in sync (this section is no longer a motion-graphics scene) */
  const links = [...document.querySelectorAll('.edition-links a')];
  const chapter = document.querySelector('.edition-progress');
  new IntersectionObserver(entries => entries.forEach(e => {
    if (!e.isIntersecting) return;
    const link = links.find(a => a.getAttribute('href') === '#' + sec.id);
    links.forEach(a => a.classList.toggle('is-active', a === link));
    if (link && chapter) chapter.textContent = link.dataset.chapter + ' / 05';
  }), { rootMargin: '-35% 0px -55% 0px' }).observe(sec);

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const RATIO = 1.3;                 // px of vertical scroll per px of sideways travel (>1 = slower, calmer)
  let dist = 0, runway = 0, top = 0, cur = 0, active = -1, on = false, running = false, last = 0, timer = 0;
  let ready = false;   // measurement is deferred until the preloader curtain has lifted

  const target = () => on ? clamp((top - sec.getBoundingClientRect().top) / runway) : 0;

  function paint(p) {
    track.style.transform = `translate3d(${(-p * dist).toFixed(1)}px,0,0)`;
    sec.style.setProperty('--hs-p', p.toFixed(4));
    sec.classList.toggle('hs-started', p > 0.015);
    const mid = innerWidth / 2;
    let best = 0, bd = Infinity;
    cards.forEach((c, i) => {
      const r = c.getBoundingClientRect(), d = Math.abs(r.left + r.width / 2 - mid);
      if (d < bd) { bd = d; best = i; }
    });
    if (best !== active) {
      active = best;
      cards.forEach((c, i) => c.classList.toggle('is-active', i === best));
      if (countEl) countEl.textContent = String(best + 1).padStart(2, '0') + ' / ' + String(cards.length).padStart(2, '0');
    }
  }

  function tick(now) {
    const t = target(), dt = Math.min(64, now - last || 16); last = now;
    cur += (t - cur) * (1 - Math.exp(-dt / 90));            // eased, so wheel steps glide
    if (Math.abs(t - cur) < 0.0003) cur = t;
    paint(cur);
    if (cur !== t) requestAnimationFrame(tick); else running = false;
  }
  const kick = () => { if (on && !running) { running = true; last = performance.now(); requestAnimationFrame(tick); } };

  function measure() {
    if (!ready) return;                          // skip until after the loader leaves
    const nav = document.querySelector('.navbar');
    top = nav ? Math.round(nav.getBoundingClientRect().height) : 0;
    sec.style.setProperty('--hs-top', top + 'px');
    sec.classList.add('hs-on');
    sec.style.removeProperty('--hs-h');                      // let the pinned layout settle, then measure it
    dist = Math.max(0, Math.ceil(track.offsetWidth - pin.clientWidth));
    if (dist < 8) {                                          // everything already fits: leave the plain grid
      on = false; sec.classList.remove('hs-on', 'hs-started'); track.style.transform = ''; return;
    }
    on = true;
    runway = dist * RATIO;
    sec.style.setProperty('--hs-h', Math.round(pin.offsetHeight + runway) + 'px');
    cur = target(); paint(cur);
  }
  const measureSoon = () => { clearTimeout(timer); timer = setTimeout(measure, 120); };

  /* keyboard: tabbing to a card that is off-screen scrolls the page far enough to bring it in */
  track.addEventListener('focusin', e => {
    if (!on) return;
    const el = e.target.closest('.lp-role, .lp-section-head');
    if (!el) return;
    const r = el.getBoundingClientRect();
    const offset = clamp(cur * dist + (r.left + r.width / 2 - innerWidth / 2), 0, dist);
    scrollTo({ top: scrollY + sec.getBoundingClientRect().top - top + (offset / dist) * runway, behavior: 'auto' });
  });

  addEventListener('scroll', kick, { passive: true });
  addEventListener('resize', measureSoon);
  addEventListener('load', measure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);
  if ('ResizeObserver' in window) new ResizeObserver(measureSoon).observe(track);
  /* Measure once the preloader is gone: the layout reads here are heavy and
     happen during the loader window otherwise, stalling the loader's frame
     loop (the visible frozen / stuck progress). */
  const loaderEl = document.querySelector('.site-loader');
  if (!loaderEl || loaderEl.classList.contains('is-done')) { ready = true; measure(); }
  else addEventListener('fw:loaded', () => { ready = true; measure(); }, { once: true });
})();
