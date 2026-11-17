// Shared site-wide behavior. Page-specific interactions belong in their own files.

// One-shot skip-preloader flag for any internal navigation click: the next
// full page load started by clicking a same-site link opens without the curtain.
// loader.js consumes the flag on that load; everything else keeps its normal
// intro (first visit) / quick (repeat) preloader.
(() => {
    document.addEventListener("click", (e) => {
        // Plain left-click only — ignore modified clicks (open in new tab/window).
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

        const a = e.target.closest("a[href]");
        if (!a) return;

        const href = a.getAttribute("href");
        if (!href || href.startsWith("#") || /^javascript:/i.test(href)) return;
        if (a.hasAttribute("download")) return;

        let url;
        try { url = new URL(href, location.href); } catch { return; }
        if (url.origin !== location.origin) return;      // external link: no skip

        try { sessionStorage.setItem("gw:skip-loader", "1"); } catch (err) {}
    });
})();

// Flash messages dismiss themselves: see js/flash.js


//=====================================================================Index page: reveal, counters, role preselect, Esc to close popups========
(function () {
    // scroll reveal: elements start hidden only once JS is running
    const reveals = document.querySelectorAll(".reveal");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // count-up numbers
    function countUp(el) {
        const target = parseInt(el.dataset.count, 10);
        if (isNaN(target) || reduceMotion || target === 0) return;
        const duration = 1200;
        const start = performance.now();
        function tick(now) {
            const p = Math.min((now - start) / duration, 1);
            el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
            if (p < 1) requestAnimationFrame(tick);
        }
        el.textContent = "0";
        requestAnimationFrame(tick);
    }

    if (reveals.length && "IntersectionObserver" in window && !reduceMotion) {
        const io = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add("in");
                entry.target.querySelectorAll("[data-count]").forEach(countUp);
                io.unobserve(entry.target);
            });
        }, { threshold: 0.15 });
        reveals.forEach((el) => { el.classList.add("will-reveal"); io.observe(el); });
    }

    // "Sign up as an owner / mechanic" buttons preselect the role in the sign-up form
    document.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-signup][data-role]");
        if (!btn) return;
        const select = document.querySelector("#signUpModal select[name='role']");
        if (select) select.value = btn.dataset.role;
    });

    // Password visibility toggle ("view password") — any input wrapped in .pw-wrap
    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".pw-toggle");
        if (!btn) return;
        e.preventDefault();
        const input = btn.closest(".pw-wrap")?.querySelector('input[type="password"], input[type="text"]');
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        const icon = btn.querySelector("i");
        if (icon) icon.className = show ? "bx bx-hide" : "bx bx-show";
        input.focus();
    });

})();