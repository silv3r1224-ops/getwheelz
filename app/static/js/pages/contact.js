/* ==================================================================
   contact.js — extracted from app/templates/contact.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    document.addEventListener('DOMContentLoaded', () => {
        const mapEl = document.getElementById('contact-map');
        if (!mapEl || typeof L === 'undefined') return;

        const map = L.map('contact-map', {
            zoomControl: false,
            scrollWheelZoom: false,
        }).setView([26.1445, 91.7362], 13);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
        }).addTo(map);

        L.marker([26.1445, 91.7362]).addTo(map).bindPopup('Getwheelz HQ');
    });
