// GetWheelz robot: eye-tracking, idle looking around, click reactions and a tiny API.
//
//   GWRobot.setMood(el, 'working')          switch mood (neutral | happy | excited | working | strained)
//   GWRobot.flash(el, 'happy', 1600)        show a mood briefly, then return to the base mood
//   <form data-robot="#myRobot" data-robot-on-submit="working">   robot reacts when the form is sent
//
(function () {
    if (window.GWRobot) return;   // loaded twice (e.g. by the page and by base.html): run only once
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const MOODS = ['neutral', 'happy', 'excited', 'working', 'strained'];
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