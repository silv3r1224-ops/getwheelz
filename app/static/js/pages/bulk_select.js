/* ==================================================================
   bulk_select.js - multi-select + bulk delete for the admin account tables.

   Markup contract (see admin.html / subadmin.html / admin.js):
     <table data-bulk-role="customer|owner|mechanic|mixed"
            data-bulk-url="/dashboard/admin/terminate-bulk"
            data-csrf="..."
            data-empty-text="optional - replaces the table once its last row is deleted">
       <th class="bulk-col"><input type="checkbox" class="bulk-all"></th>
       <tr data-uid="12" data-label="Person name" data-role="owner">
         <td class="bulk-col"><input type="checkbox" class="bulk-pick"></td>

   data-role is only needed on the rows of a "mixed" table (the admin's Advanced Search results, which
   can hold customers, owners and mechanics together). The server deletes one role per request, so a
   mixed selection is grouped by role and sent as one request per role (and per 200 accounts).

   Behaviour
     - header checkbox selects / clears every VISIBLE row (rows hidden by a search filter are never touched)
     - shift-click selects a range; Esc clears the selection
     - a selection bar appears while anything is selected
     - one confirm dialog -> a few requests -> a clear result summary
     - owners whose workshop holds live data are listed separately and need a second, explicit confirmation
     - deleted accounts disappear from EVERY table on the page (search results and the full lists alike)
     - tables added later (search results) are picked up automatically via #adminSearchResults
   All names shown come from the DOM / server and are inserted with textContent only (never innerHTML).
   ================================================================== */
(function () {
    'use strict';

    const searchBox = document.getElementById('adminSearchResults'); // live-search results are swapped in here
    if (!document.querySelector('table[data-bulk-role]') && !searchBox) return;

    const CHUNK = 200; // must not exceed BULK_LIMIT on the server
    const ROLES = ['customer', 'owner', 'mechanic'];
    const NOUN = {
        customer: ['customer', 'customers'],
        owner: ['owner', 'owners'],
        mechanic: ['mechanic', 'mechanics'],
        mixed: ['account', 'accounts'],
    };

    const tables = new Set();        // every table currently managed (search results come and go)
    const observers = new WeakMap(); // table -> MutationObserver on its body
    const counts = new WeakMap();    // table -> { visible, picked } from the last sync

    let active = null;       // the table that currently holds the selection
    let lastPicked = null;   // anchor for shift-click ranges
    let busy = false;

    /* ---------------------------------------------------------- tiny DOM helpers */
    function el(tag, attrs, children) {
        const node = document.createElement(tag);
        Object.keys(attrs || {}).forEach((key) => {
            if (key === 'class') node.className = attrs[key];
            else if (key === 'text') node.textContent = attrs[key];
            else node.setAttribute(key, attrs[key]);
        });
        (children || []).forEach((child) => node.appendChild(child));
        return node;
    }

    const plural = (role, n) => NOUN[role][n === 1 ? 0 : 1];
    const rowsOf = (table) =>
        Array.from(table.tBodies[0] ? table.tBodies[0].rows : []).filter((r) => r.dataset.uid);
    const pickOf = (row) => row.querySelector('.bulk-pick');
    const selectedRows = (table) => rowsOf(table).filter((r) => !r.hidden && pickOf(r) && pickOf(r).checked);
    const labelOf = (row) => row.dataset.label || 'Account ' + row.dataset.uid;
    // a mixed table carries the role on each row; the other tables carry it on the table itself
    const roleOf = (table, row) => row.dataset.role || table.dataset.bulkRole;

    function uncheckAll(table) {
        rowsOf(table).forEach((row) => {
            if (pickOf(row)) pickOf(row).checked = false;
        });
    }

    /* ---------------------------------------------------------- selection bar */
    const barCount = el('strong', { class: 'bulk-count', text: '0 selected' });
    const barHint = el('span', { class: 'bulk-hint' });
    const clearBtn = el('button', { type: 'button', class: 'bulk-btn ghost', text: 'Clear' });
    const deleteBtn = el('button', { type: 'button', class: 'bulk-btn danger' }, [
        el('i', { class: 'bx bx-trash', 'aria-hidden': 'true' }),
        el('span', { text: 'Delete selected' }),
    ]);
    const bar = el(
        'div',
        { class: 'bulk-bar', role: 'region', 'aria-label': 'Selected accounts', hidden: '' },
        [el('div', { class: 'bulk-bar-info' }, [barCount, barHint]), el('div', { class: 'bulk-bar-actions' }, [clearBtn, deleteBtn])]
    );
    document.body.appendChild(bar);

    /* ---------------------------------------------------------- dialog */
    const dTitle = el('h2', { id: 'bulkDlgTitle' });
    const dText = el('p', { class: 'bulk-dlg-text' });
    const dList = el('ul', { class: 'bulk-dlg-list' });
    const dCancel = el('button', { type: 'button', class: 'bulk-btn ghost' });
    const dOk = el('button', { type: 'button', class: 'bulk-btn danger' });
    const dActions = el('div', { class: 'bulk-dlg-actions' }, [dCancel, dOk]);
    const dialog = el(
        'div',
        { class: 'bulk-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'bulkDlgTitle' },
        [dTitle, dText, dList, dActions]
    );
    const overlay = el('div', { class: 'bulk-overlay', hidden: '' }, [dialog]);
    document.body.appendChild(overlay);

    let dialogResolve = null;
    let returnFocus = null;

    function fillDialog(opts) {
        dTitle.textContent = opts.title || '';
        dText.textContent = opts.text || '';
        dText.hidden = !opts.text;
        dList.textContent = '';
        (opts.items || []).forEach((line) => dList.appendChild(el('li', { text: line })));
        dList.hidden = !(opts.items && opts.items.length);
    }

    function openOverlay() {
        if (overlay.hidden) {
            returnFocus = document.activeElement;
            overlay.hidden = false;
            document.body.classList.add('bulk-modal-open');
        }
    }

    function closeDialog() {
        overlay.hidden = true;
        document.body.classList.remove('bulk-modal-open');
        if (returnFocus && returnFocus.focus && document.contains(returnFocus)) returnFocus.focus();
        returnFocus = null;
    }

    /** Ask a question. Resolves true (confirm) / false (cancel, Esc, backdrop). */
    function ask(opts) {
        fillDialog(opts);
        dActions.hidden = false;
        dCancel.hidden = !!opts.onlyClose;
        dCancel.textContent = opts.cancelLabel || 'Cancel';
        dOk.textContent = opts.confirmLabel || 'OK';
        dOk.className = 'bulk-btn ' + (opts.danger ? 'danger' : 'primary');
        dialog.classList.remove('is-busy');
        openOverlay();
        (opts.onlyClose ? dOk : dCancel).focus(); // the safe choice is focused by default
        return new Promise((resolve) => {
            dialogResolve = resolve;
        });
    }

    function showBusy(text) {
        fillDialog({ title: text, text: 'Please keep this page open.' });
        dActions.hidden = true;
        dialog.classList.add('is-busy');
        openOverlay();
    }

    function answer(value) {
        const resolve = dialogResolve;
        dialogResolve = null;
        if (resolve) {
            resolve(value);
        }
    }

    dOk.addEventListener('click', () => answer(true));
    dCancel.addEventListener('click', () => answer(false));
    overlay.addEventListener('mousedown', (event) => {
        if (event.target === overlay && dialogResolve) answer(false);
    });

    document.addEventListener('keydown', (event) => {
        if (overlay.hidden) {
            if (event.key === 'Escape' && active && !busy) clearSelection();
            return;
        }
        if (event.key === 'Escape') {
            if (dialogResolve) answer(false);
            return;
        }
        if (event.key === 'Tab' && !dActions.hidden) {
            const focusable = [dCancel, dOk].filter((b) => !b.hidden);
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    });

    /* ---------------------------------------------------------- selection state */
    // One pass over one table: drop selections on rows that are no longer visible (an admin must never
    // delete a row they cannot see), mark selected rows, and update the header checkbox.
    function syncTable(table) {
        let visible = 0;
        let picked = 0;
        const body = table.tBodies[0];
        const rows = body ? body.rows : [];
        for (let i = 0; i < rows.length; i++) {
            const row = rows[i];
            if (!row.dataset.uid) continue;
            const box = pickOf(row);
            if (row.hidden && box && box.checked) box.checked = false;
            const on = !!box && box.checked;
            row.classList.toggle('is-selected', on);
            if (!row.hidden) {
                visible += 1;
                if (on) picked += 1;
            }
        }
        const all = table.querySelector('.bulk-all');
        if (all) {
            all.checked = visible > 0 && picked === visible;
            all.indeterminate = picked > 0 && picked < visible;
            all.disabled = visible === 0 || busy;
        }
        counts.set(table, { visible: visible, picked: picked });
    }

    function syncBar() {
        if (active && !tables.has(active)) active = null; // its table was swapped out (e.g. a new search)
        const c = active ? counts.get(active) : null;
        if (!c || !c.picked) {
            active = null;
            bar.hidden = true;
            document.body.classList.remove('bulk-active');
            return;
        }
        const role = active.dataset.bulkRole;
        barCount.textContent = c.picked + ' ' + plural(role, c.picked) + ' selected';

        const hint = [];
        if (role === 'mixed') {
            // e.g. "2 customers, 1 owner" - the search results can hold all three roles
            const per = { customer: 0, owner: 0, mechanic: 0 };
            selectedRows(active).forEach((row) => {
                const r = roleOf(active, row);
                if (r in per) per[r] += 1;
            });
            hint.push(ROLES.filter((r) => per[r]).map((r) => per[r] + ' ' + plural(r, per[r])).join(', '));
        }
        hint.push(c.picked < c.visible ? 'of ' + c.visible + ' shown' : 'all shown');
        barHint.textContent = hint.join(' \u00b7 ');

        deleteBtn.disabled = busy;
        clearBtn.disabled = busy;
        bar.hidden = false;
        document.body.classList.add('bulk-active'); // leaves room so the bar never covers the last row
    }

    /** Re-sync one table (the common case: only it changed) or, with no argument, all of them. */
    function refresh(only) {
        if (only) {
            if (tables.has(only)) syncTable(only);
        } else {
            tables.forEach(syncTable);
        }
        syncBar();
    }

    function clearSelection() {
        tables.forEach(uncheckAll);
        active = null;
        lastPicked = null;
        refresh();
    }

    function activate(table) {
        // one selection at a time: picking in another table drops the previous one
        const previous = active;
        active = table;
        if (previous && previous !== table) {
            uncheckAll(previous);
            if (tables.has(previous)) syncTable(previous);
        }
    }

    /* ---------------------------------------------------------- tables come and go */
    function register(table) {
        if (tables.has(table) || !table.matches('table[data-bulk-role]')) return;
        tables.add(table);
        if (table.tBodies[0]) {
            // keep the bar honest when rows are filtered, sorted or removed by other scripts
            const observer = new MutationObserver(() => refresh(table));
            observer.observe(table.tBodies[0], {
                subtree: true,
                childList: true,
                attributes: true,
                attributeFilter: ['hidden'],
            });
            observers.set(table, observer);
        }
        syncTable(table);
    }

    function unregister(table) {
        tables.delete(table);
        const observer = observers.get(table);
        if (observer) observer.disconnect();
        observers.delete(table);
        if (active === table) {
            active = null;
            lastPicked = null;
        }
    }

    function rescan() {
        tables.forEach((table) => {
            if (!table.isConnected) unregister(table);
        });
        if (searchBox) searchBox.querySelectorAll('table[data-bulk-role]').forEach(register);
        syncBar();
    }

    document.querySelectorAll('table[data-bulk-role]').forEach(register);
    if (searchBox) {
        // admin.js swaps a fresh results table in after every search; pick it up (and drop the old one)
        new MutationObserver(rescan).observe(searchBox, { childList: true });
        rescan();
    }

    /* ---------------------------------------------------------- clicks */
    document.addEventListener('click', (event) => {
        if (busy) return;
        const target = event.target;
        if (!(target instanceof Element)) return;

        const all = target.closest('.bulk-all');
        if (all) {
            const table = all.closest('table[data-bulk-role]');
            if (!table || !tables.has(table)) return;
            activate(table);
            Array.from(table.tBodies[0] ? table.tBodies[0].rows : []).forEach((row) => {
                if (row.dataset.uid && !row.hidden && pickOf(row)) pickOf(row).checked = all.checked;
            });
            lastPicked = null;
            refresh(table);
            return;
        }

        const box = target.closest('.bulk-pick');
        if (box) {
            const table = box.closest('table[data-bulk-role]');
            if (!table || !tables.has(table)) return;
            activate(table);
            const row = box.closest('tr');
            if (event.shiftKey && lastPicked && lastPicked !== row && lastPicked.closest('table') === table) {
                const list = rowsOf(table).filter((r) => !r.hidden);
                const a = list.indexOf(lastPicked);
                const b = list.indexOf(row);
                if (a !== -1 && b !== -1) {
                    const from = Math.min(a, b);
                    const to = Math.max(a, b);
                    for (let i = from; i <= to; i++) pickOf(list[i]).checked = box.checked;
                }
            }
            lastPicked = row;
            refresh(table);
        }
    });

    // Shift-click should select a range of rows, not highlight a stretch of page text.
    document.addEventListener('mousedown', (event) => {
        if (event.shiftKey && event.target instanceof Element && event.target.closest('table[data-bulk-role] td.bulk-col')) {
            event.preventDefault();
        }
    });

    clearBtn.addEventListener('click', () => {
        if (!busy) clearSelection();
    });

    /* ---------------------------------------------------------- talking to the server */
    async function call(table, role, ids, force) {
        const res = await fetch(table.dataset.bulkUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json',
                'X-Requested-With': 'fetch',
                'X-CSRFToken': table.dataset.csrf || '',
            },
            body: JSON.stringify({ role: role, ids: ids, force: force === true }),
        });
        let data = null;
        try {
            data = await res.json();
        } catch (err) {
            /* not JSON (e.g. the session expired and a login page came back) */
        }
        if (!res.ok || !data || !data.ok) {
            throw new Error((data && data.error) || 'The server did not accept the request (' + res.status + ').');
        }
        return data;
    }

    async function callInChunks(table, role, ids, force, outcome) {
        for (let i = 0; i < ids.length; i += CHUNK) {
            const data = await call(table, role, ids.slice(i, i + CHUNK), force);
            ['deleted', 'gone', 'needs_confirm', 'skipped', 'failed'].forEach((key) => {
                outcome[key] = outcome[key].concat(data[key] || []);
            });
        }
    }

    /* ---------------------------------------------------------- the delete flow */
    function previewNames(names) {
        const shown = names.slice(0, 6);
        if (names.length > shown.length) shown.push('and ' + (names.length - shown.length) + ' more');
        return shown;
    }

    function describeImpact(item, label) {
        const parts = [];
        parts.push(item.services + (item.services === 1 ? ' service' : ' services'));
        parts.push(item.bookings + (item.bookings === 1 ? ' booking' : ' bookings') + (item.active_bookings ? ' (' + item.active_bookings + ' open)' : ''));
        if (item.mechanics) parts.push(item.mechanics + (item.mechanics === 1 ? ' mechanic' : ' mechanics') + ' unassigned');
        return label + ' - workshop "' + item.workshop + '": ' + parts.join(', ');
    }

    /** Remove deleted accounts from every table on the page, not only the one the admin picked in. */
    function removeRows(uids) {
        const wanted = new Set(uids.map(String));
        if (!wanted.size) return;
        const leaving = [];
        tables.forEach((table) =>
            rowsOf(table).forEach((row) => {
                if (wanted.has(row.dataset.uid)) leaving.push(row);
            })
        );
        if (!leaving.length) return;
        leaving.forEach((row) => {
            if (pickOf(row)) pickOf(row).checked = false;
            row.classList.add('is-leaving');
        });
        // one timer for the whole batch, so tables are renumbered / re-sorted once, not once per row
        setTimeout(() => {
            const touched = new Set();
            leaving.forEach((row) => {
                const table = row.closest('table');
                if (table) touched.add(table);
                row.remove();
            });
            touched.forEach((table) => {
                renumber(table);
                showEmptyNote(table);
            });
            document.dispatchEvent(new CustomEvent('admin:rows-changed'));
            refresh();
        }, 260);
    }

    function renumber(table) {
        // keep an "S.no." column honest after rows disappear
        const body = table.tBodies[0];
        if (!body) return;
        let n = 0;
        rowsOf(table).forEach((row) => {
            n += 1;
            const cell = row.cells[1];
            if (cell && /^\d+$/.test(cell.textContent.trim()) && cell.classList.contains('bulk-serial')) cell.textContent = String(n);
        });
    }

    function showEmptyNote(table) {
        const text = table.dataset.emptyText;
        if (!text || rowsOf(table).length) return;
        table.replaceWith(el('p', { class: 'no-results neo-note', text: text }));
    }

    async function deleteSelected() {
        if (busy || !active) return;
        const table = active;
        const tableRole = table.dataset.bulkRole;
        const rows = selectedRows(table);
        if (!rows.length) return;

        // Group by role: the server removes one role per request.
        const groups = { customer: [], owner: [], mechanic: [] };
        const labels = {};
        const roleOfUid = {};
        const outcome = { deleted: [], gone: [], needs_confirm: [], skipped: [], failed: [] };
        rows.forEach((row) => {
            const uid = parseInt(row.dataset.uid, 10);
            const role = roleOf(table, row);
            labels[uid] = labelOf(row);
            if (!(uid > 0) || !(role in groups)) {
                outcome.skipped.push({ u_id: uid || row.dataset.uid, reason: 'unknown account type' });
                return;
            }
            groups[role].push(uid);
            roleOfUid[uid] = role;
        });
        const order = ROLES.filter((r) => groups[r].length);
        const ids = [].concat(...order.map((r) => groups[r]));
        if (!ids.length) return;

        const mixed = tableRole === 'mixed';
        const named = (uid) => (mixed ? labels[uid] + ' (' + roleOfUid[uid] + ')' : labels[uid]);
        const breakdown = order.map((r) => groups[r].length + ' ' + plural(r, groups[r].length)).join(', ');

        let text = 'These accounts will be permanently deleted. This cannot be undone.';
        if (groups.owner.length) text = 'Owners who run a workshop are shown in the next step, so you can see what goes with them.';
        if (mixed) text = breakdown + '. ' + text;

        const confirmed = await ask({
            title: 'Delete ' + ids.length + ' ' + plural(tableRole, ids.length) + '?',
            text: text,
            items: previewNames(ids.map(named)),
            confirmLabel: 'Delete ' + ids.length,
            danger: true,
        });
        if (!confirmed) {
            closeDialog();
            return;
        }

        busy = true;
        refresh(); // disables every header checkbox and both bar buttons while the request runs
        let fatal = null;
        let declined = [];

        try {
            showBusy('Deleting ' + ids.length + ' ' + plural(tableRole, ids.length) + '...');
            for (const role of order) {
                await callInChunks(table, role, groups[role], false, outcome);
            }

            if (outcome.needs_confirm.length) {
                const pending = outcome.needs_confirm;
                outcome.needs_confirm = [];
                const go = await ask({
                    title: pending.length + (pending.length === 1 ? ' owner also runs' : ' owners also run') + ' a workshop',
                    text: 'Deleting them permanently removes their workshop, services, bookings and payments. Customers with open bookings and the workshop mechanics are notified.',
                    items: pending.map((item) => describeImpact(item, labels[item.u_id] || 'Owner ' + item.u_id)),
                    confirmLabel: 'Delete everything',
                    cancelLabel: 'Skip these',
                    danger: true,
                });
                if (go) {
                    showBusy('Deleting workshops and owners...');
                    await callInChunks(table, 'owner', pending.map((p) => p.u_id), true, outcome);
                } else {
                    declined = pending.map((p) => p.u_id);
                }
            }
        } catch (err) {
            fatal = err && err.message ? err.message : 'Something went wrong.';
        }

        busy = false;
        removeRows(outcome.deleted.concat(outcome.gone));
        lastPicked = null;
        refresh();

        // Anything that got no verdict (the run stopped early) is reported, never silently dropped.
        const settled = new Set(
            [].concat(
                outcome.deleted,
                outcome.gone,
                declined,
                outcome.skipped.map((s) => s.u_id),
                outcome.failed.map((f) => f.u_id)
            )
        );
        const notAttempted = ids.filter((id) => !settled.has(id)).length;

        const nm = (uid) => labels[uid] || 'Account ' + uid;
        const lines = [];
        outcome.failed.forEach((f) => lines.push(nm(f.u_id) + ' - ' + f.error));
        outcome.skipped.forEach((s) => lines.push(nm(s.u_id) + ' - skipped: ' + s.reason));
        declined.forEach((uid) => lines.push(nm(uid) + ' - skipped by you (still has a workshop)'));

        const summary = [];
        if (outcome.deleted.length) summary.push('Deleted ' + outcome.deleted.length + ' ' + plural(tableRole, outcome.deleted.length) + '.');
        if (outcome.gone.length) summary.push(outcome.gone.length + ' already ' + (outcome.gone.length === 1 ? 'was' : 'were') + ' gone.');
        if (notAttempted) summary.push(notAttempted + ' not deleted because the run stopped early.');
        if (fatal) summary.push(fatal);
        const problems = lines.length > 0 || !!fatal;

        await ask({
            title: problems ? 'Finished with some problems' : 'Done',
            text: summary.join(' ') || 'Nothing was deleted.',
            items: lines,
            confirmLabel: 'Close',
            onlyClose: true,
        });
        closeDialog();
    }

    deleteBtn.addEventListener('click', deleteSelected);
    refresh();
})();
