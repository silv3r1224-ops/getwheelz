// Shared distance helpers for the customer pages.
//
// Elements that carry data-lat / data-lng (a workshop card, a list row, the workshop banner) get
// their ".px-dist" pill filled in once the visitor's location is known. The location is cached
// in sessionStorage for 10 minutes so moving between pages does not ask for permission again.

window.GW = window.GW || {};

(function (GW) {
    const KEY = 'gw_location_v1';
    const TTL_MS = 10 * 60 * 1000;

    // great-circle distance in kilometres
    GW.haversine = function (lat1, lon1, lat2, lon2) {
        const rad = (d) => (d * Math.PI) / 180;
        const dLat = rad(lat2 - lat1);
        const dLon = rad(lon2 - lon1);
        const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
        return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    };

    // "450 m", "3.2 km", "27 km"
    GW.formatDistance = function (km) {
        if (km < 1) return Math.max(10, Math.round((km * 1000) / 10) * 10) + ' m';
        if (km < 10) return km.toFixed(1) + ' km';
        return Math.round(km) + ' km';
    };

    GW.cachedLocation = function () {
        try {
            const v = JSON.parse(sessionStorage.getItem(KEY));
            if (v && Date.now() - v.t < TTL_MS) return v;
        } catch (e) { /* storage blocked or empty */ }
        return null;
    };

    // Resolves {lat, lng}; rejects when the browser has no location support or the visitor says no.
    GW.getLocation = function (forceFresh) {
        return new Promise((resolve, reject) => {
            const cached = forceFresh ? null : GW.cachedLocation();
            if (cached) return resolve(cached);
            if (!navigator.geolocation) return reject(new Error('unsupported'));
            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    const v = { lat: pos.coords.latitude, lng: pos.coords.longitude, t: Date.now() };
                    try { sessionStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* ignore */ }
                    resolve(v);
                },
                (err) => reject(err),
                { timeout: 10000, maximumAge: 300000 }
            );
        });
    };

    // Fill the distance pill of every [data-lat][data-lng] element under root.
    GW.fillDistances = function (root, loc) {
        (root || document).querySelectorAll('[data-lat][data-lng]').forEach((el) => {
            const lat = parseFloat(el.dataset.lat);
            const lng = parseFloat(el.dataset.lng);
            if (Number.isNaN(lat) || Number.isNaN(lng)) return;
            const km = GW.haversine(loc.lat, loc.lng, lat, lng);
            el.dataset.km = km.toFixed(3);
            el.querySelectorAll('.px-dist-text').forEach((t) => { t.textContent = GW.formatDistance(km) + ' away'; });
            el.classList.add('has-dist');
        });
    };

    // Re-order the children of a container nearest-first (children without a distance go last).
    GW.sortByDistance = function (container, childSelector) {
        const items = Array.from(container.querySelectorAll(childSelector));
        items.sort((a, b) => {
            const ka = a.dataset.km === undefined ? Infinity : parseFloat(a.dataset.km);
            const kb = b.dataset.km === undefined ? Infinity : parseFloat(b.dataset.km);
            return ka - kb;
        });
        items.forEach((el) => container.appendChild(el));
    };
})(window.GW);