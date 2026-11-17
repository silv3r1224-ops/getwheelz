/* ==================================================================
   workshop_selected_map.js — extracted from app/templates/workshops/selected.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    document.addEventListener('DOMContentLoaded', () => {
        if (workshopLat !== null && workshopLng !== null) {
            const map = L.map('profile-map').setView([workshopLat, workshopLng], 15);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors'
            }).addTo(map);
            L.marker([workshopLat, workshopLng]).addTo(map).bindPopup(workshopName);

            // how far is it from where the visitor is right now?
            const banner = document.querySelector('.px-banner');
            if (banner && window.GW) {
                window.GW.getLocation(false).then((loc) => window.GW.fillDistances(banner, loc)).catch(() => { /* no location: pill stays hidden */ });
            }
        }
    });
