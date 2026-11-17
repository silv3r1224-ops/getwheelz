// Shared toggle for "Report this account / workshop" inline panels.
// Used by workshops/person.html and workshops/selected.html. Every toggle
// button must carry aria-controls pointing at its panel's id, so multiple
// panels on one page work independently.
(function () {
    document.querySelectorAll('[data-report-toggle]').forEach(function (btn) {
        var panel = document.getElementById(btn.getAttribute('aria-controls'));
        if (!panel) return;

        function setOpen(open) {
            panel.style.display = open ? 'block' : 'none';
            btn.classList.toggle('is-active', open);
        }

        btn.addEventListener('click', function () {
            var open = panel.style.display !== 'none';
            setOpen(!open);
            if (!open) {
                var ta = panel.querySelector('textarea');
                if (ta) ta.focus();
            }
        });

        var cancel = panel.querySelector('[data-report-cancel]');
        if (cancel) cancel.addEventListener('click', function () {
            setOpen(false);
        });
    });
})();
