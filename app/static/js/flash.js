// NEO's flash messages: one place for the server-rendered messages (base.html) and for GW.neoToast(...).
// Each message leaves by itself (a cyan line along its bottom edge shows the time left), waits while the
// pointer or keyboard focus is on it, and can be closed with the x. Timing lives here, in JS, so it also
// works when the browser or the performance mode switches CSS animation off.
(function () {
    'use strict';
    if (window.GW && window.GW.flash) return;
    var MS = { success: 4500, error: 7000 };
    var MAX = 4;

    function mount(item) {
        if (!item || item._gw) return;
        item._gw = true;
        var ok = item.getAttribute('data-cat') === 'success';
        var ms = ok ? MS.success : MS.error, left = ms, started = 0, timer = 0;
        item.style.setProperty('--flash-ms', ms + 'ms');
        function leave() {
            clearTimeout(timer);
            item.classList.add('is-leaving');
            setTimeout(function () { item.remove(); }, 300);
        }
        function run() { started = Date.now(); clearTimeout(timer); timer = setTimeout(leave, left); item.classList.remove('is-paused'); }
        function pause() { if (!started) return; left = Math.max(800, left - (Date.now() - started)); started = 0; clearTimeout(timer); item.classList.add('is-paused'); }
        item.addEventListener('mouseenter', pause);
        item.addEventListener('mouseleave', run);
        item.addEventListener('focusin', pause);
        item.addEventListener('focusout', run);
        var x = item.querySelector('.flash-close');
        if (x) x.addEventListener('click', leave);
        item.addEventListener('keydown', function (e) { if (e.key === 'Escape') leave(); });
        run();
    }

    function init() {
        document.querySelectorAll('.flash-item').forEach(mount);
        // messages queued by a form that moved the person to another page (see live.js)
        try {
            var raw = sessionStorage.getItem('gw:flash');
            if (raw) {
                sessionStorage.removeItem('gw:flash');
                JSON.parse(raw).slice(0, MAX).forEach(function (m) { toast(m.text, m.cat); });
            }
        } catch (e) { /* storage blocked */ }
    }

    // GW.neoToast("text", "error" | "success"): the same message look, made from the <template id="neoToastTpl">
    function toast(message, category) {
        var tpl = document.getElementById('neoToastTpl');
        if (!tpl) return;
        var ok = category === 'success';
        var box = document.querySelector('[data-neo-toast]');
        if (!box) {
            box = tpl.content.firstElementChild.cloneNode(true);
            box.querySelectorAll('.flash-item').forEach(function (r) { r.remove(); });   // the template's sample row is only a model
            document.body.appendChild(box);
        }
        var rows = box.querySelectorAll('.flash-item');
        for (var i = 0; i <= rows.length - MAX; i++) rows[i].remove();
        var row = tpl.content.querySelector('.flash-item').cloneNode(true);
        row.setAttribute('data-cat', ok ? 'success' : 'error');
        row.setAttribute('role', ok ? 'status' : 'alert');
        var bubble = row.querySelector('.flash-message');
        bubble.classList.toggle('flash-success', ok);
        bubble.classList.toggle('flash-error', !ok);
        var icon = bubble.querySelector('.flash-ico');
        if (icon) icon.className = 'bx ' + (ok ? 'bx-check-circle' : 'bx-error-circle') + ' flash-ico';
        var chip = row.querySelector('.nc');
        if (chip) chip.setAttribute('data-mood', ok ? 'happy' : 'error');
        bubble.querySelector('span').textContent = String(message);   // text only: never HTML
        box.appendChild(row);
        mount(row);
    }

    window.GW = window.GW || {};
    window.GW.flash = { mount: mount };
    window.GW.neoToast = toast;
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
