/* Reason-picker check fx: a tiny spark burst when a `.px-reason` checkbox is
   checked. Uses the house motion language (see premium-chrome.js smoke bits) —
   CSS-variable-driven bits that drift, spin and fade. Skipped entirely when the
   user prefers reduced motion or the device is flagged low-power. */
(() => {
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || document.documentElement.classList.contains('low-power')) return;

    const palette = ['139,230,223', '238,107,97', '215,243,107'];

    const spark = (x, y) => {
        const bit = document.createElement('i');
        bit.className = 'reason-spark-bit';
        const size = 3 + Math.random() * 4;
        bit.style.left = `${x}px`;
        bit.style.top = `${y}px`;
        bit.style.setProperty('--size', `${size}px`);
        bit.style.setProperty('--drift-x', `${(Math.random() - .5) * 46}px`);
        bit.style.setProperty('--drift-y', `${-14 - Math.random() * 26}px`);
        bit.style.setProperty('--spin', `${(Math.random() - .5) * 200}deg`);
        bit.style.setProperty('--life', `${420 + Math.random() * 260}ms`);
        bit.style.setProperty('--spark-color', `rgb(${palette[(Math.random() * palette.length) | 0]})`);
        document.body.appendChild(bit);
        setTimeout(() => bit.remove(), 900);
    };

    document.addEventListener('change', e => {
        const box = e.target.closest?.('input[type="checkbox"]');
        if (!box || !box.checked) return;
        const r = box.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        for (let i = 0; i < 6; i++) spark(cx, cy);
    });
})();
