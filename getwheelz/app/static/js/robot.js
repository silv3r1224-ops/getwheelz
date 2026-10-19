// NEO, the GetWheelz robot: eye-tracking, idle looking around, 3D roaming, click reactions and a tiny API.
//
//   GWRobot.setMood(el, 'working')          switch mood (neutral | happy | excited | wave | working | screwing | strained)
//   GWRobot.flash(el, 'happy', 1600)        show a mood briefly, then return to the base mood
//   <form data-robot="#myRobot" data-robot-on-submit="working">   robot reacts when the form is sent
//
(function () {
    if (window.GWRobot) return;   // loaded twice (e.g. by the page and by base.html): run only once
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const MOODS = ['neutral', 'happy', 'excited', 'wave', 'working', 'screwing', 'strained'];
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    let lastMove = 0;

    const all = () => Array.from(document.querySelectorAll('.rb'));

    function setMood(el, mood) {
        if (!el || MOODS.indexOf(mood) === -1) return;
        el.dataset.mood = mood;
    }

    function flash(el, mood, ms) {
        if (!el) return;
        clearTimeout(el._rbTimer);
        setMood(el, mood);
        el._rbTimer = setTimeout(() => setMood(el, el.dataset.baseMood || 'neutral'), ms || 1600);
    }

    function boop(el) {
        if (!reduce) {
            el.classList.remove('is-boop');
            void el.getBoundingClientRect();           // restart the animation
            el.classList.add('is-boop');
            setTimeout(() => el.classList.remove('is-boop'), 650);
        }
        flash(el, 'happy', 1500);
    }

    function look(el, nx, ny) {
        el.style.setProperty('--lx', (clamp(nx, -1, 1) * 7).toFixed(2));
        el.style.setProperty('--ly', (clamp(ny, -1, 1) * 5).toFixed(2));
    }

    function init() {
        all().forEach((el) => {
            if (el.dataset.rbReady) return;
            el.dataset.rbReady = '1';
            if (!el.dataset.baseMood) el.dataset.baseMood = el.dataset.mood || 'neutral';
            el.addEventListener('click', () => boop(el));
        });
    }

    // eyes follow the pointer
    if (!reduce) {
        document.addEventListener('pointermove', (e) => {
            lastMove = Date.now();
            all().forEach((el) => {
                if (!el.hasAttribute('data-follow')) return;
                const r = el.getBoundingClientRect();
                look(el, (e.clientX - (r.left + r.width / 2)) / 320, (e.clientY - (r.top + r.height / 2)) / 320);
            });
        }, { passive: true });

        // when nobody is moving the pointer (or on touch screens) glance around now and then
        setInterval(() => {
            if (Date.now() - lastMove < 3500) return;
            all().forEach((el) => {
                if (!el.hasAttribute('data-follow')) return;
                look(el, (Math.random() * 2 - 1) * 0.9, (Math.random() * 2 - 1) * 0.6);
            });
        }, 2600);
    }

    // forms that make the robot react
    document.addEventListener('submit', (e) => {
        const form = e.target;
        if (!form.matches || !form.matches('[data-robot-on-submit]')) return;
        const target = document.querySelector(form.getAttribute('data-robot'));
        setMood(target, form.getAttribute('data-robot-on-submit'));
    });

    // ---------- roam: NEO floats around in 3D space ----------
    // Elements with data-roam get a smooth, endlessly varying path made from a few slow sine waves:
    //   x / y     drift around (in % of NEO's own size, so it scales with it)
    //   scale     moves closer to / farther from you
    //   rotateY/X turns and nods toward the direction of travel (needs perspective, added below)
    //   rotateZ   leans into the turns like a little drone
    // The face slides toward where NEO is heading, and every few seconds it glances straight at you.
    (function roam() {
        if (reduce || !('IntersectionObserver' in window)) return;
        const live = new Set();            // roaming robots currently on screen
        let raf = 0;

        function frame(now) {
            const t = now / 1000;
            live.forEach((el) => {
                const w = t + (parseFloat(el.dataset.roamPhase) || 0);
                const x = 70 * Math.sin(0.31 * w) + 34 * Math.sin(0.57 * w + 1.3);
                const y = 38 + 36 * Math.sin(0.43 * w + 0.6) + 20 * Math.sin(0.71 * w + 2.1);
                const vx = 70 * 0.31 * Math.cos(0.31 * w) + 34 * 0.57 * Math.cos(0.57 * w + 1.3);
                const vy = 36 * 0.43 * Math.cos(0.43 * w + 0.6) + 20 * 0.71 * Math.cos(0.71 * w + 2.1);
                const s = 1 + 0.15 * Math.sin(0.37 * w + 2.2);
                const yaw = clamp(vx * 0.8, -34, 34);
                const pitch = clamp(vy * 0.22, -7, 7);
                const roll = clamp(vx * 0.14, -8, 8) + 2 * Math.sin(1.3 * w);

                // every ~9 s NEO turns its eyes to look right at you for a moment
                const c = w % 9;
                const glance = c > 6.2 && c < 7.8 ? Math.sin(((c - 6.2) / 1.6) * Math.PI) : 0;
                const lead = 1 - glance;

                el.style.transform =
                    'translate(' + x.toFixed(2) + '%, ' + y.toFixed(2) + '%) scale(' + s.toFixed(3) + ') ' +
                    'perspective(800px) rotateY(' + yaw.toFixed(2) + 'deg) rotateX(' + (-pitch).toFixed(2) + 'deg) ' +
                    'rotateZ(' + roll.toFixed(2) + 'deg)';
                el.style.setProperty('--lx', ((yaw / 34) * 9 * lead).toFixed(2));
                el.style.setProperty('--ly', ((pitch / 7) * 5 * lead + 1.2 * Math.sin(2.1 * w)).toFixed(2));
            });
            raf = live.size ? requestAnimationFrame(frame) : 0;
        }

        const io = new IntersectionObserver((entries) => {
            entries.forEach((e) => (e.isIntersecting ? live.add(e.target) : live.delete(e.target)));
            if (live.size && !raf) raf = requestAnimationFrame(frame);
        });
        const watch = () => document.querySelectorAll('.rb[data-roam]').forEach((el) => {
            if (el.dataset.roamReady) return;
            el.dataset.roamReady = '1';
            io.observe(el);
        });
        watch();
        document.addEventListener('DOMContentLoaded', watch);
    })();

    // ---------- login / sign-up pop-ups: an excited robot appears next to the form ----------
    // base.html adds <div id="authRobot"> for signed-out visitors. We watch the two pop-ups, and when one
    // opens we stand the robot beside it (or perch it on the top edge when the screen is narrow).
    (function authRobot() {
        const wrap = document.getElementById('authRobot');
        if (!wrap) return;
        const svg = wrap.querySelector('.rb');
        const modals = ['loginModal', 'signUpModal'].map((id) => document.getElementById(id)).filter(Boolean);
        if (!svg || !modals.length) return;
        let current = null;

        const openModal = () => modals.find((m) => m.classList.contains('show')) || null;

        function place(m) {
            const r = m.getBoundingClientRect();
            const w = wrap.offsetWidth;
            const h = wrap.offsetHeight;
            let left, top, fx, fy, lx, ly;
            if (r.left >= w + 18) {                        // room on the left: stand beside the form
                left = r.left - w - 12;
                top = Math.max(12, r.top + Math.min(40, r.height * 0.12));
                fx = '50px'; fy = '10px'; lx = 1; ly = 0.25;
            } else if (r.top >= h * 0.72) {                // otherwise perch on the top edge, looking down
                left = clamp(r.left + r.width / 2 - w / 2, 8, window.innerWidth - w - 8);
                top = Math.max(6, r.top - h + 22);
                fx = '0px'; fy = '40px'; lx = 0; ly = 1;
            } else {
                return false;                              // no room: stay hidden
            }
            wrap.style.left = left + 'px';
            wrap.style.top = top + 'px';
            wrap.style.setProperty('--fx', fx);
            wrap.style.setProperty('--fy', fy);
            look(svg, lx, ly);                             // glance toward the form
            return true;
        }

        function sync() {
            const m = openModal();
            if (!m || !place(m)) {
                wrap.classList.remove('is-in');
                current = m ? m.id : null;
                return;
            }
            setMood(svg, 'excited');
            if (current !== m.id || !wrap.classList.contains('is-in')) {
                wrap.classList.remove('is-in');
                void wrap.offsetWidth;                     // restart the pop-in
                wrap.classList.add('is-in');
            }
            current = m.id;
        }

        const observer = new MutationObserver(sync);
        modals.forEach((m) => observer.observe(m, { attributes: true, attributeFilter: ['class'] }));
        window.addEventListener('resize', () => { if (openModal()) sync(); });

        // clicking the robot boops it; it must not count as a click outside the form (which would close the pop-up)
        wrap.addEventListener('click', (e) => e.stopPropagation());

        // eyes follow whichever field is being filled in
        document.addEventListener('focusin', (e) => {
            if (!wrap.classList.contains('is-in')) return;
            const t = e.target;
            if (!(t instanceof Element) || !t.closest('#loginModal, #signUpModal')) return;
            const a = svg.getBoundingClientRect();
            const b = t.getBoundingClientRect();
            look(svg, (b.left + b.width / 2 - (a.left + a.width / 2)) / 220, (b.top + b.height / 2 - (a.top + a.height / 2)) / 200);
        });
    })();

    window.GWRobot = { init, setMood, flash, boop };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();