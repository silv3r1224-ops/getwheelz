/* "Live parts" showcase cards inside the pinned horizontal-scroll section (index.html roles).
   Each card hosts its own mini GW3D stage, mounted lazily when the card nears the
   viewport (the track slides sideways, so a card that is far off-screen stays
   unmounted), with a per-card ASCII / PIXEL toggle. Mirrors garage.js, but there
   is no auto-cycle: the visitor takes over immediately. */
(() => {
  const cards = [...document.querySelectorAll('.lp-role-parts')];
  if (!cards.length || !window.GW3D) return;

  cards.forEach(card => {
    const stageEl = card.querySelector('.gw-stage');
    if (!stageEl) return;
    const nameEl = card.querySelector('[data-gw-name]');
    const specEl = card.querySelector('[data-gw-spec]');
    const btns = [...card.querySelectorAll('[data-gw-mode-btn]')];
    let api = null;

    const setBtn = b => btns.forEach(x => {
      const on = x === b;
      x.classList.toggle('is-on', on);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
    });

    btns.forEach(b => b.addEventListener('click', () => {
      setBtn(b);
      if (api) api.setMode(b.dataset.gwModeBtn);
    }));
    stageEl.addEventListener('pointerdown', () => { /* interaction takes over; nothing to pause */ });

    const io = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting || api) return;
      io.disconnect();
      api = GW3D.mount(stageEl, {
        object: stageEl.dataset.gwObject,
        mode: stageEl.dataset.gwMode || 'ascii',
        onchange: meta => {
          if (nameEl) nameEl.textContent = meta.name;
          if (specEl) specEl.textContent = meta.spec;
        }
      });
    }), { rootMargin: '400px' });
    io.observe(stageEl);
  });
})();
