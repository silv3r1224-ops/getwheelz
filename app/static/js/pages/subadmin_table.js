/* ==================================================================
   subadmin_table.js — extracted from app/templates/dashboard/subadmin.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    (function () {
        const body = document.getElementById('saBody');
        if (!body) return;

        const allRows = Array.from(body.querySelectorAll('tr[data-row]'));
        // rows deleted from the page (single or bulk delete) must not be re-added when re-sorting
        const liveRows = () => allRows.filter(row => row.isConnected);
        const search = document.getElementById('saSearch');
        const sort = document.getElementById('saSort');
        const count = document.getElementById('saCount');
        const noMatch = document.getElementById('saNoMatch');

        function apply() {
            const term = search.value.trim().toLowerCase();
            const mode = sort.value;

            const rows = liveRows();
            const ordered = rows.slice().sort((a, b) => {
                if (mode === 'name') return a.dataset.name.localeCompare(b.dataset.name);
                if (mode === 'old') return a.dataset.joined.localeCompare(b.dataset.joined);
                return b.dataset.joined.localeCompare(a.dataset.joined);   // newest first
            });

            let shown = 0;
            ordered.forEach(row => {
                const match = !term || row.dataset.search.includes(term);
                row.hidden = !match;
                if (match) shown++;
                body.appendChild(row);
            });

            count.textContent = 'Showing ' + shown + ' of ' + rows.length;
            noMatch.hidden = shown !== 0;
        }

        document.addEventListener('admin:rows-changed', apply);
        search.addEventListener('input', apply);
        sort.addEventListener('change', apply);
        apply();

        // put the person's name into the delete pop-up (admin.js opens it)
        const msg = document.getElementById('deleteMsg');
        const original = msg ? msg.textContent.trim() : '';
        document.addEventListener('click', function (e) {
            const trigger = e.target.closest ? e.target.closest('.deleteAcc') : null;
            if (trigger && msg) {
                msg.textContent = (trigger.dataset.name ? trigger.dataset.name + ': ' : '') + original;
            }
        });
    })();
