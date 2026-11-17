// Admin-only interactions. This file is loaded only by admin templates.

(() => {
    const sideBar = document.getElementById("sideBar");
    const menuBar = document.getElementById("menuBar");
    const mobileQuery = window.matchMedia("(max-width: 900px)");

    if (sideBar && menuBar) {
        // Desktop: remember the collapsed / open state.
        try {
            if (localStorage.getItem("sidebar") === "collapsed") {
                sideBar.classList.add("collapsed");
            }
        } catch (error) {
            // Use the expanded sidebar if storage is unavailable.
        }

        sideBar.querySelectorAll(".sidebar-link").forEach((link) => {
            link.title = link.textContent.trim().replace(/\s+/g, " ");
        });

        // Mobile: the sidebar becomes a slide-in drawer with a dark backdrop.
        const navbar = document.querySelector(".navbar");
        const backdrop = document.createElement("div");
        backdrop.className = "sidebar-backdrop";
        document.body.appendChild(backdrop);

        const setNavHeight = () => {
            const height = navbar ? navbar.offsetHeight : 80;
            document.documentElement.style.setProperty("--nav-h", height + "px");
        };

        const closeDrawer = () => {
            sideBar.classList.remove("mobile-open");
            backdrop.classList.remove("show");
            document.body.classList.remove("sidebar-open");
            menuBar.setAttribute("aria-expanded", "false");
        };

        const openDrawer = () => {
            setNavHeight();
            sideBar.classList.add("mobile-open");
            backdrop.classList.add("show");
            document.body.classList.add("sidebar-open");
            menuBar.setAttribute("aria-expanded", "true");
        };

        menuBar.setAttribute("aria-expanded", "false");
        menuBar.addEventListener("click", (event) => {
            event.preventDefault();

            if (mobileQuery.matches) {
                if (sideBar.classList.contains("mobile-open")) {
                    closeDrawer();
                } else {
                    openDrawer();
                }
                return;
            }

            const collapsed = sideBar.classList.toggle("collapsed");
            try {
                localStorage.setItem("sidebar", collapsed ? "collapsed" : "open");
            } catch (error) {
                // Ignore unavailable storage.
            }
        });

        backdrop.addEventListener("click", closeDrawer);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") closeDrawer();
        });

        sideBar.addEventListener("click", (event) => {
            if (mobileQuery.matches && event.target.closest(".sidebar-link")) closeDrawer();
        });

        mobileQuery.addEventListener("change", closeDrawer);
        window.addEventListener("resize", setNavHeight);
        setNavHeight();
    }

    document.querySelectorAll(".sidebar-link").forEach((sidebarLink) => {
        // Links that open a dialog (class "sidebar-action") are not pages, so they never become "active".
        if (sidebarLink.classList.contains("sidebar-action")) return;
        sidebarLink.addEventListener("click", () => {
            document.querySelectorAll(".sidebar-link").forEach((link) => {
                link.classList.toggle("active", link === sidebarLink);
            });
        });
    });

    // Delete confirmation is present on the admin dashboard, but not necessarily
    // on the service-catalog page, so every element is checked before use.
    const deleteCon = document.getElementById("deleteCon");
    const adminLayout = document.getElementById("adminLayout");
    const cancelDel = document.getElementById("cancelDel");
    const confirmDel = document.getElementById("confirmDel");
    const deleteForm = document.getElementById("deleteForm");

    document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const trigger = target.closest(".deleteAcc");
        if (!trigger) return;

        event.preventDefault();
        const deleteUrl = trigger.getAttribute("data-delete-url");
        if (!deleteUrl || !confirmDel || !deleteCon || !deleteForm) return;

        deleteForm.setAttribute("action", deleteUrl);
        deleteCon.classList.add("pop");
        adminLayout?.classList.add("pop");
    });

    cancelDel?.addEventListener("click", (event) => {
        event.preventDefault();
        deleteCon?.classList.remove("pop");
        adminLayout?.classList.remove("pop");
    });

    window.addEventListener("click", (event) => {
        if (
            deleteCon?.classList.contains("pop") &&
            !deleteCon.contains(event.target) &&
            !(event.target instanceof Element && event.target.closest(".deleteAcc"))
        ) {
            deleteCon.classList.remove("pop");
            adminLayout?.classList.remove("pop");
        }
    });

    // Copy email addresses without allowing the table row to navigate or jump.
    document.querySelectorAll(".copy-email").forEach((link) => {
        link.addEventListener("click", async (event) => {
            event.preventDefault();
            const email = link.dataset.email;
            if (!email) return;

            try {
                await navigator.clipboard.writeText(email);
                const original = link.innerHTML;
                link.innerHTML = "<i class='bx bx-check'></i> Copied!";
                window.setTimeout(() => {
                    link.innerHTML = original;
                }, 1500);
            } catch (error) {
                console.error("Failed to copy email:", error);
            }
        });
    });
})();