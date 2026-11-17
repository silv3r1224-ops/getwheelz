// Seamless text marquee for the edition bands (.px-edition-marquee /
// .lp-edition-marquee). A pure-CSS translateX(-50%) loop only looks seamless
// when one copy of the message is wider than the viewport; on wide screens the
// strip runs out and shows empty space before looping. Here the script wraps
// the message(s) in a track, duplicates the set until one full set is wider
// than the viewport, and animates by exactly one set width (--marq-shift), so
// the loop never shows a gap.
(function () {
    const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const SPEED = 70;        // px per second
    const MAX_COPIES = 12;

    // Wrap the band's children in a track (if not already wrapped).
    const ensureTrack = (marq) => {
        let track = marq.querySelector(':scope > .px-marquee-track');
        if (!track) {
            track = document.createElement('div');
            track.className = 'px-marquee-track';
            while (marq.firstChild) track.appendChild(marq.firstChild);
            marq.appendChild(track);
        }
        return track;
    };

    document.querySelectorAll('.px-edition-marquee, .lp-edition-marquee').forEach((marq) => {
        const track = ensureTrack(marq);
        const originals = Array.from(track.children);
        if (!originals.length || reduceMotion) return;

        // Width of one full set (start of set 2 minus start of set 1) — this
        // includes the flex gap, so a shift of exactly this amount re-seams.
        const setWidth = () => {
            const firstClone = track.children[originals.length];
            if (!firstClone) return 0;
            return firstClone.offsetLeft - track.children[0].offsetLeft;
        };
        const viewportW = () => (track.parentElement ? track.parentElement.clientWidth : 0);

        const appendSet = () => {
            originals.forEach((c) => {
                const dup = c.cloneNode(true);
                dup.setAttribute('aria-hidden', 'true');
                track.appendChild(dup);
            });
        };
        appendSet();

        let copies = 2;
        while (copies < MAX_COPIES && setWidth() < viewportW()) {
            appendSet();
            copies++;
        }

        const setShift = () => {
            const w = setWidth();
            if (w > 10) {
                track.style.setProperty('--marq-shift', `${w}px`);
                track.style.setProperty('--marq-duration', `${Math.max(8, Math.round(w / SPEED))}s`);
            }
        };
        setShift();

        let raf = null;
        window.addEventListener('resize', () => {
            // Growing the window may need extra copies to stay seamless.
            while (copies < MAX_COPIES && setWidth() < viewportW()) {
                appendSet();
                copies++;
            }
            if (raf) return;
            raf = requestAnimationFrame(() => { raf = null; setShift(); });
        });
    });
})();
