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
        themeIcon?.classList.toggle("bx-moon", isLight);
        themeIcon?.classList.toggle("bx-sun", !isLight);
    } catch (error) {
        // Keep the page's default theme if storage is unavailable.
    }

    themeToggle?.addEventListener("click", () => {
        const isLight = document.body.classList.toggle("light");
        themeIcon?.classList.toggle("bx-moon", isLight);
        themeIcon?.classList.toggle("bx-sun", !isLight);
        try {
            localStorage.setItem("theme", isLight ? "light" : "dark");
        } catch (error) {
            // Theme still works for this page if storage is unavailable.
        }
    });

    const locationBtn = document.getElementById("location-btn");
    locationBtn?.addEventListener("click", () => {
        if (!navigator.geolocation) {
            window.alert("Your browser does not support location access.");
            return;
        }

        const icon = locationBtn.querySelector("i");
        icon?.classList.add("bx-spin");
        navigator.geolocation.getCurrentPosition(
            (position) => {
                const { latitude, longitude } = position.coords;
                window.location.assign(`/workshops/search?lat=${latitude}&lng=${longitude}`);
            },
            () => {
                icon?.classList.remove("bx-spin");
                window.alert("Could not access your location. Please allow location access and try again.");
            },
            { timeout: 10000 }
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
