(() => {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    /* the preloader lives in loader.js */
    if (reduce || !matchMedia('(pointer: fine)').matches) return;
    const smoke = document.querySelector('.cursor-smoke');
    if (!smoke) return;
    let x = innerWidth / 2, y = innerHeight / 2, tx = x, ty = y, last = 0;
    let previousX = x, previousY = y, speed = 0;
    const bits = [];
    const label = smoke.querySelector('.cursor-label');
    const interactive = 'a, button, input, textarea, select, summary, [data-signup], [data-login]';
    addEventListener('pointermove', e => {
        tx = e.clientX; ty = e.clientY;
        smoke.classList.add('is-visible');
        const target = e.target.closest?.(interactive);
        smoke.classList.toggle('is-hovering', Boolean(target));
        label.textContent = target ? 'OPEN / 01' : 'MOVE / 01';
        if (performance.now() - last > 42 && speed > .35) {
            last = performance.now();
            const bit = document.createElement('i');
            bit.className = 'smoke-bit';
            bit.style.left = `${e.clientX}px`; bit.style.top = `${e.clientY}px`;
            bit.style.setProperty('--drift-x', `${(Math.random() - .5) * (28 + speed * 1.8)}px`);
            bit.style.setProperty('--drift-y', `${-10 - Math.random() * (24 + speed)}px`);
            bit.style.setProperty('--spin', `${(Math.random() - .5) * 110}deg`);
            bit.style.setProperty('--size', `${2 + Math.random() * 5}px`);
            bit.style.setProperty('--life', `${450 + Math.min(speed * 22, 360)}ms`);
            document.body.appendChild(bit); bits.push(bit);
            setTimeout(() => { bit.remove(); bits.splice(bits.indexOf(bit), 1); }, 850);
        }
    }, { passive: true });
    addEventListener('pointerleave', () => smoke.classList.remove('is-visible'));
    const tick = () => {
        x += (tx - x) * .18; y += (ty - y) * .18;
        const dx = tx - previousX, dy = ty - previousY;
        speed += (Math.hypot(dx, dy) - speed) * .2;
        previousX = tx; previousY = ty;
        smoke.style.setProperty('--cursor-x', `${x}px`); smoke.style.setProperty('--cursor-y', `${y}px`);
        smoke.style.setProperty('--cursor-speed', `${Math.min(speed / 18, 1)}`);
        requestAnimationFrame(tick);
    };
    /* The cursor ring is invisible behind the preloader; deferring the loop
       until the curtain lifts keeps the main thread for the loader's progress
       frames (drawing the smoke every frame here starved the loader). */
    const loaderEl = document.querySelector('.site-loader');
    if (!loaderEl || loaderEl.classList.contains('is-done')) tick();
    else addEventListener('fw:loaded', tick, { once: true });
})();
