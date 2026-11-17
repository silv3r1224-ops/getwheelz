// Inbox (Phase 5): compact rows, one shared popup, and a bottom bar that acts on the section being viewed.
//  - clicking a row opens the popup with the full message and marks the mail read
//  - the Delete button floats at the bottom of the popup (only for mail that may be deleted)
//  - "Mark All as Read" and "Delete All" (which asks first) apply to the visible section only
(function () {
    "use strict";
    var root = document.getElementById("inboxPanels");
    if (!root) return;

    var panels = Array.prototype.slice.call(root.querySelectorAll(".inbox-panel"));
    var tabs = Array.prototype.slice.call(document.querySelectorAll("#inboxTabs .inbox-tab"));
    var sideLinks = Array.prototype.slice.call(document.querySelectorAll(".js-inbox-nav"));
    var csrf = root.dataset.csrf;
    var pop = document.getElementById("mailPop");
    var popCard = pop.querySelector(".mail-pop-card");
    var popBody = document.getElementById("mailPopBody");
    var popTitle = document.getElementById("mailPopTitle");
    var popIcon = document.getElementById("mailPopIcon");
    var popDelete = document.getElementById("mailPopDelete");
    var confirmPop = document.getElementById("confirmPop");
    var bar = document.getElementById("mailBar");
    var barLabel = document.getElementById("mailBarLabel");
    var markAllBtn = document.getElementById("markAllRead");
    var deleteAllBtn = document.getElementById("deleteAll");
    var toast = document.getElementById("mailToast");
    var current = null;      // the row shown in the popup
    var opener = null;       // what to give focus back to
    var activeId = null;     // the section being viewed

    // ---------------------------------------------------------------- helpers
    function post(url, payload) {
        return fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrf, "X-Requested-With": "fetch", "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(function (res) {
            return res.json().catch(function () { return { ok: false }; });
        });
    }
    function say(text) {
        toast.textContent = text;
        toast.hidden = false;
        clearTimeout(say.t);
        say.t = setTimeout(function () { toast.hidden = true; }, 2600);
    }
    function panelOf(el) { return el.closest(".inbox-panel"); }
    function rowsOf(panel) { return Array.prototype.slice.call(panel.querySelectorAll(".mail-row")); }
    function activePanel() { return document.getElementById(activeId); }

    // ---------------------------------------------------------------- counts, dots, bottom bar
    function refresh() {
        panels.forEach(function (p) {
            var section = p.dataset.section;
            var rows = rowsOf(p);
            var unread = rows.filter(function (r) { return r.classList.contains("is-unread"); }).length;
            var dot = document.querySelector('[data-dot="' + section + '"]');
            if (dot) dot.hidden = unread === 0;
            var count = document.querySelector('[data-count-for="' + section + '"]');
            if (count && section !== "reports") count.textContent = unread + " new";
            var tab = document.querySelector('#inboxTabs .inbox-tab[data-panel="' + p.id + '"]');
            if (tab) tab.dataset.count = String(rows.length);
            var empty = p.querySelector(".inbox-panel-empty");
            if (empty) empty.hidden = rows.length > 0;
        });
        updateBar();
        if (window.refreshMailDot) window.refreshMailDot();
    }
    function updateBar() {
        var p = activePanel();
        if (!p) return;
        var rows = rowsOf(p);
        var label = (p.querySelector(".inbox-panel-title") || {}).textContent || "";
        barLabel.textContent = label.trim();
        var hasUnread = rows.some(function (r) { return r.classList.contains("is-unread"); });
        // only sections that keep read state can have unread rows; Reports counts too (mail + feedback)
        markAllBtn.disabled = !hasUnread;
        markAllBtn.title = hasUnread ? "" : "Nothing unread in this section";
        var hasDeletable = rows.some(function (r) { return r.dataset.deletable === "1"; });
        deleteAllBtn.disabled = !hasDeletable;
        deleteAllBtn.title = hasDeletable ? "" : "Nothing in this section can be deleted";
    }

    // ---------------------------------------------------------------- sections
    function openSection(id) {
        if (!document.getElementById(id)) id = panels[0] && panels[0].id;
        activeId = id;
        panels.forEach(function (p) { p.classList.toggle("is-active", p.id === id); });
        tabs.forEach(function (t) {
            var on = t.dataset.panel === id;
            t.classList.toggle("is-active", on);
            t.setAttribute("aria-selected", on ? "true" : "false");
        });
        sideLinks.forEach(function (l) {
            var on = l.dataset.panel === id;
            l.classList.toggle("active", on);
            l.setAttribute("aria-current", on ? "true" : "false");
        });
        updateBar();
    }
    tabs.concat(sideLinks).forEach(function (b) {
        b.addEventListener("click", function () { openSection(b.dataset.panel); });
    });
    var wanted = location.hash && document.getElementById(location.hash.slice(1));
    var firstWithMail = tabs.find(function (t) { return parseInt(t.dataset.count || "0", 10) > 0; }) || tabs[0];
    openSection(wanted && wanted.classList.contains("inbox-panel") ? wanted.id : (firstWithMail ? firstWithMail.dataset.panel : null));

    // ---------------------------------------------------------------- popup
    function focusables(scope) {
        return Array.prototype.slice.call(scope.querySelectorAll(
            'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select, textarea, summary, [tabindex]:not([tabindex="-1"])'
        )).filter(function (el) { return !el.hidden && el.offsetParent !== null; });
    }
    function openRow(row, trigger) {
        var tpl = row.querySelector("template.mail-body");
        if (!tpl) return;
        current = row;
        opener = trigger || row.querySelector("[data-open]");
        popTitle.textContent = tpl.dataset.title || "";
        popIcon.className = "bx " + (tpl.dataset.icon || "bx-envelope");
        popBody.innerHTML = "";
        popBody.appendChild(tpl.content.cloneNode(true));
        popDelete.hidden = row.dataset.deletable !== "1";
        popDelete.disabled = false;
        pop.hidden = false;
        document.body.style.overflow = "hidden";
        popCard.focus();
        markRead(row);   // opening a mail marks it read
    }
    function closePop() {
        if (pop.hidden) return;
        pop.hidden = true;
        popBody.innerHTML = "";
        document.body.style.overflow = "";
        current = null;
        if (opener && document.contains(opener)) opener.focus();
        opener = null;
    }
    function markRead(row) {
        if (!row.classList.contains("is-unread")) return;
        var url = row.dataset.markUrl;
        // show it as read straight away; put it back if the server refuses
        row.classList.remove("is-unread");
        var dot = row.querySelector(".mail-dot");
        if (dot) dot.hidden = true;
        refresh();
        if (!url) return;
        post(url, { kind: row.dataset.kind, id: row.dataset.id }).then(function (data) {
            if (data && data.ok) return;
            row.classList.add("is-unread");
            if (dot) dot.hidden = false;
            refresh();
        }).catch(function () {
            row.classList.add("is-unread");
            if (dot) dot.hidden = false;
            refresh();
        });
    }
    root.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-open]");
        if (!btn) return;
        var row = btn.closest(".mail-row");
        if (row) openRow(row, btn);
    });
    document.getElementById("mailPopClose").addEventListener("click", closePop);
    pop.addEventListener("click", function (e) { if (e.target === pop) closePop(); });

    popDelete.addEventListener("click", function () {
        var row = current;
        if (!row || !row.dataset.delUrl) return;
        popDelete.disabled = true;
        post(row.dataset.delUrl, { kind: row.dataset.delKind, id: row.dataset.id }).then(function (data) {
            if (!data || !data.ok) {
                popDelete.disabled = false;
                say("That mail could not be deleted.");
                return;
            }
            closePop();
            row.classList.add("is-leaving");
            setTimeout(function () { row.remove(); refresh(); }, 220);
            say("Deleted.");
        }).catch(function () {
            popDelete.disabled = false;
            say("That mail could not be deleted.");
        });
    });

    // ---------------------------------------------------------------- bottom bar
    markAllBtn.addEventListener("click", function () {
        var p = activePanel();
        if (!p || markAllBtn.disabled) return;
        markAllBtn.disabled = true;
        post(root.dataset.markUrl, { section: p.dataset.section }).then(function (data) {
            if (!data || !data.ok) { say("Could not mark these as read."); updateBar(); return; }
            rowsOf(p).forEach(function (r) {
                r.classList.remove("is-unread");
                var d = r.querySelector(".mail-dot");
                if (d) d.hidden = true;
                r.dataset.markUrl = "";
            });
            refresh();
            say("All marked as read.");
        }).catch(function () { say("Could not mark these as read."); updateBar(); });
    });

    function closeConfirm() {
        confirmPop.hidden = true;
        document.body.style.overflow = "";
        if (deleteAllBtn) deleteAllBtn.focus();
    }
    deleteAllBtn.addEventListener("click", function () {
        var p = activePanel();
        if (!p || deleteAllBtn.disabled) return;
        var n = rowsOf(p).filter(function (r) { return r.dataset.deletable === "1"; }).length;
        document.getElementById("confirmTitle").textContent = "Delete all in " + barLabel.textContent + "?";
        document.getElementById("confirmText").textContent =
            "This removes " + n + " item" + (n === 1 ? "" : "s") + " from this section. " + (p.dataset.deleteNote || "") +
            " This cannot be undone.";
        confirmPop.hidden = false;
        document.body.style.overflow = "hidden";
        confirmPop.querySelector(".mail-pop-card").focus();
    });
    document.getElementById("confirmCancel").addEventListener("click", closeConfirm);
    confirmPop.addEventListener("click", function (e) { if (e.target === confirmPop) closeConfirm(); });
    document.getElementById("confirmOk").addEventListener("click", function () {
        var p = activePanel();
        if (!p) return closeConfirm();
        var ok = this;
        ok.disabled = true;
        post(root.dataset.deleteAllUrl, { section: p.dataset.section }).then(function (data) {
            ok.disabled = false;
            if (!data || !data.ok) { closeConfirm(); say("Could not delete these."); return; }
            // what is removed depends on the section (some items always stay), so show the server's truth
            var msg = "Deleted " + data.deleted + " item" + (data.deleted === 1 ? "" : "s") + ".";
            location.hash = p.id;
            var live = window.GWLive ? window.GWLive.refresh() : Promise.resolve(false);
            live.then(function (done) {
                if (done === true) { closeConfirm(); say(msg); return; }      // patched in place
                try { sessionStorage.setItem("mailToast", msg); } catch (e) { /* ignore */ }
                location.reload();                                              // fallback
            });
        }).catch(function () { ok.disabled = false; closeConfirm(); say("Could not delete these."); });
    });

    // ---------------------------------------------------------------- keyboard: Esc closes, Tab stays inside
    document.addEventListener("keydown", function (e) {
        var open = !confirmPop.hidden ? confirmPop : (!pop.hidden ? pop : null);
        if (!open) return;
        if (e.key === "Escape") { e.preventDefault(); if (open === confirmPop) closeConfirm(); else closePop(); return; }
        if (e.key !== "Tab") return;
        var items = focusables(open.querySelector(".mail-pop-card"));
        if (!items.length) { e.preventDefault(); return; }
        var first = items[0], last = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === first || document.activeElement === open.querySelector(".mail-pop-card"))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });

    try {
        var saved = sessionStorage.getItem("mailToast");
        if (saved) { sessionStorage.removeItem("mailToast"); say(saved); }
    } catch (e) { /* ignore */ }
    refresh();
})();
