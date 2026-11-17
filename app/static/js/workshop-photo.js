// Workshop photos.
// 1. If an <img data-wp-photo> fails to load (missing file, broken path),
//    swap it for the container's store-icon placeholder instead of showing a
//    broken-image glyph. Delegated in the capture phase so it also covers
//    images added later by JS (e.g. nearby cards).
// 2. Any [data-wp-lightbox] trigger — banner photo button, home-card photo,
//    quick-view modal photo — opens a full-size lightbox with blur backdrop,
//    Esc/backdrop close and focus round-trip. The backdrop is created lazily
//    so one script works on every page without duplicated markup.
(() => {
    // ---------- broken-photo fallback ----------
    document.addEventListener(
        'error',
        (e) => {
            const img = e.target;
            if (!(img instanceof HTMLImageElement) || !img.hasAttribute('data-wp-photo')) return;

            const wrap = img.closest('.px-wcard-img, .lp-row-img, .px-banner-media, .px-banner, .wp-photo');
            if (!wrap) return;

            img.remove();

            if (wrap.classList.contains('wp-photo')) {
                const btn = wrap.querySelector('.wp-photo-open');
                if (btn) btn.hidden = true;
                const ico = wrap.querySelector('i[data-wp-ph-ico]');
                if (ico) ico.hidden = false;
                return;
            }

            if (wrap.classList.contains('px-banner-media') || wrap.classList.contains('px-banner')) {
                const btn = wrap.querySelector('.px-photo-open');
                if (btn) btn.remove();
                const ph = document.createElement('div');
                ph.className = 'px-ph';
                ph.innerHTML = "<i class='bx bx-store'></i>";
                wrap.appendChild(ph);
                return;
            }

            const cardBtn = wrap.querySelector('.px-card-photo-open');
            if (cardBtn) cardBtn.remove();

            const cls = wrap.classList.contains('lp-row-img') ? 'lp-ph' : 'px-ph';
            const ph = document.createElement('div');
            ph.className = cls;
            ph.innerHTML = "<i class='bx bx-store'></i>";
            wrap.appendChild(ph);
        },
        true
    );

    // ---------- shared lightbox ----------
    let backd = null;
    let stageImg = null;
    let closeBtn = null;
    let captionEl = null;
    let prevFocus = null;

    const ensureBackdrop = () => {
        if (backd) return backd;
        backd = document.getElementById('wlBackdrop');
        if (!backd) {
            backd = document.createElement('div');
            backd.id = 'wlBackdrop';
            backd.className = 'wl-backdrop';
            backd.hidden = true;
            backd.innerHTML =
                "<div class='wl-stage' role='dialog' aria-modal='true' aria-label='Workshop photo'>" +
                "<button type='button' class='wl-close' aria-label='Close photo' data-wl-close><i class='bx bx-x'></i></button>" +
                "<img id='wlImg' alt='' src=''>" +
                "<p class='wl-caption'><span class='wl-eyebrow'>Workshop</span><span class='wl-name'></span></p>" +
                "</div>";
            document.body.appendChild(backd);
        } else {
            const stage = backd.querySelector('.wl-stage');
            if (stage && !stage.querySelector('.wl-caption')) {
                const cap = document.createElement('p');
                cap.className = 'wl-caption';
                cap.innerHTML = "<span class='wl-eyebrow'>Workshop</span><span class='wl-name'></span>";
                stage.appendChild(cap);
            }
        }
        stageImg = backd.querySelector('#wlImg');
        closeBtn = backd.querySelector('.wl-close');
        captionEl = backd.querySelector('.wl-name');
        return backd;
    };

    const close = () => {
        if (!backd) return;
        backd.hidden = true;
        if (stageImg) stageImg.removeAttribute('src');
        if (captionEl) captionEl.textContent = '';
        if (prevFocus && prevFocus.focus) prevFocus.focus();
        prevFocus = null;
    };

    const openFrom = (trigger) => {
        const img = trigger.querySelector('img[data-wp-photo]');
        if (!img || !img.currentSrc) return;
        ensureBackdrop();
        prevFocus = document.activeElement;
        stageImg.src = img.currentSrc;
        if (captionEl) captionEl.textContent = img.alt || '';
        backd.hidden = false;
        if (closeBtn) closeBtn.focus();
    };

    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('[data-wp-lightbox]');
        if (trigger) {
            e.preventDefault();
            e.stopPropagation();
            openFrom(trigger);
            return;
        }
        if (backd && !backd.hidden) {
            if (e.target.closest('[data-wl-close]') || e.target === backd) close();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && backd && !backd.hidden) {
            close();
            return;
        }
        if ((e.key === 'Enter' || e.key === ' ') && e.target && e.target.matches('.px-card-photo-open')) {
            e.preventDefault();
            e.target.click();
        }
    });
})();
