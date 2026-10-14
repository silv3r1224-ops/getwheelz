//=====================================================================Customer home: recommended carousel + nearby list==============================

(function () {

    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c =>

        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));



    // ---------- Recommended: auto-slide one workshop at a time ----------

    const track = document.getElementById('rec-track');

    const prevBtn = document.getElementById('rec-prev');

    const nextBtn = document.getElementById('rec-next');

    const dot = document.getElementById('rec-status-dot');

    const dotText = document.getElementById('rec-status-text');

    const cards = track ? track.querySelectorAll('.carousel-card') : [];



    if (track && prevBtn && nextBtn) {

        if (cards.length < 2) {

            prevBtn.style.display = nextBtn.style.display = 'none';

        } else {

            const INTERVAL = 4000;

            const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

            let timer = null;



            const step = () => {

                const gap = parseInt(getComputedStyle(track).columnGap) || 20;

                return cards[0].offsetWidth + gap;

            };

            const atEnd = () => track.scrollLeft + track.clientWidth >= track.scrollWidth - 5;



            const next = () => atEnd()

                ? track.scrollTo({ left: 0, behavior: 'smooth' })

                : track.scrollBy({ left: step(), behavior: 'smooth' });

            const prev = () => track.scrollLeft <= 5

                ? track.scrollTo({ left: track.scrollWidth, behavior: 'smooth' })

                : track.scrollBy({ left: -step(), behavior: 'smooth' });



            const setStatus = (running) => {

                if (dot) dot.classList.toggle('paused', !running);

                if (dotText) dotText.textContent = running ? 'Auto-sliding' : 'Paused';

            };

            const stop = () => { clearInterval(timer); timer = null; setStatus(false); };

            const start = () => {

                if (reduceMotion || document.hidden) return;

                clearInterval(timer);

                timer = setInterval(next, INTERVAL);

                setStatus(true);

            };



            nextBtn.addEventListener('click', () => { next(); start(); });

            prevBtn.addEventListener('click', () => { prev(); start(); });



            track.addEventListener('mouseenter', stop);

            track.addEventListener('mouseleave', start);

            track.addEventListener('touchstart', stop, { passive: true });

            track.addEventListener('touchend', start);

            document.addEventListener('visibilitychange', () => document.hidden ? stop() : start());



            start();

        }

    }



    // ---------- Nearby workshops list ----------

    const section = document.getElementById('nearby-section');

    const list = document.getElementById('nearby-list');



    if (section && list && navigator.geolocation) {

        const profileUrl = section.dataset.profileUrl || '/workshops/0';

        const staticUrl = section.dataset.staticUrl || '/static/';



        navigator.geolocation.getCurrentPosition(async (pos) => {

            try {

                const { latitude, longitude } = pos.coords;

                const res = await fetch(`${section.dataset.url || '/workshops/nearby'}?lat=${latitude}&lng=${longitude}`);

                if (!res.ok) throw new Error('Bad response');

                const data = await res.json();

                if (!data.length) return;



                section.style.display = 'block';

                list.innerHTML = data.map(w => `

                    <a href="${profileUrl.replace(/0$/, w.w_id)}" class="nearby-card">

                        <div class="nearby-card-img">

                            ${w.photo_url

                        ? `<img src="${staticUrl}${esc(w.photo_url)}" alt="${esc(w.name)}">`

                        : `<div class="carousel-card-img-placeholder" style="font-size:2rem;"><i class='bx bx-store'></i></div>`}

                        </div>

                        <div class="nearby-card-body">

                            <div class="nearby-card-distance">${esc(w.distance_km)} km away</div>

                            <h3>${esc(w.name)}</h3>

                            <p class="nearby-card-address"><i class='bx bx-map'></i> ${esc(w.address || 'Nearby')}</p>

                        </div>

                    </a>`).join('');

            } catch (e) {

                console.error('Could not load nearby workshops:', e);

            }

        }, () => { /* permission denied: section stays hidden */ }, { timeout: 10000 });

    }

})();
