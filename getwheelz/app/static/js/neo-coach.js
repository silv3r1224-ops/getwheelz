// NEO guides an owner while they create their workshop, then points them at the next step.
//  1. In the "Set up your workshop" pop-up NEO sits at the top and talks about the field the owner is on
//     (name, address, phone, map pin), cheers when the pin lands, and reacts if the form is not ready.
//  2. Once the workshop exists, a small card from NEO offers to add the first service.
// Only runs when the owner has no workshop yet (the form's data-mode is "create"); editing stays quiet.
// Needs: css/neo-coach.css, js/robot.js (GWRobot), js/workshop.js loaded before this file, and the
// #neoCoachTpl / #neoNextTpl / #neoCoachCfg elements in dashboard/owner.html.
(function () {
    'use strict';
    var modal = document.getElementById('createWorkshopModal');
    var form = document.getElementById('createWorkshopForm');
    var cfg = document.getElementById('neoCoachCfg');
    var FLAG = 'gw_neo_next_service';
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var $ = function (id) { return document.getElementById(id); };
    function setMood(el, m) { if (el && window.GWRobot) window.GWRobot.setMood(el, m); }
    function store(fn) { try { return fn(); } catch (e) { return null; } }

    // ---------- 1. coaching inside the create-workshop pop-up ----------
    var TIPS = {
        name: { mood: 'wave', title: 'Hi, I\u2019m NEO! Name it', text: 'What do customers call your workshop? Use the name on your signboard so they recognise you.' },
        address: { mood: 'working', title: 'Where are you?', text: 'Add the street, area and city. Customers see this on your workshop page.' },
        contact: { mood: 'happy', title: 'A number to call', text: 'Optional. Customers can reach you with questions before they book. You can also add it later.' },
        map: { mood: 'excited', title: 'Drop your pin', text: 'Click the map or drag the pin onto your workshop. If you are there right now, press \u201cUse my location\u201d. Customers nearby find you through this pin.' },
        pin: { mood: 'happy', title: 'Nice pin!', text: 'Zoom in and drag it if it sits a little off your workshop.' },
        ready: { mood: 'excited', title: 'That\u2019s everything!', text: 'Press \u201cCreate workshop\u201d below and your workshop goes live for customers.' },
        geoerror: { mood: 'neutral', title: 'Can\u2019t find you', text: 'No problem. Click the map to drop the pin where your workshop is.' },
        saving: { mood: 'working', title: 'Building it\u2026', text: 'Creating your workshop. One moment!' }
    };

    function initCoach() {
        var tpl = $('neoCoachTpl');
        var body = modal.querySelector('.fw-modal-body');
        if (!tpl || !body) return;
        var coach = tpl.content.firstElementChild.cloneNode(true);
        body.insertBefore(coach, body.firstChild);
        var bot = coach.querySelector('.rb');
        var title = coach.querySelector('[data-nc-title]');
        var text = coach.querySelector('[data-nc-text]');
        var fill = coach.querySelector('[data-nc-fill]');
        var count = coach.querySelector('[data-nc-count]');
        var hide = coach.querySelector('[data-nc-hide]');
        var name = $('cwName'), address = $('cwAddress'), lat = $('latitude'), lng = $('longitude'), status = $('location-status');
        var hadPin = false, wasReady = false, lastKey = '';

        function say(key) {
            var t = TIPS[key];
            if (!t) return;
            lastKey = key;
            title.textContent = t.title;
            text.textContent = t.text;
            setMood(bot, t.mood);
            coach.classList.remove('pop'); void coach.offsetWidth;
            if (!reduce) coach.classList.add('pop');
        }
        function missing() {
            var m = [];
            if (!name.value.trim()) m.push('the workshop name');
            if (!address.value.trim()) m.push('the address');
            if (!lat.value || !lng.value) m.push('the map pin');
            return m;
        }
        function refresh(announce) {
            var left = missing(), done = 3 - left.length;
            fill.style.width = Math.round(done / 3 * 100) + '%';
            count.textContent = done + ' of 3 done';
            var ready = left.length === 0;
            if (announce && ready && !wasReady) say('ready');
            wasReady = ready;
        }
        function onPin() {
            var has = !!(lat.value && lng.value);
            if (has && !hadPin) { hadPin = true; refresh(false); say(missing().length ? 'pin' : 'ready'); wasReady = !missing().length; return; }
            hadPin = has;
            refresh(true);
        }
        function reset() {
            hadPin = !!(lat.value && lng.value);
            wasReady = false;
            coach.hidden = false;
            refresh(false);
            say('name');
        }

        // which field is the owner on?
        modal.addEventListener('focusin', function (e) {
            var t = e.target;
            if (!t || !t.closest) return;
            if (t === name) say('name');
            else if (t === address) say('address');
            else if (t === $('cwContact')) say('contact');
            else if (t.closest('#cwMapWrap') || t.id === 'cwUseLocation') { if (lastKey !== 'map' && lastKey !== 'pin') say('map'); }
        });
        var wrap = $('cwMapWrap');
        if (wrap) wrap.addEventListener('pointerdown', function () { if (lastKey !== 'map' && lastKey !== 'pin' && lastKey !== 'ready') say('map'); });
        [name, address].forEach(function (el) { el.addEventListener('input', function () { refresh(true); }); });

        // the pin and its status text are written by workshop.js, so watch them
        if (status) new MutationObserver(function () {
            if (status.dataset.state === 'error') { say('geoerror'); return; }
            onPin();
        }).observe(status, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ['data-state'] });

        // submit: workshop.js has already validated by now (its listener was added first)
        form.addEventListener('submit', function (e) {
            if (e.defaultPrevented) {
                var m = missing();
                title.textContent = 'Almost there!';
                text.textContent = m.length ? 'I still need ' + m.join(', ').replace(/, ([^,]*)$/, ' and $1') + '. Check the red messages.' : 'Please check the red messages and try again.';
                setMood(bot, 'strained');
                coach.classList.remove('pop'); void coach.offsetWidth;
                if (!reduce) coach.classList.add('pop');
                lastKey = 'error';
            } else {
                say('saving');
                store(function () { sessionStorage.setItem(FLAG, '1'); });   // the next page shows the "add a service" card
            }
        });

        hide.addEventListener('click', function () { coach.hidden = true; });

        // opened / closed
        var wasOpen = false;
        new MutationObserver(function () {
            var open = modal.classList.contains('show');
            if (open && !wasOpen) {
                // an owner who opens this in the middle of the dashboard tour: let the coach take over
                document.dispatchEvent(new CustomEvent('neo:coach-open'));
                reset();
            }
            wasOpen = open;
        }).observe(modal, { attributes: true, attributeFilter: ['class'] });
        if (modal.classList.contains('show')) { wasOpen = true; reset(); }
    }

    // ---------- 2. "add your first service" once the workshop exists ----------
    function showNext() {
        var tpl = $('neoNextTpl');
        if (!tpl) return;
        var tourCard = $('ntCard');
        if (tourCard && !tourCard.hidden) return;                // the dashboard tour is talking: stay quiet
        var card = tpl.content.firstElementChild.cloneNode(true);
        document.body.appendChild(card);
        setMood(card.querySelector('.rb'), 'excited');
        if (!reduce) card.classList.add('pop');
        var go = card.querySelector('[data-nc-go]');
        function close() {
            card.remove();
            document.removeEventListener('keydown', onKey);
        }
        function onKey(e) { if (e.key === 'Escape') close(); }
        document.addEventListener('keydown', onKey);
        card.querySelector('[data-nc-later]').addEventListener('click', close);
        go.addEventListener('click', function () {
            close();
            var opener = document.querySelector('[data-open-add-service]');
            if (opener) opener.click();
            else { var s = $('services'); if (s) s.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' }); }
        });
        go.focus({ preventScroll: true });
    }

    function boot() {
        if (modal && form && form.dataset.mode === 'create') initCoach();
        var pending = store(function () { return sessionStorage.getItem(FLAG); });
        if (pending) {
            store(function () { sessionStorage.removeItem(FLAG); });
            // only if the workshop really got created (the server may have refused the form)
            if (cfg && cfg.dataset.hasWorkshop === 'true') setTimeout(showNext, 1000);
        }
    }
    if (document.readyState === 'complete') boot(); else addEventListener('load', boot);
})();