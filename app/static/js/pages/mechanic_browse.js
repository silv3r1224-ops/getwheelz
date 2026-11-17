/* ==================================================================
   mechanic_browse.js — extracted from app/templates/mechanics/browse.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

(function () {
    const page = document.querySelector('.mechanic-browse-page');
    if (!page || !document.getElementById('browseSearch')) return;

    const search = document.getElementById('browseSearch');
    const chips = document.querySelectorAll('#serviceChips .chip');
    const sections = page.querySelectorAll('.browse-section');
    const noMatches = document.getElementById('noMatches');
    let activeService = '';

    // ---------- filtering (search box + service chips) ----------
    function applyFilters() {
        const q = search.value.trim().toLowerCase();
        let anyVisible = false;

        sections.forEach(sec => {
            if (sec.id === 'nearbyWorkshops' && !sec.dataset.ready) return;   // not populated yet
            const cards = sec.querySelectorAll('.workshop-join-card');
            let shown = 0;
            cards.forEach(card => {
                const d = card.dataset;
                const matchText = !q || d.name.includes(q) || d.address.includes(q);
                const matchService = !activeService || d.services.split('|').includes(activeService);
                const show = matchText && matchService;
                card.hidden = !show;
                if (show) shown++;
            });
            // sections with cards hide when nothing matches; the "hiring" empty message stays
            if (cards.length) sec.hidden = shown === 0;
            if (shown) anyVisible = true;
        });

        if (noMatches) noMatches.hidden = anyVisible;
    }

    search.addEventListener('input', applyFilters);
    chips.forEach(chip => chip.addEventListener('click', () => {
        chips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        activeService = chip.dataset.service;
        applyFilters();
    }));

    // ---------- click a card to open the workshop profile ----------
    page.addEventListener('click', (e) => {
        const card = e.target.closest('.workshop-join-card[data-href]');
        if (!card) return;
        if (e.target.closest('form, button, a')) return;   // buttons and links keep their own behaviour
        window.location.href = card.dataset.href;
    });

    // ---------- nearby: distance computed in the browser ----------
    const nearbySection = document.getElementById('nearbyWorkshops');
    const nearbyList = document.getElementById('nearbyList');
    const nearbyCount = document.getElementById('nearbyCount');
    const nearbyLink = document.getElementById('nearbyLink');

    const toRad = (d) => d * Math.PI / 180;
    function km(lat1, lng1, lat2, lng2) {
        const a = Math.sin(toRad(lat2 - lat1) / 2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(toRad(lng2 - lng1) / 2) ** 2;
        return 6371 * 2 * Math.asin(Math.sqrt(a));
    }

    if (nearbySection && navigator.geolocation) {
        navigator.geolocation.getCurrentPosition((pos) => {
            const { latitude, longitude } = pos.coords;
            const seen = new Set();
            const found = [];

            // collect each workshop once, from the server-rendered sections
            page.querySelectorAll('.browse-section:not(#nearbyWorkshops) .workshop-join-card').forEach(card => {
                const lat = parseFloat(card.dataset.lat);
                const lng = parseFloat(card.dataset.lng);
                if (isNaN(lat) || isNaN(lng) || seen.has(card.dataset.wid)) return;
                seen.add(card.dataset.wid);
                found.push({ card, dist: km(latitude, longitude, lat, lng) });
            });

            if (!found.length) return;
            found.sort((a, b) => a.dist - b.dist);

            found.slice(0, 6).forEach(({ card, dist }) => {
                const clone = card.cloneNode(true);
                clone.hidden = false;
                const badge = clone.querySelector('.distance-badge');
                badge.textContent = (dist < 10 ? dist.toFixed(1) : Math.round(dist)) + ' km away';
                badge.hidden = false;
                nearbyList.appendChild(clone);
            });

            nearbyCount.textContent = Math.min(6, found.length);
            nearbySection.dataset.ready = '1';
            nearbySection.hidden = false;
            if (nearbyLink) nearbyLink.hidden = false;
            applyFilters();
        }, () => { /* permission denied: the Nearby section simply stays hidden */ },
        { timeout: 10000, maximumAge: 300000 });
    }
})();
