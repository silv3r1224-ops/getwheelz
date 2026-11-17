// NEO's guided tour (console card: NEO thinks "....", then types each step; spotlight morph; reduced-motion safe). Starts by itself on a new account's first login (GW_TOUR.pending) and any time the
// "?" button in the navbar is pressed. Each role has its own steps; a step whose element is not on the page
// (e.g. a mechanic with no workshop yet has no "My Team") is skipped automatically.
(function () {
    'use strict';
    var cfg = window.GW_TOUR;
    if (!cfg || !cfg.role) return;
    var KEY = 'gw_tour';
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var $ = function (id) { return document.getElementById(id); };
    var spot, ring, card, panel, bot, steps, cur = -1, dir = 1, raf = 0, ready = false, opened = false, idle = 0;
    var PAGE_LABEL = { home: 'your dashboard', profile: 'your profile' };

    // ---------- the steps ----------
    function byHeading(text) {
        return function () {
            var h = Array.prototype.find.call(document.querySelectorAll('h2'), function (x) {
                return x.textContent.toLowerCase().indexOf(text) !== -1;
            });
            return h && (h.closest('section') || h);
        };
    }
    function openEdit() { var c = $('profileCard'); if (c) c.classList.add('is-editing'); }
    var hi = { title: 'Hi ' + (cfg.name || 'there') + ', I\u2019m NEO!', mood: 'wave', page: 'home' };
    var bye = function (text) {
        return { page: 'profile', title: 'You\u2019re all set!', mood: 'excited',
            text: text + ' If you ever want me again, press the ? button at the top of the page.' };
    };
    var photo = { page: 'profile', sel: '#avatarPreview', title: 'Add a profile photo', mood: 'happy',
        text: 'A friendly photo makes your profile feel real. Click your picture to upload one.' };
    var edit = function (text) {
        return { page: 'profile', sel: '#editToggleBtn', title: 'Keep your details up to date', mood: 'working', text: text };
    };

    var ROLES = {
        mechanic: [
            Object.assign({}, hi, { text: 'I\u2019ll show you around in about a minute: your dashboard first, then how to add your experience so owners can trust your profile. You can skip any time.' }),
            { page: 'home', sel: '#browseSearch', title: 'Find a workshop', mood: 'working', text: 'Search by workshop name or area to find a place to work.' },
            { page: 'home', sel: '#serviceChips', title: 'Filter by service', mood: 'happy', text: 'Tap a service to see only the workshops that offer it.' },
            { page: 'home', sel: '#hiringNow', title: 'Send a join request', mood: 'excited', text: 'These workshops have room for mechanics. Press Join on one and its owner will look at your profile, so a complete profile with your experience really helps.' },
            { page: 'home', sel: '#yourRequests', title: 'Track your requests', mood: 'neutral', text: 'Requests you have sent wait here until the owner accepts or declines them.' },
            { page: 'home', sel: '#mStatus', title: 'Set your availability', mood: 'happy', text: 'Switch to Active when you are ready for jobs. Your owner and team can see whether you are available.' },
            { page: 'home', sel: '#mBookings', title: 'Your jobs', mood: 'working', text: 'Bookings assigned to you appear here. Use the search and the date filter to find a job quickly.' },
            { page: 'home', sel: '#mOwner', title: 'Your workshop owner', mood: 'neutral', text: 'See who owns the workshop you work for.' },
            { page: 'home', sel: '#mTeam', title: 'Your team', mood: 'happy', text: 'Tap a teammate to see their profile and experience.' },
            { page: 'home', sel: '#mLeave', title: 'Need time off?', mood: 'neutral', text: 'Send a leave request with a reason. Your owner approves it and you can follow its status here.' },
            { page: 'profile', sel: '#editToggleBtn', title: 'Now let\u2019s add your experience', mood: 'excited', text: 'Owners check your experience before accepting you, and it shows on your public profile. Press Edit to open your details.' },
            { page: 'profile', sel: '#experience_yrs', before: openEdit, title: 'Years of experience', mood: 'working', text: 'Type how many years you have worked as a mechanic. This is the number owners and customers see next to your name.' },
            { page: 'profile', sel: '#phone_number', title: 'Add your phone number', mood: 'happy', text: 'So your workshop can reach you when plans change.' },
            { page: 'profile', sel: '#profileEditForm button[type="submit"]', title: 'Save your changes', mood: 'excited', text: 'Press Save changes so your experience is stored. You can come back and update it as you grow.' },
            photo,
            bye('Your profile is ready for owners to see.')
        ],
        customer: [
            Object.assign({}, hi, { text: 'I\u2019ll show you how to find a workshop and book a service. It takes about a minute, and you can skip any time.' }),
            { page: 'home', sel: '#hero-search-form', title: 'Search for what you need', mood: 'working', text: 'Type a service such as engine repair or tyres and press search to see the workshops that offer it.' },
            { page: 'home', sel: '#location-btn', title: 'Use your location', mood: 'happy', text: 'Press this and I will show the workshops closest to you first.' },
            { page: 'home', sel: '#rec-track', title: 'Recommended workshops', mood: 'excited', text: 'Recommendations glide by in a loop — hover or touch to pause. Open one to see its services, prices and mechanics.' },
            { page: 'home', sel: byHeading('browse by service'), title: 'Browse by service', mood: 'happy', text: 'Tap a service to see every workshop that offers it.' },
            { page: 'home', sel: '#map', title: 'Workshops on the map', mood: 'neutral', text: 'See where workshops are around you.' },
            { page: 'home', sel: byHeading('how booking works'), title: 'How booking works', mood: 'working', text: 'Pick a workshop and a service, choose a time and send your request. The workshop then confirms it.' },
            { page: 'home', sel: function () { return document.querySelector('.nav-links a[href="' + cfg.urls.bookings + '"]'); }, title: 'My Bookings', mood: 'happy', text: 'Follow your upcoming appointments and past jobs here, with the status of each one.' },
            { page: 'home', sel: '.nav-profile', title: 'Your profile', mood: 'excited', text: 'This is your profile. Let me show you how to complete it.' },
            edit('Press Edit to update your details so workshops can reach you.'),
            { page: 'profile', sel: '#phone_number', before: openEdit, title: 'Add your phone number', mood: 'working', text: 'A phone number lets a workshop call you about your booking. Press Save changes when you are done.' },
            photo,
            bye('Happy booking!')
        ],
        owner: [
            Object.assign({}, hi, { text: 'I\u2019ll show you how to get your workshop listed and start taking bookings. It takes about a minute, and you can skip any time.' }),
            { page: 'home', sel: '.owner-welcome .ow-steps', title: 'Three steps to get started', mood: 'happy', text: 'Create your workshop, add your services, then take bookings and build a team.' },
            { page: 'home', sel: '#create-workshop-btn', title: 'Create your workshop', mood: 'excited', text: 'Start here: add its name and address, and drop a pin on the map so customers nearby can find you.' },
            { page: 'home', sel: '.oc-toggle-form', title: 'Open or closed', mood: 'happy', text: 'Let customers know whether you are taking work right now.' },
            { page: 'home', sel: '#services', title: 'Add your services', mood: 'working', text: 'Choose services from the catalog and set a price range and duration for each. Customers search by these.' },
            { page: 'home', sel: '#bookings', title: 'Bookings', mood: 'excited', text: 'New booking requests arrive here. Review them, confirm them and assign a mechanic from your team.' },
            { page: 'home', sel: '#joiningRequests', title: 'Mechanics who want to join', mood: 'happy', text: 'Mechanics send you requests. Open one to see their profile and experience, then accept or decline.' },
            { page: 'home', sel: '#leaveRequests', title: 'Leave requests', mood: 'neutral', text: 'Time-off requests from your mechanics wait here for your approval.' },
            { page: 'home', sel: '#mechanics', title: 'Your team', mood: 'happy', text: 'Everyone who works at your workshop. Tap a mechanic to see their profile.' },
            edit('Press Edit to complete your own profile. Customers and your mechanics see it.'),
            photo,
            bye('Your workshop is in good hands.')
        ],
        admin: [
            Object.assign({}, hi, { text: 'As an admin you look after the whole platform. Let me show you where everything is. You can skip any time.' }),
            { page: 'home', sel: '.admin-hero', title: 'Control center', mood: 'happy', text: 'A quick look at what is happening across Getwheelz.' },
            { page: 'home', sel: '#all-customers', title: 'Customers', mood: 'working', text: 'Everyone who books services. You can open a profile or manage an account here.' },
            { page: 'home', sel: '#all-owners', title: 'Workshop owners', mood: 'working', text: 'Owners who list workshops on the platform.' },
            { page: 'home', sel: '#all-mechanics', title: 'Mechanics', mood: 'working', text: 'Mechanics and the workshops they work for.' },
            { page: 'home', sel: '#all-workshops', title: 'Workshops', mood: 'excited', text: 'Every workshop on the platform. Open one to look at its details.' },
            { page: 'home', sel: '#all-feedback', title: 'Feedback', mood: 'happy', text: 'Messages people send through the Contact page arrive here.' },
            { page: 'home', sel: function () { return document.querySelector('.sidebar-link[href="' + cfg.urls.adminServices + '"]'); }, title: 'Service catalog', mood: 'neutral', text: 'The master list of services that workshops choose from.' },
            { page: 'home', sel: function () { return document.querySelector('.sidebar-link[href="' + cfg.urls.adminSubadmins + '"]'); }, title: 'Sub-admins', mood: 'neutral', text: 'Create helpers who manage only customers, owners and workshops, or mechanics.' },
            { page: 'home', title: 'You\u2019re all set!', mood: 'excited', text: 'That is everything. If you ever want me again, press the ? button at the top of the page.' }
        ]
    };
    steps = ROLES[cfg.role] || [];
    if (!steps.length) return;

    // ---------- motion kit ----------
    // A tiny timeline helper on the Web Animations API (compositor-friendly, no dependency). `go` plays one
    // animation, `stagger` plays the same one across several elements with a delay between them. With
    // prefers-reduced-motion nothing animates: state changes are instant.
    var EASE = 'cubic-bezier(.19, 1, .22, 1)';
    function go(el, frames, o) {
        if (!el || reduce || !el.animate) return null;
        o = o || {};
        return el.animate(frames, { duration: o.d || 420, delay: o.delay || 0, easing: o.ease || EASE, fill: 'backwards' });
    }
    function stagger(els, frames, o) {
        o = o || {};
        els.forEach(function (el, n) { go(el, frames, { d: o.d, ease: o.ease, delay: (o.delay || 0) + n * (o.gap || 55) }); });
    }
    var RISE = [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }];

    // ---------- helpers ----------
    function load() {   // saved progress belongs to one person: ignore it after someone else logs in
        try { var s = JSON.parse(sessionStorage.getItem(KEY) || 'null'); return s && s.uid === cfg.uid ? s : null; } catch (e) { return null; }
    }
    function save(i) { try { sessionStorage.setItem(KEY, JSON.stringify({ on: 1, i: i, uid: cfg.uid })); } catch (e) {} }
    function clear() { try { sessionStorage.removeItem(KEY); } catch (e) {} }
    function samePath(url) { return new URL(url, location.href).pathname === location.pathname; }
    function onPage(key) { return samePath(cfg.urls[key]); }
    function find(sel) { return typeof sel === 'function' ? sel() : sel ? document.querySelector(sel) : null; }
    function visible(el) {
        if (!el || el.hidden || !el.getClientRects().length) return false;
        var r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.right > 0 && r.left < innerWidth;
    }

    // ---------- NEO's voice: "...." first, then the words are typed out ----------
    var typer = 0;
    var CHIP_MOOD = { wave: 'happy', happy: 'happy', excited: 'excited', working: 'working', neutral: 'neutral', strained: 'error' };
    function setMood(m) { var b = $('ntBot'); if (b) b.setAttribute('data-mood', CHIP_MOOD[m] || 'happy'); }
    function speak(text, first) {
        var body = $('ntBody'), out = $('ntText'), sr = $('ntSr');
        clearTimeout(typer);
        sr.textContent = text;                       // screen readers always get the whole sentence at once
        if (reduce) { body.classList.remove('is-thinking'); out.classList.remove('nt-caret'); out.textContent = text; return; }
        body.classList.add('is-thinking'); out.textContent = ''; out.classList.remove('nt-caret');
        var i = 0, step = Math.max(8, Math.min(22, 1100 / text.length));   // long texts type faster, so nobody waits
        typer = setTimeout(function () {
            body.classList.remove('is-thinking'); out.classList.add('nt-caret');
            (function tick() {
                i += 2; out.textContent = text.slice(0, i);
                if (i < text.length) typer = setTimeout(tick, step);
                else out.classList.remove('nt-caret');
            })();
        }, first ? 650 : 380);
    }

    // ---------- showing a step ----------
    function show(i, d) {
        dir = d || 1;
        if (i < 0) i = 0;
        if (i >= steps.length) return finish();
        var st = steps[i];
        if (!onPage(st.page)) { save(i); location.href = cfg.urls[st.page]; return; }
        if (st.before) st.before();
        var el = find(st.sel);
        if (st.sel && !visible(el)) return show(i + dir, dir);   // not on this page: skip the step
        var first = !opened;
        cur = i; save(i);
        var next = steps[i + 1];
        var title = $('ntTitle'), actions = card.querySelector('.nt-actions');

        title.textContent = st.title;
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        $('ntCount').textContent = pad(i + 1) + ' / ' + pad(steps.length);
        $('ntBarFill').style.transform = 'scaleX(' + ((i + 1) / steps.length) + ')';
        $('ntBar').setAttribute('aria-valuenow', String(i + 1));
        $('ntBar').setAttribute('aria-valuemax', String(steps.length));
        $('ntBack').disabled = i === 0;
        $('ntNext').textContent = !next ? 'Finish' : next.page !== st.page ? 'Continue to ' + PAGE_LABEL[next.page] : 'Next';
        $('ntSkip').hidden = !next;
        card.classList.toggle('is-welcome', !st.sel);
        if (window.GWRobot) { /* the tour uses the round NEO chip */ }
        setMood(st.mood);
        speak(st.text, first);

        spot.hidden = false; card.hidden = false; opened = true;
        var willScroll = scrollTo(el);
        spot.classList.toggle('nt-live', willScroll);
        place(el);

        if (first) {   // the one orchestrated moment: scrim, spotlight and card arrive together
            go(spot, [{ opacity: 0 }, { opacity: 1 }], { d: 600, ease: 'ease-out' });
            go(panel, [{ opacity: 0, transform: 'translateX(14px) scale(.97)' }, { opacity: 1, transform: 'none' }], { d: 700, delay: 140 });
            stagger([title, actions], RISE, { delay: 320, gap: 80, d: 520 });
            go($('ntBot'), [{ transform: 'scale(.55) rotate(-12deg)', opacity: 0 }, { transform: 'none', opacity: 1 }],
                { d: 700, delay: 200, ease: 'cubic-bezier(.34, 1.56, .64, 1)' });
        } else {       // moving between steps: the title slides, NEO hops, the text is typed again
            go(title, [{ opacity: 0, transform: 'translateX(' + (dir > 0 ? 12 : -12) + 'px)' }, { opacity: 1, transform: 'none' }], { d: 420 });
            go($('ntBot'), [{ transform: 'translateY(5px) scale(.94)' }, { transform: 'none' }], { d: 520, ease: 'cubic-bezier(.34, 1.56, .64, 1)' });
        }
        if (el) go(ring, [{ opacity: .85, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(1.07)' }], { d: 900, delay: first ? 500 : 180, ease: 'ease-out' });

        // the page may still be scrolling or loading: keep the spotlight on the element for a moment
        var until = performance.now() + 900;
        cancelAnimationFrame(raf);
        (function loop(now) {
            place(find(st.sel));
            if (now < until) raf = requestAnimationFrame(loop); else spot.classList.remove('nt-live');
        })(performance.now());
        $('ntNext').focus({ preventScroll: true });
    }

    function scrollTo(el) {   // returns true when the page has to scroll to bring the element into view
        if (!el) return false;
        var r = el.getBoundingClientRect(), small = innerWidth <= 640;
        var top = small ? r.top - 90 : r.top - (innerHeight - Math.min(r.height, innerHeight * .6)) / 2;
        if (r.top >= 80 && r.bottom <= innerHeight - (small ? 240 : 20)) return false;   // already comfortably in view
        window.scrollBy({ top: top, behavior: reduce ? 'auto' : 'smooth' });
        return true;
    }

    function setSpot(x, y, w, h) {
        spot.style.transform = 'translate3d(' + Math.round(x) + 'px,' + Math.round(y) + 'px,0)';
        spot.style.width = Math.round(w) + 'px'; spot.style.height = Math.round(h) + 'px';
    }

    function place(el) {
        var small = innerWidth <= 640;
        if (!visible(el)) {
            spot.classList.add('nt-none');
            setSpot(innerWidth / 2, innerHeight / 2, 0, 0);
            if (small) { card.style.transform = ''; return; }
            card.style.transform = 'translate3d(' + Math.round(Math.max(12, (innerWidth - card.offsetWidth) / 2)) + 'px,' +
                Math.round(Math.max(12, (innerHeight - card.offsetHeight) / 2)) + 'px,0)';
            return;
        }
        var r = el.getBoundingClientRect(), pad = 10;
        var top = Math.max(r.top - pad, 4), bottom = Math.min(r.bottom + pad, innerHeight - 4);
        var left = Math.max(r.left - pad, 4), right = Math.min(r.right + pad, innerWidth - 4);
        spot.classList.remove('nt-none');
        setSpot(left, top, Math.max(right - left, 0), Math.max(bottom - top, 0));
        if (small) { card.style.transform = ''; return; }   // on phones the card is docked at the bottom by CSS
        var cw = card.offsetWidth, ch = card.offsetHeight, gap = 18, x, y;
        if (bottom + gap + ch <= innerHeight) { y = bottom + gap; x = left; }
        else if (top - gap - ch >= 0) { y = top - gap - ch; x = left; }
        else if (right + gap + cw <= innerWidth) { x = right + gap; y = Math.max(12, top); }
        else if (left - gap - cw >= 0) { x = left - gap - cw; y = Math.max(12, top); }
        else { x = innerWidth - cw - 20; y = innerHeight - ch - 20; }
        x = Math.min(Math.max(12, x), innerWidth - cw - 12);
        y = Math.min(Math.max(12, y), innerHeight - ch - 12);
        card.style.transform = 'translate3d(' + Math.round(x) + 'px,' + Math.round(y) + 'px,0)';
    }

    // ---------- starting and stopping ----------
    function markDone() {
        try {
            fetch(cfg.doneUrl, { method: 'POST', headers: { 'X-CSRFToken': cfg.csrf }, credentials: 'same-origin' });
        } catch (e) {}
        cfg.pending = false;
    }
    function close() {
        cancelAnimationFrame(raf); clearTimeout(typer);
        var a = go(panel, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(10px) scale(.98)' }], { d: 240, ease: 'ease-in' });
        go(spot, [{ opacity: 1 }, { opacity: 0 }], { d: 240, ease: 'ease-in' });
        var done = function () { spot.hidden = true; card.hidden = true; };
        if (a) a.onfinish = done; else done();
        cur = -1; opened = false; clear();
    }
    function finish() { close(); if (cfg.pending) markDone(); }
    function skip() { close(); if (cfg.pending) markDone(); }

    function start() { show(0, 1); }
    function resume() { var s = load(); if (s && s.on) show(s.i, 1); else start(); }

    function boot() {
        spot = $('ntSpot'); card = $('ntCard'); bot = $('ntBot');
        if (!spot || !card) return;
        panel = card.querySelector('.nt-panel'); ring = spot.querySelector('.nt-ring');
        ready = true;
        $('ntNext').addEventListener('click', function () { show(cur + 1, 1); });
        $('ntBack').addEventListener('click', function () { show(cur - 1, -1); });
        $('ntSkip').addEventListener('click', skip);
        document.addEventListener('keydown', function (e) {
            if (card.hidden || cur < 0) return;
            if (e.key === 'Escape') skip();
            else if (e.key === 'ArrowRight') show(cur + 1, 1);
            else if (e.key === 'ArrowLeft') show(cur - 1, -1);
        });
        addEventListener('resize', function () { if (cur >= 0) place(find(steps[cur].sel)); });
        // while the person scrolls, the spotlight follows the page directly instead of easing behind it
        addEventListener('scroll', function () {
            if (cur < 0) return;
            spot.classList.add('nt-live');
            place(find(steps[cur].sel));
            clearTimeout(idle);
            idle = setTimeout(function () { spot.classList.remove('nt-live'); }, 140);
        }, { passive: true });
        // the owner opened the create-workshop pop-up: NEO's coach (neo-coach.js) takes over from the tour
        document.addEventListener('neo:coach-open', function () { if (cur >= 0) skip(); });
        var btn = $('tourBtn');
        if (btn) btn.addEventListener('click', function () { if (cur >= 0) return; resume(); });

        var s = load();
        // the tour moved here from another page. If the person wandered off to some other page the tour just
        // waits (the ? button picks it up again); it never drags them back.
        if (s && s.on) { if (steps[s.i] && onPage(steps[s.i].page)) show(s.i, 1); }
        else if (cfg.pending && onPage('home')) setTimeout(start, 700);
    }
    if (document.readyState === 'complete') boot(); else addEventListener('load', boot);
})();
