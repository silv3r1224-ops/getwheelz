/* Cinematic scroll choreography for the public landing page and the customer
   home (which shares the same reveal language). No dependencies. */
(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const page = document.querySelector('.lp, .px-customer-home, .px-customer-booking, .px-customer-page');
    if (!page || reduce) return;

    document.documentElement.classList.add('premium-motion');
    const reveal = [...page.querySelectorAll('.reveal')];
    reveal.forEach((el, i) => {
        el.style.setProperty('--reveal-delay', `${Math.min(i * 55, 220)}ms`);
        el.classList.add('premium-reveal');
        // Break each section into a few stable visual pieces so it assembles
        // like a designed puzzle instead of simply fading in as one block.
        const pieces = el.querySelector(':scope > .lp-wrap')?.children || el.children;
        [...pieces].forEach((piece, index) => {
            piece.classList.add('puzzle-piece');
            piece.style.setProperty('--piece-index', index);
            piece.style.setProperty('--piece-x', `${index % 2 ? 18 : -18}px`);
            piece.style.setProperty('--piece-y', `${index % 3 === 0 ? 22 : index % 3 === 1 ? -16 : 12}px`);
            piece.style.setProperty('--piece-rotate', `${index % 2 ? 1.3 : -1.1}deg`);
        });
    });

    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver((entries, obs) => {
            entries.forEach(entry => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('premium-in');
                obs.unobserve(entry.target);
            });
        }, { threshold: .08, rootMargin: '0px 0px -12% 0px' });
        reveal.forEach(el => observer.observe(el));
    } else reveal.forEach(el => el.classList.add('premium-in'));

    page.querySelectorAll('a[href^="#"]').forEach(link => {
        link.addEventListener('click', event => {
            const target = document.querySelector(link.getAttribute('href'));
            if (!target) return;
            event.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });
})();
