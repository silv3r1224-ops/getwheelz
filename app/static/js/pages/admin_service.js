/* ==================================================================
   admin_service.js — extracted from app/templates/dashboard/admin_service.html (inline <script>).
   Pure DOM logic; data comes from data-* attributes in the template.
   ================================================================== */
(function () {
        const body = document.getElementById('catBody');
        if (!body) return;

        const rows = Array.from(body.querySelectorAll('tr[data-row]'));
        const search = document.getElementById('catSearch');
        const sort = document.getElementById('catSort');
        const count = document.getElementById('catCount');
        const noMatch = document.getElementById('catNoMatch');

        function apply() {
            const term = search.value.trim().toLowerCase();
            const mode = sort.value;

            const ordered = rows.slice().sort((a, b) => {
                const an = a.dataset.name, bn = b.dataset.name;
                const au = +a.dataset.used, bu = +b.dataset.used;
                if (mode === 'name-desc') return bn.localeCompare(an);
                if (mode === 'used-desc') return bu - au || an.localeCompare(bn);
                if (mode === 'used-asc') return au - bu || an.localeCompare(bn);
                return an.localeCompare(bn);
            });

            let shown = 0;
            ordered.forEach(row => {
                const match = !term || row.dataset.name.includes(term);
                row.hidden = !match;
                if (match) shown++;
                body.appendChild(row);
            });

            count.textContent = 'Showing ' + shown + ' of ' + rows.length;
            noMatch.hidden = shown !== 0;
        }

        search.addEventListener('input', apply);
        sort.addEventListener('change', apply);
        apply();

        // inline rename
        function stopEditing(row) { row.classList.remove('is-editing'); }

        body.addEventListener('click', function (e) {
            const edit = e.target.closest('[data-edit]');
            if (edit) {
                body.querySelectorAll('tr.is-editing').forEach(stopEditing);
                const row = edit.closest('tr');
                row.classList.add('is-editing');
                const input = row.querySelector('.cat-edit-form input[name="s_name"]');
                input.focus();
                input.select();
                return;
            }
            const cancel = e.target.closest('[data-cancel-edit]');
            if (cancel) stopEditing(cancel.closest('tr'));
        });

        body.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                const row = e.target.closest('tr.is-editing');
                if (row) stopEditing(row);
            }
        });

        // put the service name into the remove pop-up (admin.js opens it)
        const msg = document.getElementById('deleteMsg');
        document.addEventListener('click', function (e) {
            const trigger = e.target.closest ? e.target.closest('.deleteAcc') : null;
            if (trigger && msg) {
                msg.textContent = '"' + (trigger.dataset.name || 'This service') + '" will be removed from the catalog.';
            }
        });
    })();