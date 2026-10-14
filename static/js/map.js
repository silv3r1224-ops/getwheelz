const escHtml = (v) => String(v ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

document.addEventListener('DOMContentLoaded', () => {
    const mapContainer = document.getElementById('map');
    if (!mapContainer || typeof workshopData === 'undefined') return;

    // Home page sets `mapCenterOnUser = true`: the map opens already showing the visitor's location.
    const centerOnUser = typeof mapCenterOnUser !== 'undefined' && mapCenterOnUser;
    // Home page sets `mapClickToInteract = true`: map stays locked until it is clicked.
    const lockedUntilClick = typeof mapClickToInteract !== 'undefined' && mapClickToInteract;

    const USER_ZOOM = 15;        // zoom level when showing the user's location
    const WAIT_MS = 5000;        // how long to wait for location before showing the map anyway

    let map = null;
    let pendingCoords = null;    // location that arrived after the map was already built

    if (centerOnUser && navigator.geolocation) {
        mapContainer.innerHTML = '<div class="map-loading"><i class="bx bx-loader-alt bx-spin"></i> Finding your location...</div>';

        // never leave the visitor staring at a blank box if they ignore the permission prompt
        const fallbackTimer = setTimeout(() => buildMap(null), WAIT_MS);

        navigator.geolocation.getCurrentPosition(
            (pos) => {
                clearTimeout(fallbackTimer);
                if (map) showUser(pos.coords.latitude, pos.coords.longitude, true);  // arrived late
                else buildMap(pos.coords);
            },
            () => {
                clearTimeout(fallbackTimer);
                if (!map) buildMap(null);   // denied or unavailable: show the workshops
            },
            { timeout: 10000, maximumAge: 300000 }
        );
    } else {
        buildMap(null);
    }

    // -------------------------------------------------------------------------------------------
    let userMarker = null;
    const userIcon = L.divIcon({
        className: 'user-location-marker',
        html: '<div class="user-dot"></div><div class="user-pulse"></div>',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
    });

    function showUser(lat, lng, zoomTo) {
        if (userMarker) {
            userMarker.setLatLng([lat, lng]);
        } else {
            userMarker = L.marker([lat, lng], { icon: userIcon })
                .addTo(map)
                .bindPopup('You are here');
        }
        if (zoomTo) map.setView([lat, lng], USER_ZOOM);
    }

    function locateUser(zoomTo) {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(
            (position) => showUser(position.coords.latitude, position.coords.longitude, zoomTo),
            (error) => console.log('Location access denied or unavailable:', error.message)
        );
    }

    function buildMap(userCoords) {
        mapContainer.innerHTML = '';

        let centerLat = 26.1445;
        let centerLng = 91.7362;

        const validWorkshops = workshopData.filter(w => w.lat && w.lng);
        if (validWorkshops.length > 0) {
            centerLat = validWorkshops[0].lat;
            centerLng = validWorkshops[0].lng;
        }

        // start directly on the user's location when we have it, otherwise on the workshops
        const startView = userCoords
            ? [[userCoords.latitude, userCoords.longitude], USER_ZOOM]
            : [[centerLat, centerLng], 12];

        map = L.map('map', lockedUntilClick ? {
            dragging: false,
            scrollWheelZoom: false,
            touchZoom: false,
            doubleClickZoom: false,
            boxZoom: false,
            keyboard: false,
        } : {}).setView(startView[0], startView[1]);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19,
        }).addTo(map);

        if (lockedUntilClick) {
            const hint = document.createElement('div');
            hint.className = 'map-hint';
            hint.textContent = 'Click the map to interact';
            mapContainer.appendChild(hint);

            const handlers = ['dragging', 'scrollWheelZoom', 'touchZoom', 'doubleClickZoom', 'boxZoom', 'keyboard'];
            const setInteractive = (on) => {
                handlers.forEach(h => (on ? map[h].enable() : map[h].disable()));
                hint.classList.toggle('hidden', on);
                mapContainer.classList.toggle('map-active', on);
            };

            // first click unlocks (capture so it also works when the click lands on a marker)
            mapContainer.addEventListener('click', () => setInteractive(true), true);

            // lock again when the pointer leaves, or the user clicks elsewhere on the page
            mapContainer.addEventListener('mouseleave', () => setInteractive(false));
            document.addEventListener('click', (e) => {
                if (!mapContainer.contains(e.target)) setInteractive(false);
            });
        }

        const markers = [];
        validWorkshops.forEach(w => {
            const marker = L.marker([w.lat, w.lng])
                .addTo(map)
                .bindPopup(`
                    <strong>${escHtml(w.name)}</strong><br>
                    ${escHtml(w.address)}<br>
                    <a href="/workshops/${w.id}">View details</a>
                `);
            markers.push(marker);
        });

        // ---- custom "locate me" button control ----
        const LocateControl = L.Control.extend({
            options: { position: 'topright' },
            onAdd: function () {
                const container = L.DomUtil.create('div', 'leaflet-bar leaflet-control locate-control');
                container.innerHTML = `<a href="#" title="Go to my location"><i class='bx bx-current-location'></i></a>`;

                L.DomEvent.disableClickPropagation(container);
                L.DomEvent.on(container, 'click', (e) => {
                    e.preventDefault();
                    locateUser(true);
                });

                return container;
            },
        });
        map.addControl(new LocateControl());

        if (userCoords) {
            // already centred on the user: just add their dot
            showUser(userCoords.latitude, userCoords.longitude, false);
        } else if (centerOnUser) {
            // home page without a location yet: show all workshops, nothing else to do
            if (markers.length > 1) {
                map.fitBounds(L.featureGroup(markers).getBounds().pad(0.2));
            }
        } else {
            // other pages (e.g. search): keep the workshop view, only jump to the user if there are no workshops
            locateUser(validWorkshops.length === 0);
            if (markers.length > 1) {
                map.fitBounds(L.featureGroup(markers).getBounds().pad(0.2));
            }
        }
    }
});