// Customer home: recommended carousel, location status, and the nearby-workshops grid.
// Distances come from distance.js (window.GW), which must be loaded first.

(function () {
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // ---------- Recommended carousel: continuous glide (marquee) ----------
    // The strip glides left forever inside a clipped window and loops
    // seamlessly: the track holds identical sets of cards, and the CSS
    // animation translates it by exactly one set width (--ticker-shift), so
    // the end of one set meets the start of the next. Hover, focus and touch
    // pause it; the page being hidden pauses it too.
    const track = document.getElementById('rec-track');

    if (track) {
        // On mobile views (or generally), keep the track as a static grid / list if requested.
        // We ensure any continuous glide animation classes are removed so it stays stationary.
        track.classList.remove('px-ticker-ready');
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
        const href = w.url || profileUrl;
        const img = w.photo_url
            ? "<span class='px-card-photo-open' role='button' tabindex='0' aria-label='View " + esc(w.name) + " photo' data-wp-lightbox>" +
              "<img src='" + staticUrl + esc(w.photo_url) + "' alt='" + esc(w.name) + "' loading='lazy' data-wp-photo>" +
              "<span class='px-photo-zoom' aria-hidden='true'><i class='bx bx-expand'></i></span></span>"
            : "<div class='px-ph'><i class='bx bx-store'></i></div>";
        const km = Number(w.distance_km);
        const payload = {
            id: w.w_id,
            name: w.name,
            address: w.address || '',
            photo: w.photo_url ? staticUrl + esc(w.photo_url) : '',
            open: !!w.is_open,
            km: km,
            services: [],
            team: w.team || [],
            url: href,
            lat: null,
            lng: null
        };
        const wpJson = esc(JSON.stringify(payload));
        const bm = window.GW_CUSTOMER
            ? "<span class='px-bm " + (w.bookmarked ? "on" : "") + "' role='button' tabindex='0' aria-label='" +
              (w.bookmarked ? "Remove from saved workshops" : "Save this workshop") +
              "' aria-pressed='" + (w.bookmarked ? "true" : "false") +
              "' data-bm data-w-id='" + w.w_id + "'><i class='bx " +
              (w.bookmarked ? "bxs-bookmark" : "bx-bookmark") + "'></i><span class='bm-label'>" +
              (w.bookmarked ? "Saved" : "Save") + "</span></span>"
            : "";
        return (
            "<a href='" + href + "' class='px-card px-lift px-wcard has-dist' data-km='" + km + "'>" +
            "<div class='px-wcard-img'>" + img +
            "<div class='px-wcard-top'><span class='px-dist'><i class='bx bx-navigation'></i><span class='px-dist-text'>" +
            esc(window.GW.formatDistance(km)) + " away</span></span></div>" + bm + "</div>" +
            "<div class='px-wcard-body'><h3>" + esc(w.name) + '</h3>' +
            "<p class='px-addr'><i class='bx bx-map'></i><span>" + esc(w.address || 'Nearby') + '</span></p>' +
            "<span class='px-quickview' role='button' tabindex='0' aria-label='Quick view " + esc(w.name) +
            "' aria-expanded='false' data-wp='" + wpJson + "'><i class='bx bx-show'></i> Quick view</span>" +
            "<div class='px-wcard-foot'>View workshop <i class='bx bx-right-arrow-alt'></i></div></div></a>"
        );
    }

    let loadId = 0;
    // silent = a live refresh (see live.js): keep what is on screen until the new list arrives, and never show errors
    async function loadNearby(forceFresh, silent) {
        const myLoad = ++loadId;
        if (!silent) setChip('loading');
        if (!silent && section && grid && status) {
            status.hidden = true;
            grid.hidden = false;
            grid.innerHTML = "<div class='px-card px-skel'></div><div class='px-card px-skel'></div><div class='px-card px-skel'></div>";
        }
        let loc;
        try {
            loc = await window.GW.getLocation(forceFresh);
        } catch (e) {
            if (silent) return;
            setChip('off');
            showStatus('bx-current-location', 'Location is off',
                'Allow location access to see the workshops closest to you and how far each one is.', true);
            return;
        }

        if (myLoad !== loadId) return;            // a newer load started meanwhile
        setChip('ok');
        window.GW.fillDistances(document, loc);   // recommended cards get their distance pills

        // Keep the quick-view payloads on the recommended cards in sync with the
        // distance pills just filled (the server template can't know distances).
        document.querySelectorAll('#rec-track [data-wp]').forEach((el) => {
            const card = el.closest('.px-wcard');
            const km = card ? parseFloat(card.dataset.km) : NaN;
            if (Number.isNaN(km)) return;
            try {
                const p = JSON.parse(el.getAttribute('data-wp'));
                p.km = km;
                el.setAttribute('data-wp', JSON.stringify(p));
            } catch { /* leave the payload as-is */ }
        });

        if (!section) return;
        try {
            const res = await fetch((section.dataset.url || '/workshops/nearby') + '?lat=' + loc.lat + '&lng=' + loc.lng);
            if (!res.ok) throw new Error('Bad response');
            const data = await res.json();
            if (myLoad !== loadId) return;
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
            if (silent) return;
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
    // the page was patched in place (vehicle switch, someone else's change): refresh the nearby list too
    document.addEventListener('gw:live-updated', () => {
        if (section && navigator.geolocation) loadNearby(false, true);
    });
})();
