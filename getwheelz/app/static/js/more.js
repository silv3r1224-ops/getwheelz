// "More..." for long lists, used everywhere the service catalog can grow big.
//   <div class="px-chips" data-more="8"> ... </div>   show 8 items, the rest sit behind a "More..." button
// Optional attributes on the container:
//   data-more-items="<selector>"   which children count as items (default: direct children; a table's body rows)
//   data-more-label="services"     makes the button read "More services..." instead of "More..."
// Optional attribute on a child:
//   data-more-skip                 never hidden, not counted (a "Browse by service:" label, an "All" chip)
// An item that is .active / [aria-current] is never hidden, so the chip you picked stays visible.
// window.GWMore.refresh(root) re-runs it for content added later.
(function () {
    'use strict';

    function itemsOf(box) {
        var sel = box.getAttribute('data-more-items');
        var list;
        if (sel) list = box.querySelectorAll(sel);
        else if (box.tagName === 'TABLE') list = box.querySelectorAll('tbody > tr');
        else list = box.children;
        return Array.prototype.filter.call(list, function (el) {
            return !el.hasAttribute('data-more-skip') && !el.classList.contains('more-row') && !el.classList.contains('more-li');
        });
    }
    function pinned(el) { return el.classList.contains('active') || el.hasAttribute('aria-current'); }

    function setup(box) {
        if (box.__more) { box.__more.apply(); return; }
        var limit = parseInt(box.getAttribute('data-more'), 10);
        if (!(limit > 0)) return;
        var items = itemsOf(box);
        if (items.length <= limit) return;

        var label = box.getAttribute('data-more-label');
        var expanded = false;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'more-btn';

        var tag = box.tagName;
        var isGrid = window.getComputedStyle(box).display.indexOf('grid') === 0;
        var wrap;
        if (tag === 'UL' || tag === 'OL') { wrap = document.createElement('li'); wrap.className = 'more-li'; box.appendChild(wrap); }
        else if (tag === 'TABLE') {
            wrap = document.createElement('div'); wrap.className = 'more-row after';
            var anchor = box.closest('.admin-table-wrapper, .cat-table-wrap') || box;
            anchor.insertAdjacentElement('afterend', wrap);
        }
        else if (isGrid) { wrap = document.createElement('div'); wrap.className = 'more-row'; box.appendChild(wrap); }
        else if (box.hasAttribute('data-more-block')) { wrap = document.createElement('div'); wrap.className = 'more-row after'; box.insertAdjacentElement('afterend', wrap); }
        else { wrap = null; box.appendChild(btn); }                       // chip rows: the button is one more chip
        if (wrap) wrap.appendChild(btn);

        function apply() {
            var hidden = 0;
            items.forEach(function (el, i) {
                var hide = !expanded && i >= limit && !pinned(el);
                el.classList.toggle('more-hidden', hide);
                if (hide) hidden++;
            });
            if (!expanded && hidden === 0) { btn.hidden = true; if (wrap) wrap.hidden = true; return; }
            btn.hidden = false; if (wrap) wrap.hidden = false;
            btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            btn.innerHTML = expanded
                ? 'Show less <i class="bx bx-chevron-up" aria-hidden="true"></i>'
                : 'More' + (label ? ' ' + label : '') + '\u2026 <span class="more-count">(+' + hidden + ')</span> <i class="bx bx-chevron-down" aria-hidden="true"></i>';
        }
        btn.addEventListener('click', function (e) {
            e.preventDefault(); e.stopPropagation();
            expanded = !expanded;
            apply();
            if (!expanded) {                                                // collapsing: don't leave the reader below the list
                var r = box.getBoundingClientRect();
                if (r.top < 0) box.scrollIntoView({ block: 'nearest' });
            }
        });
        box.__more = { apply: apply };
        apply();
    }

    function refresh(root) {
        Array.prototype.forEach.call((root || document).querySelectorAll('[data-more]'), setup);
    }
    window.GWMore = { refresh: refresh };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { refresh(); });
    else refresh();
})();