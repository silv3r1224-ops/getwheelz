/* ==================================================================
   profile_settings_tab.js — extracted from app/templates/dashboard/profile.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    // arriving from the delete-account check (#settings): open the Settings tab straight away
    window.addEventListener('DOMContentLoaded', function () {
        if (location.hash === '#settings') {
            var tab = document.querySelector('[data-tab-btn="settingsTab"]');
            if (tab) setTimeout(function () { tab.click(); }, 0);
        }
    });
