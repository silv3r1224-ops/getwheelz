// Mechanic dashboard: filter, search, sort and page through the bookings table.
// Same approach as owner-bookings.js: the server renders every booking row once with data-* attributes
// (status, mine / to-do, which periods it falls in, a timestamp, searchable text) and this file only
// shows, hides and reorders those rows. The chosen view survives the reload after "Mark Complete".

(() => {
    const toolbar = document.getElementById("bkToolbar");
    const tbody = document.querySelector("#bkTableWrap tbody");
    if (!toolbar || !tbody) return;

    const PAGE = 15;
    const STORE_KEY = "gw:mechanic-bookings";

    const rows = Array.from(tbody.querySelectorAll("tr.bk-row"));
    const chips = Array.from(toolbar.querySelectorAll("[data-bk-chip]"));
    const searchEl = document.getElementById("bkSearch");
    const periodEl = document.getElementById("bkPeriod");
    const sortEl = document.getElementById("bkSort");
    const resetEl = document.getElementById("bkReset");
    const wrapEl = document.getElementById("bkTableWrap");
    const emptyEl = document.getElementById("bkEmpty");
    const emptyTitle = document.getElementById("bkEmptyTitle");
    const emptyText = document.getElementById("bkEmptyText");
    const countEl = document.getElementById("bkCount");
    const moreEl = document.getElementById("bkMore");

    // open on the jobs waiting for me; with none, show everything
    const DEFAULT_CHIP = rows.some((r) => r.dataset.todo === "1") ? "todo" : "all";
    // queues are worked soonest-first; everything else reads like a history, newest first
    const DEFAULT_SORT = { todo: "soonest", pending: "soonest", confirmed: "soonest", mine: "latest", history: "latest", all: "latest" };

    const EMPTY = {
        todo: ["All caught up", "No confirmed jobs are waiting for you right now."],
        mine: ["No jobs yet", "Jobs the owner assigns to you will show up here."],
        pending: ["Nothing pending", "Every request has been answered by the owner."],
        confirmed: ["Nothing confirmed", "No confirmed bookings right now."],
        history: ["No history yet", "Completed and cancelled bookings are kept here."],
        all: ["Nothing here", "No bookings match these filters."],
    };

    const state = { chip: DEFAULT_CHIP, period: "any", sort: DEFAULT_SORT[DEFAULT_CHIP], sortChosen: false, q: "", limit: PAGE };

    const matchesChip = (row, chip) => {
        const s = row.dataset.status;
        switch (chip) {
            case "todo": return row.dataset.todo === "1";
            case "mine": return row.dataset.mine === "1";
            case "pending": return s === "pending";
            case "confirmed": return s === "confirmed";
            case "history": return s === "completed" || s === "cancelled";
            default: return true;
        }
    };
    const matchesPeriod = (row, period) => period === "any" || (row.dataset.periods || "").split(" ").includes(period);
    const matchesQuery = (row, q) => !q || (row.dataset.search || "").includes(q);

    const comparers = {
        soonest: (a, b) => Number(a.dataset.ts) - Number(b.dataset.ts),
        latest: (a, b) => Number(b.dataset.ts) - Number(a.dataset.ts),
        customer: (a, b) => (a.dataset.customer || "").localeCompare(b.dataset.customer || "") || Number(b.dataset.ts) - Number(a.dataset.ts),
    };

    const render = () => {
        const q = state.q.trim().toLowerCase();

        // chip counts follow the date + search filters, so they always say what a click will show
        const counts = {};
        chips.forEach((c) => (counts[c.dataset.bkChip] = 0));
        rows.forEach((row) => {
            if (!matchesPeriod(row, state.period) || !matchesQuery(row, q)) return;
            chips.forEach((c) => { if (matchesChip(row, c.dataset.bkChip)) counts[c.dataset.bkChip]++; });
        });
        chips.forEach((c) => {
            c.classList.toggle("active", c.dataset.bkChip === state.chip);
            c.setAttribute("aria-selected", c.dataset.bkChip === state.chip ? "true" : "false");
            const n = c.querySelector(".n");
            if (n) n.textContent = counts[c.dataset.bkChip];
        });

        const matching = rows.filter((row) => matchesChip(row, state.chip) && matchesPeriod(row, state.period) && matchesQuery(row, q));
        matching.sort(comparers[state.sort] || comparers.latest);

        const fragment = document.createDocumentFragment();
        matching.forEach((row) => fragment.appendChild(row));
        rows.forEach((row) => { if (!matching.includes(row)) row.hidden = true; });
        matching.forEach((row, i) => { row.hidden = i >= state.limit; });
        tbody.appendChild(fragment);

        const shown = Math.min(matching.length, state.limit);
        wrapEl.hidden = matching.length === 0;
        emptyEl.hidden = matching.length !== 0;
        if (!matching.length) {
            const filtered = q || state.period !== "any";
            const [title, text] = EMPTY[state.chip] || EMPTY.all;
            emptyTitle.textContent = filtered ? "No matching bookings" : title;
            emptyText.textContent = filtered ? "Try a different date or search, or clear the filters." : text;
        }
        countEl.textContent = matching.length ? "Showing " + shown + " of " + matching.length : "";
        const remaining = matching.length - shown;
        moreEl.hidden = remaining <= 0;
        moreEl.textContent = "Show " + Math.min(PAGE, remaining) + " more";

        sortEl.value = state.sort;
        periodEl.value = state.period;
        resetEl.hidden = !(q || state.period !== "any" || state.chip !== DEFAULT_CHIP);
        save();
    };

    function save() {
        try { sessionStorage.setItem(STORE_KEY, JSON.stringify(Object.assign({ at: Date.now() }, state))); }
        catch (e) { /* storage blocked: the view just resets on reload */ }
    }
    function restore() {
        try {
            const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
            // only trust a view saved a moment ago (the page reloaded after "Mark Complete"),
            // so coming back later never opens on a stale filter that hides new jobs
            if (!saved || Date.now() - saved.at > 60000) return;
            if (chips.some((c) => c.dataset.bkChip === saved.chip)) state.chip = saved.chip;
            if (["any", "today", "week", "month"].includes(saved.period)) state.period = saved.period;
            if (comparers[saved.sort]) state.sort = saved.sort;
            state.sortChosen = !!saved.sortChosen;
            state.q = typeof saved.q === "string" ? saved.q : "";
            searchEl.value = state.q;
        } catch (e) { /* ignore a bad saved value */ }
    }

    const setChip = (chip) => {
        state.chip = chip;
        state.limit = PAGE;
        if (!state.sortChosen) state.sort = DEFAULT_SORT[chip] || "latest";
        render();
    };

    chips.forEach((c) => c.addEventListener("click", () => setChip(c.dataset.bkChip)));

    let timer;
    searchEl.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => { state.q = searchEl.value; state.limit = PAGE; render(); }, 120);
    });
    periodEl.addEventListener("change", () => { state.period = periodEl.value; state.limit = PAGE; render(); });
    sortEl.addEventListener("change", () => { state.sort = sortEl.value; state.sortChosen = true; state.limit = PAGE; render(); });
    moreEl.addEventListener("click", () => { state.limit += PAGE; render(); });
    resetEl.addEventListener("click", () => {
        state.chip = DEFAULT_CHIP; state.period = "any"; state.q = ""; state.sortChosen = false;
        state.sort = DEFAULT_SORT[DEFAULT_CHIP]; state.limit = PAGE;
        searchEl.value = "";
        render();
    });

    // the stat cards at the top jump straight to that view
    document.querySelectorAll("[data-bk-filter]").forEach((card) => {
        const go = () => {
            state.period = "any"; state.q = ""; searchEl.value = "";
            setChip(card.dataset.bkFilter);
            document.getElementById("mBookings").scrollIntoView({ behavior: "smooth", block: "start" });
        };
        card.addEventListener("click", go);
        card.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
        });
    });

    restore();
    render();
})();