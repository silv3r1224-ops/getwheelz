/* ==================================================================
   workshops_search_measure.js — extracted from app/templates/workshops/search.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    // When the server did not get coordinates, measure from the browser instead and sort nearest first.
    (function () {
        const chip = document.getElementById('loc-chip');
        const list = document.getElementById('workshop-list');
        const note = document.getElementById('sort-note');
        const enable = document.getElementById('enable-location');
        if (!chip || !window.GW) return;
        if (presetUserLat !== null) return;   // distances already came from the server

        const text = chip.querySelector('.loc-text');
        function off() { text.textContent = 'Turn on location to see distances'; enable.hidden = false; }

        function run(force) {
            text.textContent = 'Finding your location...';
            enable.hidden = true;
            window.GW.getLocation(force).then(function (loc) {
                chip.classList.add('ok');
                text.textContent = 'Distances measured from your location';
                // Ranking (distance blended with ratings) is done on the server in app/ranking.py, so
                // reload once with the coordinates instead of re-sorting here with a second formula.
                // presetUserLat is null only on the first load, so this cannot loop.
                const url = new URL(window.location.href);
                url.searchParams.set('lat', loc.lat.toFixed(5));
                url.searchParams.set('lng', loc.lng.toFixed(5));
                if (window.GWLive) window.GWLive.replace(url.toString()).then(function (done) { if (done !== true) window.location.replace(url.toString()); });
                else window.location.replace(url.toString());
            }).catch(off);
        }

        enable.addEventListener('click', function () { run(true); });
        run(false);
    })();
