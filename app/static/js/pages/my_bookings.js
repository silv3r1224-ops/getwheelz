/* ==================================================================
   my_bookings.js — extracted from app/templates/bookings/my_bookings.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    (function () {
        const bar = document.getElementById('booking-filter');
        const list = document.getElementById('booking-list');
        const empty = document.getElementById('booking-empty');
        if (!bar || !list) return;
        bar.addEventListener('click', function (e) {
            const btn = e.target.closest('button[data-filter]');
            if (!btn) return;
            bar.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
            const f = btn.dataset.filter;
            let shown = 0;
            list.querySelectorAll('.px-booking').forEach((card) => {
                const show = f === 'all' || (f === 'topay' ? card.dataset.pay === '1' : card.dataset.group === f);
                card.hidden = !show;
                if (show) shown++;
            });
            empty.hidden = shown !== 0;
        });
    })();
