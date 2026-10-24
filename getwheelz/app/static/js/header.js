// Shared navbar behavior: service dropdown, theme, geolocation, and auth modals.

(() => {
    const dropdown = document.getElementById("dropdown");
    const dropdownMenu = document.getElementById("dropdownMenu");

    if (dropdown && dropdownMenu) {
        dropdown.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            dropdownMenu.classList.toggle("show");
        });

        document.addEventListener("click", (event) => {
            if (!(event.target instanceof Element)) return;
            if (!event.target.closest(".dropdown")) dropdownMenu.classList.remove("show");
        });
    }

    const themeToggle = document.getElementById("theme-toggle");
    const themeIcon = document.getElementById("theme");

    try {
        const isLight = localStorage.getItem("theme") === "light";
        document.body.classList.toggle("light", isLight);
        document.documentElement.setAttribute("data-theme", isLight ? "light" : "dark");
        themeIcon?.classList.toggle("bx-moon", isLight);
        themeIcon?.classList.toggle("bx-sun", !isLight);
    } catch (error) {
        // Keep the page's default theme if storage is unavailable.
    }

    themeToggle?.addEventListener("click", () => {
        const isLight = document.body.classList.toggle("light");
        document.documentElement.setAttribute("data-theme", isLight ? "light" : "dark");
        themeIcon?.classList.toggle("bx-moon", isLight);
        themeIcon?.classList.toggle("bx-sun", !isLight);
        try {
            localStorage.setItem("theme", isLight ? "light" : "dark");
        } catch (error) {
            // Theme still works for this page if storage is unavailable.
        }
    });

    // "Workshops near me" shortcut, on every page: jumps to the search results, nearest first.
    const locationBtn = document.getElementById("location-btn");

    // NEO says what went wrong (same look as the flash messages) instead of a browser alert
    function neoToast(message) {
        const tpl = document.getElementById("neoToastTpl");
        if (!tpl) return;
        document.querySelectorAll("[data-neo-toast]").forEach((el) => el.remove());
        const box = tpl.content.firstElementChild.cloneNode(true);
        box.querySelector(".flash-message span").textContent = message;
        document.body.appendChild(box);
        window.GWRobot?.init();

        let timer;
        const dismiss = () => {
            window.clearTimeout(timer);
            box.style.opacity = "0";
            box.style.transform = "translateX(40px)";
            window.setTimeout(() => box.remove(), 300);
        };
        const start = () => { window.clearTimeout(timer); timer = window.setTimeout(dismiss, 6000); };
        const bubble = box.querySelector(".flash-message");
        bubble.addEventListener("mouseenter", () => window.clearTimeout(timer));
        bubble.addEventListener("mouseleave", start);
        box.querySelector(".flash-close")?.addEventListener("click", dismiss);
        start();
    }

    function locationProblem(error) {
        if (error && error.code === 1) {
            return "Location is blocked for this site. Allow it in your browser's site settings, then press the icon again.";
        }
        if (error && error.message === "unsupported") {
            return "This browser can't share its location, so I can't sort by distance.";
        }
        return "I couldn't find your location. Check that location is turned on for your device and try again.";
    }

    let locating = false;
    locationBtn?.addEventListener("click", () => {
        if (locating) return;
        // distance.js keeps a location for 10 minutes, so moving between pages doesn't ask again
        if (!window.GW) { neoToast(locationProblem(new Error("unsupported"))); return; }

        locating = true;
        const icon = locationBtn.querySelector("i");
        icon?.classList.add("bx-spin");
        window.GW.getLocation(false).then(
            (loc) => window.location.assign(`/workshops/search?lat=${loc.lat}&lng=${loc.lng}`),
            (error) => {
                locating = false;
                icon?.classList.remove("bx-spin");
                neoToast(locationProblem(error));
            }
        );
    });

    const header = document.querySelector(".navbar");
    const loginModal = document.getElementById("loginModal");
    const signUpModal = document.getElementById("signUpModal");
    const mainCon = document.getElementById("mainCon");

    document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;

        const loginBtn = target.closest("[data-login]");
        const signupBtn = target.closest("[data-signup]");

        if (loginBtn || signupBtn) {
            event.preventDefault();
            loginModal?.classList.toggle("show", Boolean(loginBtn));
            signUpModal?.classList.toggle("show", Boolean(signupBtn));
            header?.classList.add("modal-open");
            mainCon?.classList.add("show");
            return;
        }

        if (target.closest(".login-form, .signup-form")) return;
        if (target.closest("#loginModal, #signUpModal")) {
            // Clicking the modal backdrop closes it; clicks inside forms do not.
            if (target === loginModal || target === signUpModal) closeAuthModals();
            return;
        }
        if (loginModal?.classList.contains("show") || signUpModal?.classList.contains("show")) {
            closeAuthModals();
        }
    });

    function closeAuthModals() {
        loginModal?.classList.remove("show");
        signUpModal?.classList.remove("show");
        header?.classList.remove("modal-open");
        mainCon?.classList.remove("show");
    }

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeAuthModals();
    });
})();

// Login / sign-up pop-ups: submit in the background so the pop-up STAYS OPEN when something is wrong
// (wrong email or password, passwords that do not match, ...). The problem is shown inside the form,
// the fields keep what was typed, and NEO looks strained. Only a successful login leaves the page.
(() => {
    const FORMS = "#loginModal form, #signUpModal form";
    if (!window.fetch || !window.FormData) return; // very old browser: the normal form post still works

    const loginModal = document.getElementById("loginModal");
    const signUpModal = document.getElementById("signUpModal");

    function box(form) {
        let el = form.querySelector(".auth-msg");
        if (!el) {
            el = document.createElement("div");
            el.className = "auth-msg";
            el.setAttribute("role", "alert");
            el.hidden = true;
            form.insertBefore(el, form.querySelector(".fw-btn-con") || null);
        }
        return el;
    }

    function neo(mood) {
        const svg = document.querySelector("#authRobot .rb");
        if (!svg || !window.GWRobot) return;
        window.dispatchEvent(new Event("resize")); // the form just got taller: let NEO re-position itself
        window.GWRobot.flash(svg, mood, 2600);
    }

    function show(form, kind, text) {
        const el = box(form);
        el.className = "auth-msg is-" + kind;
        el.replaceChildren();
        const icon = document.createElement("i");
        icon.className = "bx " + (kind === "ok" ? "bx-check-circle" : "bx-error-circle");
        const span = document.createElement("span");
        span.textContent = text;
        el.append(icon, span);
        el.hidden = false;
        if (kind === "error") {
            form.classList.remove("is-shake");
            void form.offsetWidth; // restart the shake
            form.classList.add("is-shake");
        }
        neo(kind === "ok" ? "happy" : "strained");
    }

    function clearAll() {
        document.querySelectorAll(FORMS).forEach((f) => {
            const el = f.querySelector(".auth-msg");
            if (el) el.hidden = true;
            f.classList.remove("is-shake");
        });
    }

    // moving between Login and Sign Up by hand starts with a clean slate
    document.addEventListener("click", (e) => {
        if (e.target instanceof Element && e.target.closest("[data-login], [data-signup]")) clearAll();
    });

    document.addEventListener("submit", async (e) => {
        const form = e.target;
        if (!(form instanceof HTMLFormElement) || !form.matches(FORMS)) return;
        e.preventDefault();
        form.setAttribute("data-no-stay", ""); // stay-put.js must not remember a scroll position for these

        const isLogin = Boolean(form.closest("#loginModal"));
        const button = form.querySelector('button[type="submit"]');
        const label = button ? button.textContent : "";
        if (button) {
            button.disabled = true;
            button.textContent = isLogin ? "Signing in…" : "Creating account…";
        }
        const reset = () => {
            if (!button) return;
            button.disabled = false;
            button.textContent = label;
        };
        const el = form.querySelector(".auth-msg");
        if (el) el.hidden = true;

        let res = null;
        let data = null;
        try {
            res = await fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                credentials: "same-origin",
                headers: { "X-Requested-With": "fetch", Accept: "application/json" },
            });
            try { data = await res.json(); } catch (err) { /* not JSON: handled below */ }
        } catch (err) {
            reset();
            show(form, "error", "Could not reach the server. Check your connection and try again.");
            return;
        }

        if (data && data.ok && data.redirect) {
            window.location.assign(data.redirect); // logged in: the button stays disabled while the page changes
            return;
        }

        reset();

        if (data && data.ok) {
            // account created: move to the login form, with the email already filled in
            const email = form.querySelector('input[name="email"]');
            const loginForm = loginModal && loginModal.querySelector("form");
            form.reset();
            clearAll();
            if (loginForm) {
                const loginEmail = loginForm.querySelector('input[name="email"]');
                if (loginEmail && email) loginEmail.value = email.value || loginEmail.value;
                loginModal.classList.add("show");
                signUpModal && signUpModal.classList.remove("show");
                show(loginForm, "ok", data.message || "Account created. Please log in.");
                const pw = loginForm.querySelector('input[name="password"]');
                // the pop-up watcher in robot.js runs after this, so give NEO's mood a moment
                setTimeout(() => { neo("happy"); pw && pw.focus(); }, 60);
            }
            return;
        }

        let text = data && data.error;
        if (!text) {
            if (res && res.status === 429) text = "Too many attempts. Please wait a minute and try again.";
            else if (res && res.status === 400) text = "Your session expired. Please refresh the page and try again.";
            else text = "Something went wrong. Please try again.";
        }
        show(form, "error", text);

        if (isLogin) {
            const pw = form.querySelector('input[name="password"]');
            if (pw) { pw.value = ""; pw.focus(); }
        }
    });
})();

// "Sign up with Google": carry the role picked in the form (customer / owner / mechanic) to the server.
document.addEventListener("click", (e) => {
    const link = e.target instanceof Element ? e.target.closest("#google-signup-btn") : null;
    if (!link) return;
    const role = link.closest("form")?.querySelector('select[name="role"]')?.value;
    if (!role) return;
    const url = new URL(link.getAttribute("href"), window.location.origin);
    url.searchParams.set("role", role);
    link.setAttribute("href", url.pathname + url.search);
});