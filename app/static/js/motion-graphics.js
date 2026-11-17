/* Lightweight motion-graphics layer for landing sections. Canvas particles keep the
   premium mech atmosphere alive without requiring WebGL or a third-party runtime. */
(() => {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    /* Low-power detection: little RAM/CPU, save-data / slow connection, or a
       coarse (touch) pointer. Adds `low-power` to <html> so CSS can drop the
       expensive GPU work (blur, blend modes, layer promotion) too. */
    const lowPower = (navigator.deviceMemory && navigator.deviceMemory <= 4) ||
        (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4) ||
        (navigator.connection && (navigator.connection.saveData || /2g|slow-2g/.test(navigator.connection.effectiveType || ''))) ||
        matchMedia('(pointer: coarse)').matches;
    if (lowPower) document.documentElement.classList.add('low-power');
    if (reduce) return;
    const sections = [...document.querySelectorAll('.lp-motion-section')].filter(s => s.querySelector('.lp-motion-canvas'));
    if (!sections.length) return;
    const links = [...document.querySelectorAll('.edition-links a')];
    const progress = document.querySelector('.edition-progress');
    const chapterObserver = new IntersectionObserver(entries => entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const id = entry.target.id;
        const link = links.find(item => item.getAttribute('href') === `#${id}`);
        links.forEach(item => item.classList.toggle('is-active', item === link));
        if (link && progress) progress.textContent = `${link.dataset.chapter} / 05`;
    }), { rootMargin: '-35% 0px -55% 0px', threshold: 0 });
    sections.forEach(section => chapterObserver.observe(section));

    const palette = ['139,230,223', '238,107,97', '215,243,107'];
    const scenes = new WeakMap();
    const objects = [];
    const objectSelector = '.lp-section-head, .lp-stats-bar, .lp-tile, .lp-map-frame, .lp-step, .lp-role, .lp-faq-list details, .lp-final-card';
    document.querySelectorAll('.lp').forEach(page => {
        page.querySelectorAll(objectSelector).forEach((element, index) => {
            element.classList.add('lp-motion-object');
            element.style.setProperty('--object-index', index % 9);
            element.style.setProperty('--object-side', index % 2 ? '1' : '-1');
            objects.push(element);
        });
    });
    /* Element vertical positions are cached and refreshed on scroll/resize only.
       Reading getBoundingClientRect() inside the animation loop would force a
       layout flush every frame — the single biggest cause of scroll jank on
       low-end devices. */
    const positions = new Map();
    /* Positions are stored relative to the document (not the viewport), so
       the entrance progress can be derived from window.scrollY on every
       frame — the motion never lags or stalls between scroll events. */
    const measure = () => {
        const sy = window.scrollY;
        objects.forEach(el => {
            const r = el.getBoundingClientRect();
            /* Cards synchronise to their section: when the section (or the card
               itself, if it lives outside a motion section) is exactly centered
               in the viewport, the card is at home. */
            const anchor = el.closest('.lp-motion-section') || el;
            const ar = anchor.getBoundingClientRect();
            positions.set(el, { docTop: r.top + sy, height: r.height, anchorDocTop: ar.top + sy, anchorHeight: ar.height });
        });
    };
    let measurePending = false;
    const requestMeasure = () => {
        if (measurePending) return;
        measurePending = true;
        requestAnimationFrame(() => { measure(); measurePending = false; });
    };
    measure();
    addEventListener('scroll', requestMeasure, { passive: true });
    addEventListener('resize', requestMeasure, { passive: true });
    /* While a card is hovered, the CSS lift runs on its own ./scale/rotate
       transitions. Pausing the per-frame writes for that card stops the two
       motion engines from fighting on the same element (the cause of the
       hover flicker on the step / service / final cards). */
    const hovered = new Set();
    objects.forEach(el => {
        el.addEventListener('pointerenter', () => hovered.add(el));
        el.addEventListener('pointerleave', () => hovered.delete(el));
    });
    let pointerX = innerWidth * .5, pointerY = innerHeight * .4;
    let currentScrollY = window.scrollY;
    let lastScrollY = currentScrollY;
    let scrollVelocity = 0;
    let scrollingDown = true;
    let lastT = performance.now();
    /* Per-card state (entered latch + smoothed progress) — module-scoped so it
       survives across animation frames. */
    const states = new WeakMap();
    addEventListener('pointermove', e => { pointerX = e.clientX; pointerY = e.clientY; }, { passive: true });
    addEventListener('scroll', () => { lastScrollY = currentScrollY; currentScrollY = window.scrollY; scrollVelocity = currentScrollY - lastScrollY; scrollingDown = currentScrollY >= lastScrollY; }, { passive: true });
    const pixelTransitions = [];
    const updatePixelTransitions = () => {};
    sections.forEach(section => {
        const canvas = section.querySelector('.lp-motion-canvas');
        const ctx = canvas.getContext('2d');
        const particles = Array.from({ length: lowPower ? 12 : 34 }, (_, i) => ({
            x: Math.random(), y: Math.random(), size: 1 + Math.random() * 2.4,
            speed: .00008 + Math.random() * .00018, phase: Math.random() * 6.28,
            color: palette[i % palette.length]
        }));
        scenes.set(section, { canvas, ctx, particles, width: 0, height: 0, active: false, t: 0 });
        const resize = () => {
            const dpr = Math.min(devicePixelRatio || 1, lowPower ? 1.33 : 2);
            const box = section.getBoundingClientRect();
            const scene = scenes.get(section);
            scene.width = Math.max(1, box.width); scene.height = Math.max(1, box.height);
            canvas.width = scene.width * dpr; canvas.height = scene.height * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        };
        resize(); addEventListener('resize', resize, { passive: true });
        section.addEventListener('pointermove', e => {
            const r = section.getBoundingClientRect();
            section.style.setProperty('--motion-x', `${((e.clientX - r.left) / r.width) * 100}%`);
            section.style.setProperty('--motion-y', `${((e.clientY - r.top) / r.height) * 100}%`);
        }, { passive: true });
    });

    const observer = new IntersectionObserver(entries => entries.forEach(e => { scenes.get(e.target).active = e.isIntersecting; }), { threshold: .05 });
    sections.forEach(s => observer.observe(s));

    const draw = now => {
        const velocity = Math.max(-22, Math.min(22, scrollVelocity));
        scrollVelocity *= .86;
        updatePixelTransitions();
        const dt = Math.min(.1, Math.max(.001, (now - lastT) / 1000));
        lastT = now;
        objects.forEach((element, index) => {
            if (hovered.has(element)) return;   // CSS hover motion owns the card for now
            const cached = positions.get(element);
            if (!cached) return;
            const top = cached.docTop - window.scrollY, height = cached.height;
            if (top + height < -260 || top > innerHeight + 260) return;
            const depth = 1 + (index % 5) * .28;
            /* Progress is driven by the anchor (the card's section, or the card
               itself): offset = how far the anchor's centre sits from the viewport
               centre. offset 0 → exactly on frame → settled. Entrance spans one
               span-length of scroll below centre; reversal mirrors it. */
            const aTop = cached.anchorDocTop - window.scrollY;
            const aCenter = aTop + cached.anchorHeight / 2;
            const offset = aCenter - innerHeight / 2;
            const span = innerHeight * .68;
            let st = states.get(element);
            if (!st) { st = { entered: false, cur: 0 }; states.set(element, st); }
            const side = index % 2 ? 1 : -1;
            const maxDist = Math.min(innerWidth * .36, (220 + (index % 6) * 42) * (lowPower ? .55 : 1));
            const activity = Math.max(0, Math.min(1, (Math.abs(velocity) - .8) / 6));
            const active = activity > 0;
            const sway = (!active || lowPower) ? 0 : Math.sin(now * .0011 + index * 1.7) * (3 + index % 4) * activity;
            const lift = !active ? 0 : Math.max(-9, Math.min(9, -velocity * depth * .30)) * activity;
            const rotate = !active ? 0 : Math.max(-3, Math.min(3, velocity * (index % 2 ? .07 : -.07))) * activity;

            const p = Math.max(0, Math.min(1, 1 - offset / span));
            const o = Math.max(0, Math.min(1, offset / span));
            if (scrollingDown) {
                if (p >= 1) st.entered = true;   // latched home
            } else if (st.entered && o >= 1) {
                st.entered = false;               // fully out below → ready to re-enter
            }
            /* Target progress: 1 = home, 0 = fully out. The card chases the
               target with a smoothed lerp every frame, so the glide is fluid
               and consistent no matter how the scroll input arrives (wheel
               notches, trackpad, drag) — and direction changes never hard-snap. */
            const target = !scrollingDown ? (st.entered ? 1 - o : 0) : (st.entered ? 1 : p);
            st.cur += (target - st.cur) * (1 - Math.exp(-dt * 15));
            const t = st.cur;
            if (t > .95 && target >= 1) {
                element.style.setProperty('--object-x', '0px');
                element.style.setProperty('--object-y', '0px');
                element.style.setProperty('--object-rotate', '0deg');
                element.style.setProperty('--object-alpha', '1');
                if (element.style.willChange !== 'auto') element.style.willChange = 'auto';
                return;
            }
            const eased = 1 - Math.pow(1 - t, 2.2);
            const out = 1 - eased;
            element.style.setProperty('--object-x', `${side * out * maxDist}px`);
            element.style.setProperty('--object-y', `${sway + lift + out * 36 * (lowPower ? .6 : 1)}px`);
            element.style.setProperty('--object-rotate', `${rotate + side * out * (index % 2 ? 9 : -9) * (lowPower ? .5 : 1)}deg`);
            element.style.setProperty('--object-alpha', `${Math.max(.12, Math.min(1, t * 1.25))}`);
        });
        sections.forEach(section => {
            const scene = scenes.get(section);
            if (!scene || !scene.active) return;
            scene.t = now;
            const { ctx, width, height, particles } = scene;
            ctx.clearRect(0, 0, width, height);
            const sectionRect = section.getBoundingClientRect();
            const localPointerX = (pointerX - sectionRect.left) / Math.max(width, 1);
            particles.forEach((p, i) => {
                p.y -= p.speed * 16;
                if (p.y < -.05) p.y = 1.05;
                const drift = Math.sin(now * .0007 + p.phase) * 12;
                const x = p.x * width + drift + (localPointerX - .5) * (i % 2 ? 10 : -10);
                const y = p.y * height;
                const alpha = .12 + .16 * (Math.sin(now * .001 + p.phase) + 1);
                ctx.fillStyle = `rgba(${p.color},${alpha})`;
                ctx.fillRect(x, y, p.size, p.size);
                if (i % 6 === 0 && !lowPower) {
                    ctx.strokeStyle = `rgba(${p.color},${alpha * .55})`;
                    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 18, y - 8); ctx.stroke();
                }
            });
        });
        requestAnimationFrame(draw);
    };

    /* Defer the render loop until the preloader's curtain has lifted: while the
       loader is up, this per-frame work (style writes + layout reads on every
       .lp-motion-object, canvas fills) monopolizes the main thread and starves
       the loader's own progress frames — the visible "stuck percentage".  */
    const boot = () => {
      measure();
      requestAnimationFrame(draw);
    };
    const loaderEl = document.querySelector('.site-loader');
    if (!loaderEl || loaderEl.classList.contains('is-done')) boot();
    else addEventListener('fw:loaded', boot, { once: true });
})();
