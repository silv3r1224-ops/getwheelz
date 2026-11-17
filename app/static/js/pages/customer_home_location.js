/* ==================================================================
   customer_home_location.js — extracted from app/templates/customer/home.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    // reuse a location we already have so the search results page can show distances straight away
    (function () {
        var loc = window.GW && window.GW.cachedLocation();
        if (loc) {
            document.getElementById('search-lat').value = loc.lat;
            document.getElementById('search-lng').value = loc.lng;
        }
    })();
