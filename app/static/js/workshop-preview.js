// Workshop quick-view modal for customer surfaces (search results + home cards).
// Any element with [data-wp] opens it; the attribute holds a JSON payload:
// { id, name, address, photo, open, km, services[], url, lat, lng }
(() => {
    const modal = document.getElementById("wpPreview");
    if (!modal) return;

    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    const byId = (id) => document.getElementById(id);
    const nameEl = byId("wpvName");
    const addrEl = byId("wpvAddr");
    const badgeEl = byId("wpvBadge");
    const photoWrap = byId("wpvPhotoWrap");
    const imgEl = byId("wpvPhoto");
    const icoEl = byId("wpvPhotoIco");
    const photoBtn = photoWrap ? photoWrap.querySelector(".wp-photo-open") : null;
    const kmEl = byId("wpvKm");
    const svcEl = byId("wpvServices");
    const teamEl = byId("wpvTeam");
    const linkEl = byId("wpvLink");
    const dirEl = byId("wpvDir");

    let lastFocus = null;

    function open(data, trigger) {
        lastFocus = trigger;
        nameEl.textContent = data.name || "Workshop";
        addrEl.textContent = data.address || "Address not listed";
        addrEl.hidden = !data.address;

        badgeEl.textContent = data.open ? "Open now" : "Closed right now";
        badgeEl.className = "wp-badge " + (data.open ? "on" : "off");

        if (data.photo) {
            imgEl.src = data.photo;
            imgEl.alt = data.name || "Workshop";
            imgEl.hidden = false;
            icoEl.hidden = true;
            if (photoBtn) photoBtn.hidden = false;
        } else {
            imgEl.hidden = true;
            icoEl.hidden = false;
            if (photoBtn) photoBtn.hidden = true;
        }

        if (data.km != null && window.GW && window.GW.formatDistance) {
            kmEl.textContent = window.GW.formatDistance(Number(data.km)) + " away";
            kmEl.hidden = false;
        } else {
            kmEl.hidden = true;
        }

        svcEl.replaceChildren();
        if (data.services && data.services.length) {
            data.services.forEach((s) => {
                const t = document.createElement("span");
                t.className = "wp-tag";
                t.textContent = s;
                svcEl.appendChild(t);
            });
            svcEl.hidden = false;
        } else {
            svcEl.hidden = true;
        }

        if (teamEl) {
            teamEl.replaceChildren();
            if (data.team && data.team.length) {
                const title = document.createElement("div");
                title.className = "wp-team-title";
                title.innerHTML = "<i class='bx bx-group'></i> Mechanics (" + data.team.length + ")";
                teamEl.appendChild(title);

                const list = document.createElement("div");
                list.className = "wp-team-list";
                data.team.forEach((m) => {
                    const item = document.createElement("div");
                    item.className = "wp-mechanic";
                    const initial = m.name ? m.name.charAt(0).toUpperCase() : "M";
                    const avHtml = m.profile_picture
                        ? "<img src='/static/" + esc(m.profile_picture) + "' alt='" + esc(m.name) + "'>"
                        : "<span>" + esc(initial) + "</span>";
                    const exp = m.experience_yrs ? m.experience_yrs + " yrs exp" : "Mechanic";
                    item.innerHTML = "<div class='wp-mech-av'>" + avHtml + "</div><div><strong>" + esc(m.name) + "</strong><small>" + esc(exp) + "</small></div>";
                    list.appendChild(item);
                });
                teamEl.appendChild(list);
                teamEl.hidden = false;
            } else {
                teamEl.hidden = true;
            }
        }

        linkEl.href = data.url || "#";
        if (data.lat != null && data.lng != null) {
            dirEl.href = "https://www.google.com/maps/dir/?api=1&destination=" + data.lat + "," + data.lng;
            dirEl.hidden = false;
        } else {
            dirEl.hidden = true;
        }

        const bmBtn = byId("wpvBm");
        if (bmBtn) {
            bmBtn.hidden = !window.GW_CUSTOMER;
            if (window.GW_CUSTOMER && window.GW && window.GW.bookmarkState) {
                bmBtn.dataset.wId = String(data.id || "");
                window.GW.setBookmarkButton(bmBtn, window.GW.bookmarkState(data.id));
            }
        }

        modal.classList.add("is-open");
        document.body.style.overflow = "hidden";
        if (trigger) trigger.setAttribute("aria-expanded", "true");
    }

    function close() {
        modal.classList.remove("is-open");
        document.body.style.overflow = "";
        if (lastFocus) {
            lastFocus.setAttribute("aria-expanded", "false");
            lastFocus.focus();
        }
    }

    document.addEventListener("click", (e) => {
        const trigger = e.target.closest("[data-wp]");
        if (trigger) {
            e.preventDefault();
            e.stopPropagation();
            let data = null;
            try {
                data = JSON.parse(trigger.getAttribute("data-wp"));
            } catch (_) {
                /* bad payload; ignore */
            }
            if (data) open(data, trigger);
            return;
        }

        if (modal.classList.contains("is-open")) {
            if (e.target === modal || e.target.closest("[data-wp-close]")) close();
        }
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modal.classList.contains("is-open")) {
            close();
            return;
        }
        if ((e.key === "Enter" || e.key === " ") && e.target && e.target.matches("[data-wp]")) {
            e.preventDefault();
            e.target.click();
        }
    });
})();
