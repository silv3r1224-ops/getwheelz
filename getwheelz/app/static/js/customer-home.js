// Customer home: recommended carousel, location status, and the nearby-workshops grid.
// Distances come from distance.js (window.GW), which must be loaded first.

(function () {
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // ---------- Recommended carousel: auto-slides one workshop at a time ----------
    const track = document.getElementById('rec-track');
    const prevBtn = document.getElementById('rec-prev');
    const nextBtn = document.getElementById('rec-next');
    const cards = track ? track.querySelectorAll('.px-wcard') : [];

    if (track && prevBtn && nextBtn) {
        if (cards.length < 2) {
            prevBtn.hidden = nextBtn.hidden = true;
        } else {
            const INTERVAL = 4500;
            const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
            let timer = null;

            const step = () => {
                const gap = parseInt(getComputedStyle(track).columnGap, 10) || 18;
                return cards[0].offsetWidth + gap;
            };
            const atEnd = () => track.scrollLeft + track.clientWidth >= track.scrollWidth - 6;
            const next = () => (atEnd()
                ? track.scrollTo({ left: 0, behavior: 'smooth' })
                : track.scrollBy({ left: step(), behavior: 'smooth' }));
            const prev = () => (track.scrollLeft <= 6
                ? track.scrollTo({ left: track.scrollWidth, behavior: 'smooth' })
                : track.scrollBy({ left: -step(), behavior: 'smooth' }));

            const stop = () => { clearInterval(timer); timer = null; };
            const start = () => {
                if (reduceMotion || document.hidden) return;
                clearInterval(timer);
                timer = setInterval(next, INTERVAL);
            };

            nextBtn.addEventListener('click', () => { next(); start(); });
            prevBtn.addEventListener('click', () => { prev(); start(); });
            track.addEventListener('mouseenter', stop);
            track.addEventListener('mouseleave', start);
            track.addEventListener('focusin', stop);
            track.addEventListener('focusout', start);
            track.addEventListener('touchstart', stop, { passive: true });
            track.addEventListener('touchend', start);
            document.addEventListener('visibilitychange', () => (document.hidden ? stop() : start()));
            start();
        }
    }

    // ---------- Location, distances and the nearby grid ----------
    const section = document.getElementById('nearby-section');
    const grid = document.getElementById('nearby-grid');
    const status = document.getElementById('nearby-status');
    const locChip = document.getElementById('loc-chip');
    if (!window.GW) return;

    const profileUrl = section ? (section.dataset.profileUrl || '/workshops/0') : '';
    const staticUrl = section ? (section.dataset.staticUrl || '/static/') : '';

    function setChip(state) {
        if (!locChip) return;
        locChip.classList.toggle('ok', state === 'ok');
        const text = locChip.querySelector('.loc-text');
        const btn = locChip.querySelector('button');
        if (state === 'ok') {
            text.textContent = 'Distances measured from your location';
            btn.hidden = true;
        } else if (state === 'loading') {
            text.textContent = 'Finding your location...';
            btn.hidden = true;
        } else {
            text.textContent = 'Turn on location to see distances';
            btn.hidden = false;
        }
    }

    function showStatus(icon, title, text, withButton) {
        if (!status) return;
        status.hidden = false;
        if (grid) grid.hidden = true;
        status.innerHTML =
            "<i class='bx " + icon + "'></i><h3>" + esc(title) + '</h3><p>' + esc(text) + '</p>' +
            (withButton ? "<button type='button' class='px-btn sm' data-enable-location>Use my location</button>" : '');
    }

    function card(w) {
        const href = profileUrl.replace(/0$/, w.w_id);
        const img = w.photo_url
            ? "<img src='" + staticUrl + esc(w.photo_url) + "' alt='" + esc(w.name) + "' loading='lazy'>"
            : "<div class='px-ph'><i class='bx bx-store'></i></div>";
        const km = Number(w.distance_km);
        return (
            "<a href='" + href + "' class='px-card px-lift px-wcard has-dist' data-km='" + km + "'>" +
            "<div class='px-wcard-img'>" + img +
            "<div class='px-wcard-top'><span class='px-dist'><i class='bx bx-navigation'></i><span class='px-dist-text'>" +
            esc(window.GW.formatDistance(km)) + " away</span></span></div></div>" +
            "<div class='px-wcard-body'><h3>" + esc(w.name) + '</h3>' +
            "<p class='px-addr'><i class='bx bx-map'></i><span>" + esc(w.address || 'Nearby') + '</span></p>' +
            "<div class='px-wcard-foot'>View workshop <i class='bx bx-right-arrow-alt'></i></div></div></a>"
        );
    }

    async function loadNearby(forceFresh) {
        setChip('loading');
        if (section && grid && status) {
            status.hidden = true;
            grid.hidden = false;
            grid.innerHTML = "<div class='px-card px-skel'></div><div class='px-card px-skel'></div><div class='px-card px-skel'></div>";
        }
        let loc;
        try {
            loc = await window.GW.getLocation(forceFresh);
        } catch (e) {
            setChip('off');
            showStatus('bx-current-location', 'Location is off',
                'Allow location access to see the workshops closest to you and how far each one is.', true);
            return;
        }

        setChip('ok');
        window.GW.fillDistances(document, loc);   // recommended cards get their distance pills

        if (!section) return;
        try {
            const res = await fetch((section.dataset.url || '/workshops/nearby') + '?lat=' + loc.lat + '&lng=' + loc.lng);
            if (!res.ok) throw new Error('Bad response');
            const data = await res.json();
            if (!data.length) {
                showStatus('bx-map-pin', 'No workshops within 25 km',
                    'There are no listed workshops close to you yet. You can still browse all of them.', false);
                return;
            }
            status.hidden = true;
            grid.hidden = false;
            grid.innerHTML = data.map(card).join('');
        } catch (e) {
            console.error('Could not load nearby workshops:', e);
            showStatus('bx-error-circle', 'Could not load nearby workshops', 'Please refresh the page to try again.', false);
        }
    }

    document.addEventListener('click', (e) => {
        if (e.target.closest('[data-enable-location]')) loadNearby(true);
    });

    if (navigator.geolocation) {
        loadNearby(false);
    } else {
        setChip('off');
        showStatus('bx-current-location', 'Location is not available', 'Your browser does not support location access.', false);
    }
})();