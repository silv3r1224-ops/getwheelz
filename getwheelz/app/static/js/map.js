document.addEventListener('DOMContentLoaded', () => {
    const mapContainer = document.getElementById('map');
    if (!mapContainer || typeof workshopData === 'undefined') return;

    let centerLat = 26.1445;
    let centerLng = 91.7362;

    const validWorkshops = workshopData.filter(w => w.lat && w.lng);
    if (validWorkshops.length > 0) {
        centerLat = validWorkshops[0].lat;
        centerLng = validWorkshops[0].lng;
    }

    const map = L.map('map').setView([centerLat, centerLng], 12);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
    }).addTo(map);

    const markers = [];
    validWorkshops.forEach(w => {
        const marker = L.marker([w.lat, w.lng])
            .addTo(map)
            .bindPopup(`
                <strong>${w.name}</strong><br>
                ${w.address}<br>
                <a href="/workshops/${w.id}">View details</a>
            `);
        markers.push(marker);
    });

    const userIcon = L.divIcon({
        className: 'user-location-marker',
        html: '<div class="user-dot"></div><div class="user-pulse"></div>',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
    });

    let userMarker = null;

    function locateUser(zoomTo) {
        if (!navigator.geolocation) return;

        navigator.geolocation.getCurrentPosition(
            (position) => {
                const userLat = position.coords.latitude;
                const userLng = position.coords.longitude;

                if (userMarker) {
                    userMarker.setLatLng([userLat, userLng]);
                } else {
                    userMarker = L.marker([userLat, userLng], { icon: userIcon })
                        .addTo(map)
                        .bindPopup('You are here');
                }

                if (zoomTo) {
                    map.setView([userLat, userLng], 15);
                }
            },
            (error) => {
                console.log('Location access denied or unavailable:', error.message);
            }
        );
    }

    // run once on load, without forcing the zoom (keeps workshop view as primary)
    locateUser(validWorkshops.length === 0);

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

    if (markers.length > 1) {
        const group = L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.2));
    }
});