/* "The Garage" showcase: wires the picker list, the ASCII/PIXEL toggle and the HUD to a GW3D stage.
   Mounts lazily (three.js is only downloaded when the section is near the viewport) and auto-cycles
   through the parts until the visitor takes over. */
(() => {
  const stage = document.querySelector('.gw-stage');
  const list = document.querySelector('.gw-list');
  if (!stage || !list || !window.GW3D) return;

  const META = GW3D.META;
  const nameEl = document.querySelector('[data-gw-name]');
  const specEl = document.querySelector('[data-gw-spec]');
  const idxEl = document.querySelector('[data-gw-idx]');
  const modeBtns = [...document.querySelectorAll('[data-gw-mode-btn]')];
  const pad = n => String(n).padStart(2, '0');

  list.innerHTML = META.map((m, i) =>
    `<li><button type="button" data-gw-pick="${m.id}"><b>${pad(i + 1)}</b><span>${m.name}<small>${m.spec}</small></span></button></li>`).join('');
  const picks = [...list.querySelectorAll('[data-gw-pick]')];

  let api = null, current = stage.dataset.gwObject || META[0].id, auto = true, timer = 0, visible = false;

  function show(meta, i) {
    current = meta.id;
    picks.forEach(b => { const on = b.dataset.gwPick === meta.id; b.classList.toggle('is-on', on); b.setAttribute('aria-pressed', on); });
    if (nameEl) nameEl.textContent = meta.name;
    if (specEl) specEl.textContent = meta.spec;
    if (idxEl) idxEl.textContent = pad(i + 1) + ' / ' + pad(META.length);
  }
  show(META.find(m => m.id === current) || META[0], Math.max(0, META.findIndex(m => m.id === current)));

  const stopAuto = () => { auto = false; clearInterval(timer); };
  function startAuto() {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    clearInterval(timer);
    timer = setInterval(() => {
      if (!auto || !visible || document.hidden || !api) return;
      const i = META.findIndex(m => m.id === current);
      api.setObject(META[(i + 1) % META.length].id);
    }, 7000);
  }

  picks.forEach(b => b.addEventListener('click', () => { stopAuto(); show(META.find(m => m.id === b.dataset.gwPick), META.findIndex(m => m.id === b.dataset.gwPick)); if (api) api.setObject(b.dataset.gwPick); }));
  modeBtns.forEach(b => b.addEventListener('click', () => {
    stopAuto();
    modeBtns.forEach(x => { const on = x === b; x.classList.toggle('is-on', on); x.setAttribute('aria-pressed', on); });
    if (api) api.setMode(b.dataset.gwModeBtn);
  }));
  stage.addEventListener('pointerdown', stopAuto);

  new IntersectionObserver(es => {
    visible = es[0].isIntersecting;
    if (visible && !api) {
      api = GW3D.mount(stage, { object: current, mode: stage.dataset.gwMode || 'ascii', onchange: show });
      startAuto();
    }
  }, { rootMargin: '300px' }).observe(stage);
})();
