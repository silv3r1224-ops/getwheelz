/* ==================================================================
   owner_service_popups.js — extracted from app/templates/dashboard/owner.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    // Add / edit service pop-ups: blur the dashboard behind them (same look as the login pop-up)
    // and close on a click outside the card or Esc.
    (function () {
        var layout = document.getElementById('adminLayout');
        var modals = ['addServiceModal', 'editServiceModal']
            .map(function (id) { return document.getElementById(id); })
            .filter(Boolean);
        if (!layout || !modals.length) return;

        var openedAt = 0;
        var pressStartedInside = false;
        function anyOpen() {
            return modals.some(function (m) { return m.classList.contains('show'); });
        }
        function close() {
            modals.forEach(function (m) { m.classList.remove('show'); });
        }

        // Whoever opens or closes a pop-up, the blur follows its "show" class.
        var observer = new MutationObserver(function () {
            var open = anyOpen();
            if (open && !layout.classList.contains('pop')) openedAt = Date.now();
            layout.classList.toggle('pop', open);
        });
        modals.forEach(function (m) { observer.observe(m, { attributes: true, attributeFilter: ['class'] }); });

        document.addEventListener('pointerdown', function (e) {
            pressStartedInside = modals.some(function (m) { return m.contains(e.target); });
        });
        // every "Add Service" / "+ New Service" button opens the same pop-up
        var addModal = document.getElementById('addServiceModal');
        document.addEventListener('click', function (e) {
            var opener = e.target.closest && e.target.closest('[data-open-add-service]');
            if (opener && addModal) {
                openedAt = Date.now();
                addModal.classList.add('show');
                layout.classList.add('pop');
                var first = addModal.querySelector('.gw-select-btn, select');
                if (first && first.focus) first.focus({ preventScroll: true });
            }
        });
        document.addEventListener('click', function (e) {
            if (!anyOpen() || pressStartedInside) return;
            if (modals.some(function (m) { return m.contains(e.target); })) return;
            // the click that opened the pop-up is still bubbling up: don't close it straight away
            if (Date.now() - openedAt < 300) return;
            close();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') close();
        });
    })();

    // Styled dropdown for the "Add a Service" pop-up. The real <select> stays in the form (hidden),
    // so submitting works as before; this just draws a nicer list on top of it.
    (function () {
        var select = document.querySelector('#addServiceModal select[name="sc_id"]');
        if (!select) return;
        var form = select.form;
        var placeholder = select.options[0] ? select.options[0].textContent : 'Select a service';

        var wrap = document.createElement('div');
        wrap.className = 'gw-select';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'gw-select-btn';
        btn.setAttribute('aria-haspopup', 'listbox');
        btn.setAttribute('aria-expanded', 'false');
        var valueEl = document.createElement('span');
        valueEl.className = 'gw-select-value placeholder';
        valueEl.textContent = placeholder;
        var chevron = document.createElement('i');
        chevron.className = 'bx bx-chevron-down';
        btn.appendChild(valueEl);
        btn.appendChild(chevron);
        var list = document.createElement('ul');
        list.className = 'gw-select-list';
        list.setAttribute('role', 'listbox');
        list.hidden = true;

        function icon(name) {
            var s = document.createElement('span');
            s.className = 'ico';
            var i = document.createElement('i');
            i.className = 'bx ' + name;
            s.appendChild(i);
            return s;
        }

        var items = [];
        var addedHeader = false;
        var lastGroup = null; // a workshop serving cars and two-wheelers groups its catalog entries by type
        var groupHeaders = {};
        Array.prototype.forEach.call(select.options, function (o) {
            if (o.value === '') return;
            var label = o.getAttribute('data-label') || o.textContent;
            var group = o.getAttribute('data-group');
            if (group && !o.disabled && group !== lastGroup) {
                lastGroup = group;
                var gh = document.createElement('li');
                gh.className = 'gw-group';
                gh.setAttribute('role', 'presentation');
                gh.textContent = group;
                list.appendChild(gh);
                groupHeaders[group] = gh;
            }
            if (o.disabled && !addedHeader) {
                addedHeader = true;
                var h = document.createElement('li');
                h.className = 'gw-group';
                h.setAttribute('role', 'presentation');
                h.textContent = 'Already added';
                list.appendChild(h);
            }
            var li = document.createElement('li');
            li.className = 'gw-opt' + (o.disabled ? ' is-added' : '');
            li.setAttribute('role', 'option');
            li.setAttribute('aria-selected', 'false');
            if (o.disabled) {
                li.setAttribute('aria-disabled', 'true');
                li.title = 'You already offer this service';
            }
            li.appendChild(icon(o.disabled ? 'bx-check-circle' : 'bx-wrench'));
            var text = document.createElement('span');
            text.textContent = label;
            li.appendChild(text);
            if (o.disabled) {
                var pill = document.createElement('span');
                pill.className = 'gw-pill';
                pill.textContent = 'Added';
                li.appendChild(pill);
            } else {
                var tick = document.createElement('i');
                tick.className = 'bx bx-check tick';
                tick.hidden = true;
                li.appendChild(tick);
            }
            list.appendChild(li);
            items.push({ value: o.value, label: label, disabled: o.disabled, group: group || null, el: li });
        });

        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(btn);
        wrap.appendChild(list);
        wrap.appendChild(select);
        select.classList.add('gw-native');
        select.tabIndex = -1;
        select.setAttribute('aria-hidden', 'true');

        var enabled = items.filter(function (it) { return !it.disabled; });
        if (!enabled.length) btn.disabled = true;

        // ---- vehicle-type toggles filter the catalog (Cars / Two-wheelers) ----
        var optByValue = {};
        items.forEach(function (it) { optByValue[it.value] = it; });
        var currentGroup = null;

        function visible(it) {
            return !currentGroup || it.group === currentGroup;
        }
        function syncVisibility() {
            items.forEach(function (it) {
                var show = visible(it);
                it.el.hidden = !show;
                if (show) it.el.removeAttribute('aria-hidden');
                else it.el.setAttribute('aria-hidden', 'true');
                var opt = optByValue[it.value];
                if (opt) opt.hidden = !show;
            });
            Object.keys(groupHeaders).forEach(function (g) {
                var hasVisible = items.some(function (it) { return it.group === g && visible(it) && !it.disabled; });
                groupHeaders[g].hidden = !hasVisible;
            });
            // if the chosen service belongs to a hidden group, clear the selection
            if (select.value) {
                var selIt = optByValue[select.value];
                if (selIt && !visible(selIt)) {
                    select.value = '';
                    valueEl.textContent = placeholder;
                    valueEl.classList.add('placeholder');
                    btn.classList.remove('is-invalid');
                }
            }
            setActive(-1);
        }
        function setGroup(group) {
            // a workshop that doesn't offer the type has no options in that group
            if (group && !items.some(function (it) { return it.group === group; })) return;
            currentGroup = (currentGroup === group) ? null : group;
            toggles.forEach(function (b) {
                var on = b.dataset.vtype === currentGroup;
                b.classList.toggle('on', on);
                b.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
            syncVisibility();
            close();
        }
        var toggles = document.querySelectorAll('#addServiceModal .gwv-toggle');
        toggles.forEach(function (b) {
            b.addEventListener('click', function () { if (!b.disabled) setGroup(b.dataset.vtype); });
        });

        var active = -1;
        function setActive(i) {
            active = i;
            items.forEach(function (it, n) { it.el.classList.toggle('is-active', n === i); });
            if (i >= 0 && !items[i].el.hidden && items[i].el.scrollIntoView) {
                items[i].el.scrollIntoView({ block: 'nearest' });
            }
        }
        function isOpen() { return !list.hidden; }
        function open() {
            if (btn.disabled) return;
            list.hidden = false;
            wrap.classList.add('open');
            btn.setAttribute('aria-expanded', 'true');
            var sel = items.findIndex(function (it) { return it.value === select.value && visible(it); });
            setActive(sel >= 0 ? sel : items.findIndex(function (it) { return !it.disabled && visible(it); }));
        }
        function close() {
            list.hidden = true;
            wrap.classList.remove('open');
            btn.setAttribute('aria-expanded', 'false');
            setActive(-1);
        }
        function choose(it) {
            if (it.disabled || it.el.hidden) return;
            select.value = it.value;
            valueEl.textContent = it.label;
            valueEl.classList.remove('placeholder');
            btn.classList.remove('is-invalid');
            items.forEach(function (x) {
                var on = x === it;
                x.el.setAttribute('aria-selected', on ? 'true' : 'false');
                x.el.classList.toggle('is-selected', on);
                var tick = x.el.querySelector('.tick');
                if (tick) tick.hidden = !on;
            });
            close();
            btn.focus();
        }
        function move(step) {
            var n = active;
            do { n += step; } while (n >= 0 && n < items.length && (items[n].disabled || items[n].el.hidden));
            if (n >= 0 && n < items.length) setActive(n);
        }

        btn.addEventListener('click', function () { isOpen() ? close() : open(); });
        btn.addEventListener('keydown', function (e) {
            if (!isOpen()) {
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); open(); }
                return;
            }
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }   // closes the list, not the pop-up
            else if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
            else if (e.key === 'Home') { e.preventDefault(); setActive(items.findIndex(function (it) { return !it.disabled && visible(it); })); }
            else if (e.key === 'End') {
                e.preventDefault();
                for (var n = items.length - 1; n >= 0; n--) { if (!items[n].disabled && visible(items[n])) { setActive(n); break; } }
            }
            else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (active >= 0) choose(items[active]); }
            else if (e.key === 'Tab') close();
        });
        items.forEach(function (it, n) {
            it.el.addEventListener('mousedown', function (e) { e.preventDefault(); });   // keep focus on the button
            it.el.addEventListener('mouseenter', function () { if (!it.disabled) setActive(n); });
            it.el.addEventListener('click', function () { choose(it); });
        });
        document.addEventListener('click', function (e) { if (isOpen() && !wrap.contains(e.target)) close(); });

        // the real <select> is hidden, so when nothing is chosen show our own prompt instead of the browser's
        select.addEventListener('invalid', function (e) {
            e.preventDefault();
            btn.classList.add('is-invalid');
            open();
        });
    })();

    // Edit-service modal
    (function () {
        var modal = document.getElementById('editServiceModal');
        if (!modal) return;
        var form = document.getElementById('editServiceForm');
        var pressStartedInside = false;
        document.addEventListener('pointerdown', function (e) {
            pressStartedInside = modal.contains(e.target);
        });
        document.addEventListener('click', function (e) {
            var trigger = e.target.closest('[data-edit-url]');
            if (trigger) {
                form.action = trigger.dataset.editUrl;
                document.getElementById('editServiceName').textContent = trigger.dataset.name;
                document.getElementById('editServicePrice').value = trigger.dataset.price;
                document.getElementById('editServiceDuration').value = trigger.dataset.duration;
                modal.classList.add('show');
                document.getElementById('editServicePrice').focus();
                return;
            }
            // Click outside the card closes it (the modal IS the card, there is no backdrop element).
            // Ignore it if the press started inside the card, e.g. dragging to select text in an input.
            if (modal.classList.contains('show') && !modal.contains(e.target) && !pressStartedInside) {
                modal.classList.remove('show');
            }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') modal.classList.remove('show');
        });
    })();

    // Remove-service confirmation dialog
    (function () {
        var dialog = document.getElementById('confirmDialog');
        if (!dialog) return;
        var form = document.getElementById('confirmForm');
        var nameEl = document.getElementById('confirmName');
        function close() { dialog.classList.remove('show'); }
        document.addEventListener('click', function (e) {
            var trigger = e.target.closest('[data-remove-url]');
            if (trigger) {
                e.preventDefault();
                form.action = trigger.dataset.removeUrl;
                nameEl.textContent = trigger.dataset.name;
                dialog.classList.add('show');
                dialog.querySelector('[data-cancel]').focus();
                return;
            }
            // Cancel button, or a click on the dark backdrop
            if (e.target === dialog || e.target.closest('[data-cancel]')) close();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') close();
        });
    })();

    // Delete-workshop confirmation dialog
    (function () {
        const dialog = document.getElementById('deleteWorkshopDialog');
        const openButton = document.querySelector('[data-open-delete-workshop]');
        if (!dialog || !openButton) return;

        const cancelButton = dialog.querySelector('[data-cancel-delete-workshop]');
        function openDialog() {
            dialog.classList.add('show');
            if (cancelButton) cancelButton.focus();
        }

        function closeDialog() {
            dialog.classList.remove('show');
            openButton.focus();
        }

        openButton.addEventListener('click', openDialog);
        if (cancelButton) cancelButton.addEventListener('click', closeDialog);
        dialog.addEventListener('click', function (event) {
            if (event.target === dialog) closeDialog();
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && dialog.classList.contains('show')) closeDialog();
        });
    })();
