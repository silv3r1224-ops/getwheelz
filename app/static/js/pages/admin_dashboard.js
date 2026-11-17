/* ==================================================================
   admin_dashboard.js — extracted from app/templates/dashboard/admin.html (inline <script>).
   Pure DOM logic; data comes from data-* attributes in the template.
   ================================================================== */
(function () {
                var el = document.getElementById('adminDate');
                if (el) el.textContent = new Date().toLocaleDateString(undefined,
                    { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
            })();