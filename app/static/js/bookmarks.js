// Bookmark toggling for customer surfaces.
// Any element with [data-bm][data-w-id] toggles that workshop's saved state.
// The seed set comes from the page: window.GW_BOOKMARKS = [w_id, ...] (empty for
// non-customers, and the whole module no-ops when window.GW_CUSTOMER is missing).
(() => {
    if (!window.GW_CUSTOMER) return;

    const saved = new Set(window.GW_BOOKMARKS || []);
    window.GW_BOOKMARKS = saved;

    function setButton(btn, on) {
        if (!btn) return;
        btn.classList.toggle('on', !!on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        const ico = btn.querySelector('i');
        if (ico) ico.className = 'bx ' + (on ? 'bxs-bookmark' : 'bx-bookmark');
        const lbl = btn.querySelector('.bm-label');
        if (lbl) lbl.textContent = on ? 'Saved' : 'Save';
        const title = on ? 'Remove from saved workshops' : 'Save this workshop';
        btn.title = title;
        btn.setAttribute('aria-label', title);
    }

    function syncAll(id, on) {
        document.querySelectorAll('[data-bm][data-w-id="' + id + '"]')
            .forEach(b => setButton(b, on));
    }

    async function toggle(id) {
        try {
            const res = await fetch('/customer/bookmarks/toggle', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.GW_CSRF || ''
                },
                body: JSON.stringify({ w_id: Number(id) })
            });
            if (!res.ok) throw new Error('Bad response');
            const data = await res.json();
            if (data.saved) saved.add(Number(id));
            else saved.delete(Number(id));
            syncAll(id, !!data.saved);

            // when unsaving from the Saved shelf, collapse that card
            if (!data.saved) {
                document.querySelectorAll('[data-saved-card][data-w-id="' + id + '"]')
                    .forEach(card => {
                        card.classList.add('leaving');
                        setTimeout(() => card.remove(), 220);
                    });
            }

            if (window.GW && window.GW.neoToast) {
                window.GW.neoToast(
                    data.saved ? 'Saved to your bookmarks.' : 'Removed from saved workshops.',
                    'success'
                );
            }
            return true;
        } catch (_) {
            if (window.GW && window.GW.neoToast) {
                window.GW.neoToast("Couldn't update saved workshops. Try again.");
            }
            return false;
        }
    }

    function handleActivate(el) {
        const id = el.dataset.wId;
        if (id) toggle(id);
    }

    document.addEventListener('click', e => {
        const el = e.target.closest('[data-bm][data-w-id]');
        if (el) {
            e.preventDefault();
            e.stopPropagation();
            handleActivate(el);
        }
    });

    document.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const el = e.target.closest('[data-bm][data-w-id]');
        if (el) {
            e.preventDefault();
            handleActivate(el);
        }
    });

    window.GW = window.GW || {};
    window.GW.setBookmarkButton = setButton;
    window.GW.bookmarkState = id => saved.has(Number(id));
})();
