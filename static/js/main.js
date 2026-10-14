// Shared site-wide behavior. Page-specific interactions belong in their own files.

document.addEventListener("DOMContentLoaded", () => {
    // Dismiss flash messages after four seconds; pause while the user hovers.
    document.querySelectorAll(".flash-message").forEach((message) => {
        let timer;
        const dismiss = () => {
            message.style.opacity = "0";
            message.style.transform = "translateX(40px)";
            window.setTimeout(() => message.remove(), 300);
        };
        const start = () => {
            window.clearTimeout(timer);
            timer = window.setTimeout(dismiss, 3000);
        };
        message.addEventListener("mouseenter", () => window.clearTimeout(timer));
        message.addEventListener("mouseleave", start);
        start();
    });
});


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

    // Esc closes the login / sign-up popups
    document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        loginModal?.classList.remove("show");
        signUpModal?.classList.remove("show");
        header?.classList.remove("modal-open");
        mainCon?.classList.remove("show");
    });
})();