// Keep the page where it was after ANY form is submitted.
//
// A normal form post ends in a redirect, which is a brand-new page load: the browser starts at the top,
// on the default tab, and an #anchor in the redirect can jump somewhere else entirely.
// This script remembers where you were when you submitted (scroll position, active profile tab,
// active sidebar item) and puts everything back once the same page has loaded again.
//
// It works for every POST form on the site, including ones submitted from code (form.submit()).
// If a form should NOT keep the position, add data-no-stay to the <form>.

(() => {
    const KEY = 'fw:stay-put';
    const MAX_AGE_MS = 20000; // only trust the saved position for a short while after a submit

    let store = null;
    try { store = window.sessionStorage; } catch (e) { /* storage blocked: the page just behaves as before */ }
    if (!store) return;

    // ---------------------------------------------------------------- remember
    const snapshot = () => {
        const tab = document.querySelector('[data-tab-btn].active');
        const side = document.querySelector('.sidebar-link.active');
        const sideHref = side ? side.getAttribute('href') || '' : '';
        return {
            path: window.location.pathname,
            x: window.scrollX,
            y: window.scrollY,
            tab: tab ? tab.getAttribute('data-tab-btn') : null,
            side: sideHref.startsWith('#') ? sideHref : null, // only in-page links; page links are set by the server
            at: Date.now(),
        };
    };

    const save = () => {
        try { store.setItem(KEY, JSON.stringify(snapshot())); } catch (e) { /* ignore */ }
    };

    const discard = () => {
        try { store.removeItem(KEY); } catch (e) { /* ignore */ }
    };

    // Other scripts (ajax-forms.js) use this to say "we are leaving, keep it" / "we are staying, forget it".
    window.fwStayPut = { save, discard };

    // NB: read the HTML attributes, not form.method / form.action. A form that contains an input named
    // "method" or "action" would otherwise return that input element instead of the text.
    const shouldKeep = (form) => {
        if (!(form instanceof HTMLFormElement)) return false;
        if ((form.getAttribute('method') || '').toLowerCase() !== 'post') return false; // searches/filters (GET) are real navigations
        if (form.hasAttribute('data-no-stay')) return false;
        const target = form.getAttribute('target');
        if (target && target !== '_self') return false;                                 // opens elsewhere
        try {
            return new URL(form.getAttribute('action') || window.location.href, window.location.href).origin === window.location.origin;
        } catch (e) {
            return false;
        }
    };

    // normal submits (button click, Enter key)...
    document.addEventListener('submit', (event) => {
        if (shouldKeep(event.target)) save();
    }, true);

    // ...and submits made from code, such as the confirm dialog calling form.submit()
    const nativeSubmit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        if (shouldKeep(this)) save();
        return nativeSubmit.call(this);
    };

    // ---------------------------------------------------------------- restore
    let saved = null;
    try {
        saved = JSON.parse(store.getItem(KEY) || 'null');
        store.removeItem(KEY); // use it once, so a later visit never jumps by surprise
    } catch (e) { /* ignore */ }

    // Only when the SAME page came back (not after login, delete account, etc.) and it is fresh.
    if (!saved || window.location.pathname !== saved.path || Date.now() - saved.at > MAX_AGE_MS) return;

    let previousMode = 'auto';
    try {
        previousMode = history.scrollRestoration;
        history.scrollRestoration = 'manual'; // we place the page ourselves
    } catch (e) { /* ignore */ }

    const restoreState = () => {
        if (saved.tab) {
            const button = document.querySelector('[data-tab-btn="' + saved.tab.replace(/"/g, '\\"') + '"]');
            if (button && !button.classList.contains('active')) button.click();
        }
        if (saved.side) {
            const links = Array.from(document.querySelectorAll('.sidebar-link'));
            if (links.some((link) => link.getAttribute('href') === saved.side)) {
                links.forEach((link) => link.classList.toggle('active', link.getAttribute('href') === saved.side));
            }
        }
    };

    // 'instant' beats the site-wide scroll-behavior: smooth, so there is no visible scroll animation
    const restoreScroll = () => window.scrollTo({ left: saved.x, top: saved.y, behavior: 'instant' });

    const run = () => {
        restoreState();
        restoreScroll();
    };

    // DOMContentLoaded fires after every deferred page script has run, so tabs/sidebar are wired up.
    if (document.readyState === 'complete') run();
    else document.addEventListener('DOMContentLoaded', run);

    // Images, fonts and the browser's own #anchor jump can move things after that, so place it again.
    window.addEventListener('load', () => {
        restoreScroll();
        [60, 250].forEach((ms) => setTimeout(restoreScroll, ms));
        setTimeout(() => {
            try { history.scrollRestoration = previousMode; } catch (e) { /* ignore */ }
        }, 400);
    });
})();