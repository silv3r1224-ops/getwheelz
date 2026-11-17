// Submit selected forms in the background and show the result right inside the form,
// so a failed attempt keeps the page, the tab, the open popup and everything you typed.
//
// How it works: the form is sent with fetch(); the server (app/ajax.py) answers with
//   { ok, message, redirect }   instead of redirecting.
//   - failure -> the message appears inside the form and nothing else changes
//   - success -> either go to `redirect` (navigate: true) or show the message and stay
//
// To use it on another form, add a line to FORMS below, or just put data-ajax on the <form>
// (add data-ajax-navigate="false" if a success should stay on the page).

(() => {
    const FORMS = [
        // public pages: the login / sign-up popups
        { match: '#loginModal form', navigate: true, clearOnError: 'input[type="password"]' },
        { match: '#signUpModal form', navigate: true },

        // profile page
        { match: 'form[action$="/profile/change-password"]', navigate: false, resetOnSuccess: true },
        { match: 'form[action$="/profile/delete-account"]', navigate: true, clearOnError: 'input[type="password"]' },
        { match: '#profileEditForm', navigate: true },

        // owner dashboard popups
        { match: '#createWorkshopForm', navigate: true, status: '.fw-modal-body' },
        { match: 'form[action$="/owner/add-service"]', navigate: true },
        { match: 'form[action*="/owner/service/"][action$="/edit"]', navigate: true },

        // anything else that opts in with data-ajax
        { match: 'form[data-ajax]', navigate: null }, // null = read data-ajax-navigate
    ];

    const STYLE = `
        form .af-status { align-self: stretch; box-sizing: border-box; width: 100%; margin: 10px 0 0; padding: 10px 12px;
            border: 1px solid transparent; border-radius: 8px; font-size: 13.5px; line-height: 1.45; text-align: left;
            animation: af-in 0.15s ease; }
        form .af-status[hidden] { display: none; }
        form .af-status[data-state="error"] { color: #ff8a80; background: rgba(239, 83, 80, 0.12); border-color: rgba(239, 83, 80, 0.35); }
        form .af-status[data-state="success"] { color: #69d19a; background: rgba(76, 175, 125, 0.12); border-color: rgba(76, 175, 125, 0.35); }
        body.light form .af-status[data-state="error"] { color: #b71c1c; }
        body.light form .af-status[data-state="success"] { color: #176b40; }
        form[aria-busy="true"] button[type="submit"] { opacity: 0.7; cursor: progress; }
        @keyframes af-in { from { opacity: 0; transform: translateY(-3px); } to { opacity: 1; transform: none; } }
    `;

    const configFor = (form) => {
        for (const entry of FORMS) {
            if (!form.matches(entry.match)) continue;
            const navigate = entry.navigate === null ? form.dataset.ajaxNavigate !== 'false' : entry.navigate;
            return { ...entry, navigate };
        }
        return null;
    };

    // ---- the message line inside the form ----
    const statusLine = (form, cfg) => {
        let line = form.querySelector('.af-status');
        if (line) return line;

        line = document.createElement('p');
        line.className = 'af-status';
        line.setAttribute('role', 'alert');
        line.hidden = true;

        const host = cfg.status ? form.querySelector(cfg.status) : null;
        if (host) {
            host.prepend(line);
        } else {
            // sit just above the submit button (or the wrapper around it)
            let anchor = form.querySelector('[type="submit"]');
            while (anchor && anchor.parentElement !== form) anchor = anchor.parentElement;
            if (anchor) form.insertBefore(line, anchor);
            else form.append(line);
        }
        return line;
    };

    let hideTimer = null;
    const show = (form, cfg, state, text) => {
        const line = statusLine(form, cfg);
        clearTimeout(hideTimer);
        line.dataset.state = state;
        line.textContent = text;
        line.hidden = false;
        line.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        if (state === 'success') hideTimer = setTimeout(() => { line.hidden = true; }, 8000);
    };

    const clear = (form) => {
        const line = form.querySelector('.af-status');
        if (line) line.hidden = true;
    };

    // ---- busy state on the submit button ----
    // Only real submit buttons (not "Login with Google" etc.). The text goes into the inner pill
    // (.fw-btn) when there is one, so the button keeps its look.
    const submitButtons = (form) => form.querySelectorAll('button[type="submit"]');
    const labelNode = (btn) => btn.querySelector('.fw-btn') || btn;

    const remember = (form) => {
        submitButtons(form).forEach((btn) => {
            if (!('afLabel' in btn.dataset)) btn.dataset.afLabel = labelNode(btn).innerHTML;
        });
    };

    const setBusy = (form, busy) => {
        remember(form);
        form.setAttribute('aria-busy', busy ? 'true' : 'false');
        submitButtons(form).forEach((btn) => {
            btn.disabled = busy;
            labelNode(btn).innerHTML = busy ? 'Please wait…' : btn.dataset.afLabel;
        });
    };

    // ---- submit ----
    document.addEventListener('submit', async (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return; // other scripts validate first
        if ((form.method || '').toLowerCase() !== 'post') return;

        const cfg = configFor(form);
        if (!cfg) return;

        event.preventDefault();
        if (form.getAttribute('aria-busy') === 'true') return; // already sending

        clear(form);
        setBusy(form, true);
        let leaving = false;

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                credentials: 'same-origin',
                headers: {
                    'X-Requested-With': 'fetch',
                    'X-Ajax-Navigate': cfg.navigate ? '1' : '0',
                    Accept: 'application/json',
                },
            });

            let data = null;
            try { data = await response.json(); } catch (e) { /* not JSON */ }

            if (!data || typeof data.ok !== 'boolean') {
                // The server did not use the JSON bridge. If it redirected us, just follow it.
                if (response.ok && response.redirected) {
                    leaving = true;
                    window.location.assign(response.url);
                    return;
                }
                show(form, cfg, 'error', 'Something went wrong. Please try again.');
                return;
            }

            if (!data.ok) {
                show(form, cfg, 'error', data.message || 'Something went wrong. Please try again.');
                if (cfg.clearOnError) form.querySelectorAll(cfg.clearOnError).forEach((input) => { input.value = ''; });
                const first = cfg.clearOnError && form.querySelector(cfg.clearOnError);
                if (first) first.focus();
                return;
            }

            if (cfg.navigate && data.redirect) {
                leaving = true; // keep the button disabled while the next page loads
                window.location.assign(data.redirect);
                return;
            }

            if (cfg.resetOnSuccess) form.reset();
            if (data.message) show(form, cfg, 'success', data.message);
        } catch (error) {
            show(form, cfg, 'error', "Couldn't reach the server. Check your connection and try again.");
        } finally {
            if (!leaving) setBusy(form, false);
        }
    });

    const init = () => {
        const style = document.createElement('style');
        style.textContent = STYLE;
        document.head.appendChild(style);

        // remember each button's original label before anything changes it
        FORMS.forEach((entry) => document.querySelectorAll(entry.match).forEach((el) => {
            if (el instanceof HTMLFormElement) remember(el);
        }));
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();