/* Scroll & motion effects for the landing page. No dependencies.
   1. SplitText      - headings reveal letter by letter when they scroll in
   2. ScrollWords    - a paragraph lights up word by word as you scroll
   3. VelocityBand   - the marquee speeds up, skews and reverses with scroll speed
   4. Magnetic       - buttons lean toward the cursor
   Everything is skipped for visitors who prefer reduced motion. */
(() => {
  const page = document.querySelector('.lp');
  if (!page) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));

  /* ---------- helpers: wrap text nodes, keep inline elements (e.g. gradient spans) intact ---------- */
  function wrapText(root, makeWord) {
    [...root.childNodes].forEach(node => {
      if (node.nodeType === 1) return wrapText(node, makeWord);
      if (node.nodeType !== 3) return;
      const frag = document.createDocumentFragment();
      node.textContent.split(/(\s+)/).forEach(tok => {
        if (!tok) return;
        if (/^\s+$/.test(tok)) frag.appendChild(document.createTextNode(' '));
        else frag.appendChild(makeWord(tok));
      });
      node.parentNode.replaceChild(frag, node);
    });
  }

  /* ---------- 1. SplitText ---------- */
  const headings = page.querySelectorAll(
    '.lp-section-head h2, .lp-final-card h2, .lp-faq .lp-section-head h2'
  );
  const splitIO = new IntersectionObserver((entries, io) => entries.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.classList.add('fx-in'); io.unobserve(e.target);
  }), { threshold: 0.45, rootMargin: '0px 0px -8% 0px' });

  headings.forEach(h => {
    if (h.closest('.lp-px') || h.classList.contains('fx-split')) return;
    h.setAttribute('aria-label', h.textContent.trim().replace(/\s+/g, ' '));   // screen readers get the full text
    let i = 0;
    wrapText(h, tok => {
      const w = document.createElement('span');
      w.className = 'fx-word'; w.setAttribute('aria-hidden', 'true');
      [...tok].forEach(ch => {
        const s = document.createElement('span');
        s.className = 'fx-char'; s.style.setProperty('--i', Math.min(i++, 40)); s.textContent = ch;
        w.appendChild(s);
      });
      return w;
    });
    h.classList.add('fx-split');
    splitIO.observe(h);
  });

  /* ---------- 2. ScrollWords ---------- */
  const MIN = 0.38;
  document.querySelectorAll('[data-scroll-words]').forEach(el => {
    el.setAttribute('aria-label', el.textContent.trim().replace(/\s+/g, ' '));
    const words = [];
    wrapText(el, tok => {
      const s = document.createElement('span');
      s.className = 'fx-w'; s.setAttribute('aria-hidden', 'true'); s.textContent = tok;
      words.push(s); return s;
    });
    let cur = 0, running = false, last = 0;
    const target = () => {
      const r = el.getBoundingClientRect(), vh = innerHeight;
      const start = vh * 0.88, end = vh * 0.42;                // starts as it enters, done near mid-screen
      return clamp((start - r.top) / (start - end + r.height));
    };
    const paint = p => {
      const n = words.length, lit = p * (n + 3);
      words.forEach((w, i) => { w.style.opacity = (MIN + (1 - MIN) * clamp(lit - i)).toFixed(3); });
    };
    const tick = now => {
      const t = target(), dt = Math.min(64, now - last || 16); last = now;
      cur += (t - cur) * (1 - Math.exp(-dt / 110));            // eased so wheel steps glide
      if (Math.abs(t - cur) < 0.0004) cur = t;
      paint(cur);
      if (cur !== t) requestAnimationFrame(tick); else running = false;
    };
    const kick = () => { if (!running) { running = true; last = performance.now(); requestAnimationFrame(tick); } };
    addEventListener('scroll', kick, { passive: true }); addEventListener('resize', kick);
    cur = target(); paint(cur);
  });

  /* ---------- 3. VelocityBand ---------- */
  const band = document.querySelector('.lp-edition-marquee');
  const src = band && band.querySelector('span');
  if (band && src) {
    const html = src.innerHTML;
    const track = document.createElement('div');
    track.className = 'fx-band-track';
    band.classList.add('fx-band');
    band.replaceChild(track, src);

    let unitW = 1, x = 0, vel = 0, skew = 0, dir = 1, lastY = scrollY, lastT = 0, visible = false;
    const build = () => {
      track.innerHTML = '';
      const probe = document.createElement('span'); probe.className = 'fx-unit'; probe.innerHTML = html;
      track.appendChild(probe);
      unitW = probe.getBoundingClientRect().width || 1;
      const copies = Math.ceil((innerWidth * 2) / unitW) + 1;      // enough to cover the screen while wrapping
      for (let i = 1; i < copies; i++) { const c = probe.cloneNode(true); track.appendChild(c); }
    };
    build(); addEventListener('resize', build);
    new IntersectionObserver(e => { visible = e[0].isIntersecting; if (visible) { lastT = 0; requestAnimationFrame(loop); } }).observe(band);

    function loop(now) {
      if (!visible) return;
      const dt = Math.min(48, lastT ? now - lastT : 16) / 16.67; lastT = now;
      const dy = scrollY - lastY; lastY = scrollY;
      if (dy) dir = dy > 0 ? 1 : -1;                                // scrolling up reverses the band
      vel += (dy - vel) * Math.min(1, 0.14 * dt);                   // smoothed scroll velocity
      x -= (0.7 * dir + vel * 0.35) * dt;
      x = ((x % unitW) - unitW) % unitW;                            // seamless wrap into (-unitW, 0]
      const targetSkew = clamp(-vel * 0.4, -9, 9);
      skew += (targetSkew - skew) * Math.min(1, 0.15 * dt);
      track.style.transform = `translate3d(${x.toFixed(2)}px,0,0) skewX(${skew.toFixed(2)}deg)`;
      requestAnimationFrame(loop);
    }
  }

  /* ---------- 4. Magnetic buttons ---------- */
  if (matchMedia('(pointer: fine)').matches) {
    page.querySelectorAll('.lp-btn, .lp-ghost').forEach(btn => {
      btn.addEventListener('pointermove', e => {
        const r = btn.getBoundingClientRect();
        const dx = (e.clientX - (r.left + r.width / 2)) * 0.22;
        const dy = (e.clientY - (r.top + r.height / 2)) * 0.32;
        btn.style.translate = `${dx.toFixed(1)}px ${dy.toFixed(1)}px`;
      });
      btn.addEventListener('pointerleave', () => { btn.style.translate = ''; });
    });
  }
})();
