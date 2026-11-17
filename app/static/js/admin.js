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
        deleteForm.__triggerBtn = trigger;
        deleteForm.__force = false;
        resetDeleteDialog();
        deleteCon.classList.add("pop");
        adminLayout?.classList.add("pop");
    });

    // The dialog's text can be replaced by the server's impact summary (owners with a workshop).
    const deleteText = deleteCon?.querySelector("p");
    const deleteTitleEl = document.getElementById("deleteTitle");
    const defaultDeleteText = deleteText ? deleteText.textContent : "";
    const defaultDeleteTitle = deleteTitleEl ? deleteTitleEl.textContent : "";
    function resetDeleteDialog() {
        if (deleteText) deleteText.textContent = defaultDeleteText;
        if (deleteTitleEl) deleteTitleEl.textContent = defaultDeleteTitle;
        if (confirmDel) confirmDel.textContent = "Yes, delete";
    }

    cancelDel?.addEventListener("click", (event) => {
        event.preventDefault();
        deleteCon?.classList.remove("pop");
        adminLayout?.classList.remove("pop");
    });

    deleteForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        deleteCon?.classList.remove("pop");
        adminLayout?.classList.remove("pop");

        const deleteUrl = deleteForm.getAttribute("action");
        const trigger = deleteForm.__triggerBtn;
        const csrfToken = deleteForm.querySelector('input[name="csrf_token"]')?.value || "";
        // On a profile page there is no table row to remove, so ask the server for a redirect.
        const onProfilePage = !!document.querySelector(".profile-head");

        if (!deleteUrl) return;

        try {
            const res = await fetch(deleteUrl, {
                method: "POST",
                headers: {
                    "X-Requested-With": "fetch",
                    "Accept": "application/json",
                    "X-CSRFToken": csrfToken,
                    ...(deleteForm.__force ? { "X-Force-Delete": "1" } : {}),
                    ...(onProfilePage ? { "X-After-Delete": "redirect" } : {}),
                },
                credentials: "same-origin",
            });
            let data = null;
            try {
                data = await res.json();
            } catch (err) {
                // If not JSON, fallback to reload
                window.location.reload();
                return;
            }

            if (data && data.needs_confirm) {
                // Live data is affected: show exactly what, and let the admin confirm knowingly.
                if (deleteTitleEl) deleteTitleEl.textContent = "This also deletes a workshop";
                if (deleteText) deleteText.textContent = data.error;
                if (confirmDel) confirmDel.textContent = "Delete everything";
                deleteForm.__force = true;
                deleteCon?.classList.add("pop");
                adminLayout?.classList.add("pop");
                return;
            }
            if (data && data.ok && data.redirect) {
                window.location.href = data.redirect;
                return;
            }
            if (data && (data.ok || data.gone)) {
                if (data.gone) alert(data.error);
                // Remove the row from search results / table without reloading,
                // and also remove any matching rows across all admin tables by delete-url or u_id.
                const targetUrl = deleteUrl;
                document.querySelectorAll(`tr`).forEach((tr) => {
                    const btn = tr.querySelector(".deleteAcc");
                    if (btn && btn.getAttribute("data-delete-url") === targetUrl) {
                        tr.style.transition = "opacity 0.3s ease";
                        tr.style.opacity = "0";
                        setTimeout(() => tr.remove(), 300);
                    }
                });
                if (trigger) {
                    const tr = trigger.closest("tr");
                    if (tr) {
                        tr.style.transition = "opacity 0.3s ease";
                        tr.style.opacity = "0";
                        setTimeout(() => tr.remove(), 300);
                    }
                }
            } else {
                alert(data?.error || "Could not delete record.");
            }
        } catch (error) {
            console.error("Delete failed:", error);
            window.location.reload();
        }
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

    // Generic confirmation dialog for admin actions (e.g. cancelling a booking).
    // Any element with class .js-confirm and data-url/data-title/data-msg opens it;
    // the form then submits to data-url with the page's CSRF token.
    const confirmCon = document.getElementById("confirmCon");
    const confirmForm = document.getElementById("confirmForm");
    const confirmTitle = document.getElementById("confirmTitle");
    const confirmMsg = document.getElementById("confirmMsg");
    const confirmBtn = document.getElementById("confirmBtn");
    const cancelConfirm = document.getElementById("cancelConfirm");

    const openConfirm = (url, title, msg) => {
        if (!confirmCon || !confirmForm) return;
        confirmForm.setAttribute("action", url);
        if (confirmTitle) confirmTitle.textContent = title || "Are you sure?";
        if (confirmMsg) confirmMsg.textContent = msg || "";
        if (confirmBtn) confirmBtn.textContent = "Yes, continue";
        confirmCon.classList.add("pop");
        adminLayout?.classList.add("pop");
    };
    const closeConfirm = () => {
        confirmCon?.classList.remove("pop");
        adminLayout?.classList.remove("pop");
    };

    document.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const trigger = target.closest(".js-confirm");
        if (trigger) {
            event.preventDefault();
            openConfirm(trigger.dataset.url, trigger.dataset.title, trigger.dataset.msg);
        }
    });

    cancelConfirm?.addEventListener("click", (event) => {
        event.preventDefault();
        closeConfirm();
    });

    window.addEventListener("click", (event) => {
        if (
            confirmCon?.classList.contains("pop") &&
            !confirmCon.contains(event.target) &&
            !(event.target instanceof Element && event.target.closest(".js-confirm"))
        ) {
            closeConfirm();
        }
    });

    // Copy email addresses without allowing the table row to navigate or jump.
    // Delegated so it also covers rows rendered by the live search below.
    document.addEventListener("click", async (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const link = target.closest(".copy-email");
        if (!link) return;

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
})();

// Live record search: fetch the match as JSON and render it in place — no page reload.
// The server-side result block stays as a fallback for browsers without fetch/JS.
(() => {
    const form = document.getElementById("adminSearchForm");
    if (!form || !window.fetch) return;

    const box = document.getElementById("adminSearchResults");
    if (!box) return;

    // A reload must never bring a previous search back: strip any leftover
    // ?q=&role= from the address bar (search results live only in the DOM).
    try {
        const url = new URL(window.location.href);
        if (url.searchParams.has("q") || url.searchParams.has("role")) {
            const clean = new URL(form.action, window.location.origin);
            history.replaceState(null, "", clean.pathname);
        }
    } catch (error) {
        /* history clean-up is a nicety, not a requirement */
    }

    const btn = form.querySelector('button[type="submit"]');
    const originalBtn = btn ? btn.innerHTML : "";

    // Multi-select + bulk delete for the results (js/pages/bulk_select.js reads these attributes).
    // Without them (the script is not on the page) results stay view / delete-one only.
    const bulkUrl = box.dataset.bulkUrl || "";
    const bulkCsrf = box.dataset.csrf || "";

    function renderFound(records, truncated) {
        const bulk = !!bulkUrl;

        const meta = document.createElement("p");
        meta.className = "search-meta" + (truncated ? " is-warn" : "");
        meta.textContent = truncated
            ? `Showing the first ${records.length} matches. Narrow the search (add a role or status) to see the rest.`
            : `${records.length} ${records.length === 1 ? "record" : "records"} found.`;

        const table = document.createElement("table");
        table.className = "admin-table";
        table.style.marginTop = "14px";
        if (bulk) {
            // results can mix customers, owners and mechanics: each row carries its own role
            table.dataset.bulkRole = "mixed";
            table.dataset.bulkUrl = bulkUrl;
            table.dataset.csrf = bulkCsrf;
            table.dataset.emptyText = "All matching records were deleted.";
        }
        table.innerHTML = `
            <thead><tr>
                ${bulk ? '<th class="bulk-col"><input type="checkbox" class="bulk-all" aria-label="Select all search results"></th>' : ""}
                <th>U_id</th><th>Role_id</th><th>Role</th>
                <th>Name</th><th>Email</th><th>Joined</th><th>Action</th>
            </tr></thead>`;

        const tbody = document.createElement("tbody");
        records.forEach((record) => {
            const tr = document.createElement("tr");
            if (bulk) {
                tr.dataset.uid = record.u_id;
                tr.dataset.role = record.role;
                tr.dataset.label = record.name;
                const tdPick = document.createElement("td");
                tdPick.className = "bulk-col";
                const pick = document.createElement("input");
                pick.type = "checkbox";
                pick.className = "bulk-pick";
                pick.setAttribute("aria-label", `Select ${record.name}`);
                tdPick.appendChild(pick);
                tr.appendChild(tdPick);
            }

            const tdUid = document.createElement("td");
            tdUid.textContent = record.u_id;
            const tdRid = document.createElement("td");
            tdRid.textContent = record.role_id;
            const tdRole = document.createElement("td");
            tdRole.textContent = record.role.charAt(0).toUpperCase() + record.role.slice(1);
            if (record.is_suspended) tdRole.textContent += " (suspended)";

            const tdName = document.createElement("td");
            const nameLink = document.createElement("a");
            nameLink.className = "profile-link";
            nameLink.href = record.profile_url;
            nameLink.textContent = record.name;
            tdName.appendChild(nameLink);

            const tdEmail = document.createElement("td");
            tdEmail.textContent = record.email;

            const tdJoined = document.createElement("td");
            tdJoined.textContent = record.joined;

            const tdAction = document.createElement("td");
            const viewLink = document.createElement("a");
            viewLink.className = "view-profile-btn";
            viewLink.href = record.profile_url;
            viewLink.title = "View profile";
            viewLink.innerHTML = "<i class='bx bx-user-circle'></i> View profile";
            const delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className = "deleteAcc";
            delBtn.dataset.deleteUrl = record.delete_url;
            delBtn.innerHTML = "<i class='bx bx-trash'></i> Delete";
            tdAction.append(viewLink, delBtn);

            tr.append(tdUid, tdRid, tdRole, tdName, tdEmail, tdJoined, tdAction);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        box.append(meta, table);
    }

    function render(message, isError) {
        box.replaceChildren();
        const p = document.createElement("p");
        p.className = "no-results neo-note";
        p.textContent = message;
        if (isError) p.style.color = "var(--award-coral-hi)";
        box.appendChild(p);
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const q = form.q.value.trim();
        if (!q) {
            form.q.focus();
            return;
        }

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = "<i class='bx bx-loader-circle bx-spin'></i>";
        }

        try {
            const url = new URL(form.action, window.location.origin);
            url.searchParams.set("q", q);
            if (form.role.value) url.searchParams.set("role", form.role.value);
            if (form.status.value) url.searchParams.set("status", form.status.value);

            const res = await fetch(url, {
                headers: {
                    "X-Requested-With": "fetch",
                    Accept: "application/json",
                },
                credentials: "same-origin",
            });
            let data = null;
            let bodyHint = "";
            try {
                data = await res.json();
            } catch (error) {
                try {
                    bodyHint = (await res.text()).slice(0, 140).replace(/\s+/g, " ");
                } catch (ignore) {
                    /* no body available */
                }
            }
            if (!data || !data.ok) {
                const status = `HTTP ${res.status} ${res.statusText}`;
                let hint = "";
                if (res.redirected) {
                    hint = " (request was redirected — your session may have expired; reload the page)";
                } else if (data && data.error) {
                    hint = ` (${data.error})`;
                } else if (bodyHint) {
                    hint = ` — got non-JSON: “${bodyHint}”`;
                }
                render(`Could not search right now (${status}${hint}). Please try again.`, true);
                return;
            }
            if (!data.found || !data.records || !data.records.length) {
                render("No matching records found.");
                return;
            }
            box.replaceChildren();
            renderFound(data.records, data.truncated === true);
        } catch (error) {
            render("Could not reach the server. Please try again.", true);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalBtn;
            }
        }
    });
})();