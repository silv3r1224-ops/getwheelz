// Live pages: no reloads, and other people's changes show up by themselves.
//
//  1. FORMS        Any form on the site is sent in the background. The server answers as it always did (a redirect
//                  to the page); we take that page and patch only the parts that changed. Buttons show a busy state,
//                  messages appear as NEO's flash messages, nothing jumps, and your scroll place stays.
//  2. SWITCHES     Links that only change the query of the current page (4-wheelers / 2-wheelers, filters, tabs)
//                  do the same: patch, update the address bar, Back button works.
//  3. LIVE         Every few seconds the page asks /live/version whether anything changed anywhere. If so it fetches
//                  its OWN current version (with its own login, so nobody sees more than they should) and patches it.
//
// It never replaces what a script or a person changed on purpose: fields being typed in, tabs, filters, open dialogs,
// maps and anything a script built are left alone (see "ownership" below). If anything unexpected happens BEFORE a
// request is sent, the browser does the normal full-page submit instead, so a form can never get stuck.
//
// Opt-outs:  data-no-live on a <form>/<a>  |  data-live-ignore on any element  |  <body data-live="off"> for a page.

(() => {
    'use strict';
    if (window.GWLive) return;
    const main = () => document.querySelector('main');
    if (!main() || !window.fetch || !window.DOMParser || !window.MutationObserver || !window.URL || !window.FormData) return;

    const IGNORE = '[data-live-ignore], .leaflet-container, canvas, iframe, video, audio, template, script, style, noscript, .flash-container';
    const POLL_MS = 4000;
    const POLL_IDLE_MS = 15000;
    const MIN_GAP_MS = 2500;
    const nativeSubmit = HTMLFormElement.prototype.submit;

    // ------------------------------------------------------------------------------------------ ownership
    // Scripts change the page too (tabs, filters, lists they build...). We watch what THEY do, so a patch never
    // undoes it: attributes a script touched, nodes a script added, and elements whose content a script replaced.
    const jsAttrs = new WeakMap();        // element -> Set of attribute names a script changed
    const jsClassAdd = new WeakMap();     // element -> Set of class names a script added
    const jsClassDel = new WeakMap();     // element -> Set of class names a script removed
    const jsAdded = new WeakSet();        // nodes a script added
    const jsOwnsKids = new WeakSet();     // elements whose children a script replaced or removed
    const setOf = (map, el) => { let s = map.get(el); if (!s) map.set(el, s = new Set()); return s; };
    const tokens = (v) => (v || '').split(/\s+/).filter(Boolean);

    const note = (recs) => {
        // a node that was taken out and put back in the same batch was only MOVED (sorting a table, say):
        // that is not "the script built this" and not "the script emptied this"
        // (only a re-order inside the SAME parent counts: moving a node into another element, as a custom dropdown does
        // with a select's options, means the original parent was emptied by the script)
        const gone = new Map(), came = new Map();
        const put = (m, n, t) => { let s = m.get(n); if (!s) m.set(n, s = new Set()); s.add(t); };
        for (const r of recs) if (r.type === 'childList') { r.removedNodes.forEach((n) => put(gone, n, r.target)); r.addedNodes.forEach((n) => put(came, n, r.target)); }
        const moved = (n, parent) => !!(gone.get(n) && gone.get(n).has(parent) && came.get(n) && came.get(n).has(parent));
        for (const r of recs) {
            if (r.type === 'childList') {
                for (const n of r.removedNodes) { if (!jsAdded.has(n) && !moved(n, r.target)) jsOwnsKids.add(r.target); }
                for (const n of r.addedNodes) { if (!moved(n, r.target)) jsAdded.add(n); }
            } else if (r.type === 'characterData') {
                if (r.target.parentNode) jsOwnsKids.add(r.target.parentNode);
            } else if (r.type === 'attributes') {
                const el = r.target;
                if (r.attributeName === 'class') {
                    const before = new Set(tokens(r.oldValue)), after = new Set(tokens(el.getAttribute('class')));
                    after.forEach((t) => { if (!before.has(t)) { setOf(jsClassAdd, el).add(t); setOf(jsClassDel, el).delete(t); } });
                    before.forEach((t) => {
                        if (after.has(t)) return;
                        const added = setOf(jsClassAdd, el);
                        if (added.has(t)) added.delete(t); else setOf(jsClassDel, el).add(t);
                    });
                } else {
                    setOf(jsAttrs, el).add(r.attributeName);
                }
            }
        }
    };
    const observer = new MutationObserver(note);
    observer.observe(main(), { subtree: true, childList: true, attributes: true, attributeOldValue: true, characterData: true });
    const flush = () => note(observer.takeRecords());
    const quiet = (fn) => { flush(); try { return fn(); } finally { observer.takeRecords(); } };   // our own changes are not "a script's"

    // ------------------------------------------------------------------------------------------ morph
    const isWs = (n) => n.nodeType === 3 && !n.nodeValue.trim();
    const keyOf = (n) => {
        if (n.nodeType !== 1) return '';
        const k = n.id || n.getAttribute('data-live-key');
        if (k) return k;
        const kind = n.getAttribute('data-kind'), id = n.getAttribute('data-id');      // inbox rows
        return kind && id ? kind + ':' + id : '';
    };
    const ignored = (n) => n.nodeType === 1 && n.matches(IGNORE);
    const same = (a, b) => a.nodeType === b.nodeType && (a.nodeType !== 1 || (a.tagName === b.tagName && keyOf(a) === keyOf(b)));
    let pulses = true;

    const pulse = (el) => {
        if (!pulses || !el || el.nodeType !== 1 || el.hasAttribute('data-live-quiet')) return;
        el.classList.remove('gw-live-pulse'); void el.offsetWidth; el.classList.add('gw-live-pulse');
        setTimeout(() => quiet(() => el.classList.remove('gw-live-pulse')), 1300);
    };

    const fresh = (node) => {
        const copy = document.importNode(node, true);
        if (copy.nodeType === 1) {
            copy.querySelectorAll('script').forEach((s) => { if (!/json/i.test(s.type)) s.remove(); });   // never run scripts that arrive in a patch
            if (copy.tagName === 'SCRIPT' && !/json/i.test(copy.type)) return document.createComment('');
        }
        return copy;
    };

    function syncClass(a, b) {
        const want = new Set(tokens(b.getAttribute('class')));
        const add = jsClassAdd.get(a), del = jsClassDel.get(a);
        const have = tokens(a.getAttribute('class'));
        const out = [];
        have.forEach((t) => { if ((add && add.has(t)) || want.has(t)) out.push(t); });          // keep script-added and still-wanted
        want.forEach((t) => { if (!out.includes(t) && !(del && del.has(t))) out.push(t); });     // add new ones (unless a script removed it)
        const next = out.join(' ');
        if (next !== have.join(' ')) { if (next) a.setAttribute('class', next); else a.removeAttribute('class'); return true; }
        return false;
    }

    function syncAttrs(a, b) {
        let changed = false;
        const skip = jsAttrs.get(a);
        for (const { name, value } of Array.from(b.attributes)) {
            if (name === 'class' || (skip && skip.has(name)) || name === 'value' && /^(input|textarea|select)$/i.test(a.tagName)) continue;
            if (a.getAttribute(name) !== value) { a.setAttribute(name, value); changed = true; }
        }
        for (const { name } of Array.from(a.attributes)) {
            if (name === 'class' || (skip && skip.has(name)) || b.hasAttribute(name)) continue;
            if (name === 'value' && /^(input|textarea|select)$/i.test(a.tagName)) continue;
            if (name === 'style' || name === 'open' && a.tagName === 'DETAILS') continue;
            a.removeAttribute(name); changed = true;
        }
        if (syncClass(a, b)) changed = true;
        return changed;
    }

    function syncControl(a, b) {
        if (a === document.activeElement) return;                     // never touch the field being typed in
        const tag = a.tagName;
        if (tag === 'INPUT') {
            const type = (a.type || '').toLowerCase();
            if (type === 'checkbox' || type === 'radio') {
                if (a.checked === a.defaultChecked) {                 // untouched: follow the server
                    const on = b.hasAttribute('checked');
                    if (on) a.setAttribute('checked', ''); else a.removeAttribute('checked');
                    a.checked = on;
                }
            } else if (type !== 'file' && type !== 'password' && a.value === a.defaultValue) {
                const v = b.getAttribute('value') || '';
                if (v !== (a.getAttribute('value') || '')) { a.setAttribute('value', v); a.value = v; }
            }
        } else if (tag === 'TEXTAREA') {
            const untouched = a.value === a.defaultValue;
            if (untouched) a.value = b.value;
        } else if (tag === 'SELECT') {
            const untouched = Array.from(a.options).every((o) => o.selected === o.defaultSelected);
            if (untouched) Array.from(a.options).forEach((o, i) => {
                const want = b.options[i] ? b.options[i].hasAttribute('selected') : false;
                o.selected = want;
                if (want) o.setAttribute('selected', ''); else o.removeAttribute('selected');
            });
        }
    }

    function morphNode(a, b) {
        if (a.nodeType !== 1) {
            if (a.nodeValue !== b.nodeValue) { a.nodeValue = b.nodeValue; pulse(a.parentElement); }
            return;
        }
        const changedAttrs = syncAttrs(a, b);
        if (changedAttrs) pulse(a);
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) syncControl(a, b);
        if (a.matches('[data-live-ignore]') || jsOwnsKids.has(a) || a.tagName === 'TEXTAREA') return;
        morphChildren(a, b);
    }

    function morphChildren(a, b) {
        const keep = Array.from(a.childNodes).filter((n) => !jsAdded.has(n) && !isWs(n) && n.nodeType !== 8);
        const byKey = new Map();
        keep.forEach((n) => { const k = keyOf(n); if (k && !byKey.has(k)) byKey.set(k, n); });
        const used = new Set();
        let p = 0;
        let cursor = a.firstChild;
        const stepOverOthers = () => { while (cursor && (jsAdded.has(cursor) || isWs(cursor) || cursor.nodeType === 8 || used.has(cursor) === false && ignored(cursor))) cursor = cursor.nextSibling; };

        const target = Array.from(b.childNodes);
        for (let i = 0; i < target.length; i++) {
            const t = target[i];
            if (isWs(t) || t.nodeType === 8 || ignored(t)) continue;
            let match = null;
            const k = keyOf(t);
            if (k && byKey.has(k) && !used.has(byKey.get(k))) match = byKey.get(k);
            else if (!k) {
                while (p < keep.length && (used.has(keep[p]) || ignored(keep[p]))) p++;
                const cand = keep[p];
                if (cand && !keyOf(cand) && same(cand, t)) match = cand;
            }
            stepOverOthers();
            if (match) {
                used.add(match);
                if (match !== cursor) a.insertBefore(match, cursor);
                cursor = match.nextSibling;
                morphNode(match, t);
            } else {
                const node = fresh(t);
                a.insertBefore(node, cursor);
                used.add(node);
                if (node.nodeType === 1) pulse(node);
                const next = target[i + 1];
                if (next && isWs(next)) a.insertBefore(document.createTextNode(next.nodeValue), cursor);
            }
        }
        keep.forEach((n) => { if (!used.has(n) && !ignored(n) && n.parentNode === a) a.removeChild(n); });
    }

    // ------------------------------------------------------------------------------------------ progress bar
    // a thin line at the top of the screen while an action or a page switch is on its way
    const progress = (() => {
        const el = document.createElement('div');
        el.className = 'gw-progress'; el.setAttribute('aria-hidden', 'true');
        document.body.appendChild(el);
        let n = 0;
        return {
            start() { n++; el.classList.remove('end'); void el.offsetWidth; el.classList.add('on'); },
            done() { n = Math.max(0, n - 1); if (!n) { el.classList.add('end'); setTimeout(() => { if (!n) el.classList.remove('on', 'end'); }, 380); } },
        };
    })();

    // ------------------------------------------------------------------------------------------ applying a page
    const pagePath = () => location.pathname;
    const samePath = (u) => new URL(u, location.href).pathname === pagePath();

    function showFlashes(doc) {
        const items = Array.from(doc.querySelectorAll('.flash-container .flash-item'));
        if (!items.length || !window.GW || !window.GW.neoToast) return;
        items.forEach((it) => {
            const text = (it.querySelector('.flash-message span') || {}).textContent || '';
            if (text.trim()) window.GW.neoToast(text.trim(), it.getAttribute('data-cat') === 'success' ? 'success' : 'error');
        });
    }

    function stashFlashes(doc) {
        try {
            const list = Array.from(doc.querySelectorAll('.flash-container .flash-item')).map((it) => ({
                cat: it.getAttribute('data-cat') === 'success' ? 'success' : 'error',
                text: ((it.querySelector('.flash-message span') || {}).textContent || '').trim(),
            })).filter((x) => x.text);
            if (list.length) sessionStorage.setItem('gw:flash', JSON.stringify(list));
        } catch (e) { /* storage blocked */ }
    }

    function applyHtml(html, { source }) {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const next = doc.querySelector('main');
        if (!next || !main()) return false;
        flush();
        pulses = true;
        try {
            if (doc.title && doc.title !== document.title) document.title = doc.title;
            morphChildren(main(), next);
        } finally { observer.takeRecords(); }
        showFlashes(doc);
        document.dispatchEvent(new CustomEvent('gw:live-updated', { detail: { source } }));
        lastApplied = Date.now();
        return true;
    }

    const isHtml = (res) => /text\/html/i.test(res.headers.get('content-type') || '');
    let lastApplied = Date.now();
    let inFlight = null;

    // GET a page and patch it in (switches, Back/Forward, live refresh)
    async function visit(url, opts = {}) {
        const showBar = (opts.source || 'nav') === 'nav';
        if (showBar) progress.start();
        try { return await visitInner(url, opts); } finally { if (showBar) progress.done(); }
    }

    async function visitInner(url, { push = false, source = 'nav' } = {}) {
        const target = new URL(url, location.href);
        let res;
        try {
            res = await fetch(target.href, { credentials: 'same-origin', cache: 'no-store', headers: { 'X-GW-Live': '1', Accept: 'text/html' } });
        } catch (e) { return fail(source, 'network'); }
        const finalUrl = new URL(res.url || target.href);
        if (!isHtml(res)) return source === 'nav' ? location.assign(target.href) : false;
        if (res.status >= 500) return fail(source, 'server');
        if (finalUrl.pathname !== target.pathname) {                      // sent somewhere else (signed out, suspended, moved)
            const doc = new DOMParser().parseFromString(await res.text(), 'text/html'); stashFlashes(doc);
            return void location.assign(finalUrl.href);
        }
        if (res.status >= 400) {
            if (source === 'poll') return void location.reload();          // this page no longer exists for us
            return fail(source, 'client');
        }
        const html = await res.text();
        if (source === 'nav') {
            if (push) history.pushState({ gwLive: 1 }, '', finalUrl.href); else if (finalUrl.href !== location.href) history.replaceState({ gwLive: 1 }, '', finalUrl.href);
        }
        if (!applyHtml(html, { source })) { if (source === 'nav') location.assign(finalUrl.href); return false; }
        return true;
    }

    function fail(source, kind) {
        if (source === 'poll') return false;                                // a failed background check is silent: it simply retries
        const msg = kind === 'network' ? 'Could not reach the server. Check your connection and try again.' : 'Something went wrong. Please try again.';
        if (window.GW && window.GW.neoToast) window.GW.neoToast(msg, 'error');
        return false;
    }

    // ------------------------------------------------------------------------------------------ forms
    const liveOff = () => document.body.getAttribute('data-live') === 'off';
    const actionOf = (form) => new URL(form.getAttribute('action') || location.href, location.href);
    const methodOf = (form) => (form.getAttribute('method') || 'get').toLowerCase();

    function eligible(form) {
        if (!(form instanceof HTMLFormElement) || liveOff() || form.closest('[data-no-live]') || form.hasAttribute('data-no-live')) return false;
        const t = form.getAttribute('target');
        if (t && t !== '_self') return false;
        let u; try { u = actionOf(form); } catch (e) { return false; }
        if (u.origin !== location.origin) return false;
        const m = methodOf(form);
        if (m === 'post') return true;
        return m === 'get' && u.pathname === pagePath();                    // filters on this page; searches to another page navigate normally
    }

    const busyOn = (form, btn) => quiet(() => {
        form.__gwBusy = true; form.setAttribute('aria-busy', 'true');
        if (btn) { btn.classList.add('is-busy'); btn.setAttribute('aria-disabled', 'true'); }
    });
    const busyOff = (form, btn) => quiet(() => {
        form.__gwBusy = false; form.removeAttribute('aria-busy');
        if (btn) { btn.classList.remove('is-busy'); btn.removeAttribute('aria-disabled'); }
    });

    // after a successful submit the server's answer is the truth: let the form's own fields follow it
    function adoptValues(form) {
        quiet(() => {
            Array.from(form.elements).forEach((el) => {
                if (el.type === 'checkbox' || el.type === 'radio') el.defaultChecked = el.checked;
                else if (el.tagName === 'SELECT') Array.from(el.options).forEach((o) => { o.defaultSelected = o.selected; });
                else if (el.type !== 'file' && el.type !== 'password' && 'defaultValue' in el) el.defaultValue = el.value;
            });
        });
    }

    // a pop-up that held the form closes once the action worked (a failed one stays open, with what was typed)
    function closeModalOf(form) {
        const box = form.closest('.login-modal, .modal, .px-modal, [role="dialog"]');
        if (!box || !box.isConnected) return;
        ['show', 'open', 'is-open', 'active'].forEach((c) => box.classList.remove(c));
        if (!document.querySelector('.login-modal.show')) document.querySelectorAll('.pop').forEach((el) => el.classList.remove('pop'));
        document.body.classList.remove('modal-open', 'no-scroll');
    }

    function download(res, blob) {
        const name = ((res.headers.get('content-disposition') || '').match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i) || [])[1] || 'download';
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob); a.download = decodeURIComponent(name); document.body.appendChild(a); a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
    }

    async function send(form, submitter) {
        if (form.__gwBusy) return;
        const method = methodOf(form), action = actionOf(form);
        let body;
        try {
            body = new FormData(form, submitter || undefined);
            if (submitter && submitter.name && !body.has(submitter.name)) body.append(submitter.name, submitter.value);   // older browsers
        } catch (e) { return nativeSubmit.call(form); }                      // nothing sent yet: do it the normal way

        if (method === 'get') {                                              // a filter on this page
            const q = new URLSearchParams();
            body.forEach((v, k) => { if (typeof v === 'string') q.append(k, v); });
            action.search = q.toString();
            busyOn(form, submitter);
            try { await visit(action.href, { push: true, source: 'nav' }); } finally { busyOff(form, submitter); }
            return;
        }

        busyOn(form, submitter);
        progress.start();
        let res;
        try {
            res = await fetch(action.href, { method: 'POST', body, credentials: 'same-origin', headers: { 'X-GW-Live': '1', Accept: 'text/html,application/json' } });
        } catch (e) {
            busyOff(form, submitter);
            return fail('form', 'network');                                  // never re-send after a request went out
        }
        try {
            if (window.fwStayPut) window.fwStayPut.discard();
            const type = res.headers.get('content-type') || '';
            if (/application\/json/i.test(type)) {
                const data = await res.json().catch(() => ({}));
                if (data.redirect) return void location.assign(data.redirect);
                const text = data.error || data.message;
                if (text && window.GW) window.GW.neoToast(text, res.ok && data.ok !== false ? 'success' : 'error');
                if (res.ok) refresh('form');
                return;
            }
            if (!isHtml(res)) {
                if (res.ok) download(res, await res.blob()); else fail('form', 'server');
                return;
            }
            const html = await res.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            if (res.status === 400 && /csrf/i.test(doc.body ? doc.body.textContent : '')) {
                if (window.GW) window.GW.neoToast('Your session timed out. Refreshing the page…', 'error');
                return void setTimeout(() => location.reload(), 1200);
            }
            if (res.status === 429) return void (window.GW && window.GW.neoToast('Too many attempts. Please wait a moment and try again.', 'error'));
            if (res.status >= 400) {
                const flashed = doc.querySelectorAll('.flash-container .flash-item').length;
                if (flashed) showFlashes(doc); else fail('form', 'server');
                return;
            }
            const finalUrl = new URL(res.url || action.href);
            if (finalUrl.pathname !== pagePath()) {                          // the action moved us to another page: go there
                stashFlashes(doc);
                return void location.assign(finalUrl.href);
            }
            if (finalUrl.href !== location.href) history.replaceState({ gwLive: 1 }, '', finalUrl.href);
            const failed = !!doc.querySelector('.flash-container .flash-item[data-cat="error"]');
            if (!failed) {
                adoptValues(form);
                form.querySelectorAll('input[type="password"]').forEach((i) => { i.value = ''; });   // never keep a password on screen
            }
            if (!applyHtml(html, { source: 'form' })) { stashFlashes(doc); location.assign(finalUrl.href); return; }
            if (!failed) closeModalOf(form);
        } finally {
            busyOff(form, submitter);
            progress.done();
        }
    }

    document.addEventListener('submit', (e) => {
        if (e.defaultPrevented || !eligible(e.target)) return;
        e.preventDefault();
        send(e.target, e.submitter);
    });

    // forms submitted from code, such as the confirm dialog's "Yes"
    HTMLFormElement.prototype.submit = function () {
        if (eligible(this)) { send(this, null); return; }
        return nativeSubmit.call(this);
    };

    // ------------------------------------------------------------------------------------------ switches (same page, other query)
    document.addEventListener('click', (e) => {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || liveOff()) return;
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download') || a.hasAttribute('data-no-live') || a.closest('[data-no-live]')) return;
        let u; try { u = new URL(a.href, location.href); } catch (err) { return; }
        if (u.origin !== location.origin || u.pathname !== pagePath() || u.search === location.search || !a.closest('main')) return;
        e.preventDefault();
        visit(u.href, { push: true, source: 'nav' });
    });

    let lastSearch = location.search;
    window.addEventListener('popstate', () => {
        if (location.search === lastSearch) return;                          // an #anchor, not a page change
        lastSearch = location.search;
        visit(location.href, { push: false, source: 'nav' });
    });
    document.addEventListener('gw:live-updated', () => { lastSearch = location.search; });

    // ------------------------------------------------------------------------------------------ live refresh
    let knownVersion = null, dirty = false, timer = 0, lastInput = Date.now();
    ['pointerdown', 'keydown', 'touchstart', 'scroll'].forEach((ev) => addEventListener(ev, () => { lastInput = Date.now(); }, { passive: true, capture: true }));

    const dialogOpen = () => {
        const sel = '.confirm-dialog.show, [role="dialog"][aria-modal="true"], .modal.show, .modal.open, .modal.is-open, .px-modal.is-open, #ntCard:not([hidden])';
        return Array.from(document.querySelectorAll(sel)).some((el) => {
            if (el.hidden) return false;
            const cs = getComputedStyle(el);
            return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity !== 0 && el.getClientRects().length > 0;
        });
    };
    const busyNow = () => !!document.querySelector('form[aria-busy="true"]') || !!inFlight;

    async function refresh(source = 'poll') {
        if (inFlight) return inFlight;
        inFlight = (async () => {
            try { return await visit(location.href, { push: false, source: source === 'form' ? 'poll' : source }); }
            finally { inFlight = null; }
        })();
        return inFlight;
    }

    async function tick() {
        clearTimeout(timer);
        if (!document.hidden && !liveOff()) {
            try {
                const res = await fetch('/live/version', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
                if (res.ok) {
                    const { v } = await res.json();
                    if (v != null) {
                        if (knownVersion === null) knownVersion = v;
                        else if (v !== knownVersion) { knownVersion = v; dirty = true; }
                    }
                }
            } catch (e) { /* offline: try again next time */ }
            if (dirty && !busyNow() && !dialogOpen() && Date.now() - lastApplied >= MIN_GAP_MS) {
                dirty = false;
                await refresh('poll');
            }
        }
        timer = setTimeout(tick, Date.now() - lastInput > 10 * 60 * 1000 ? POLL_IDLE_MS : POLL_MS);
    }

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) return;
        if (Date.now() - lastApplied > 30000) dirty = true;                  // been away: catch up
        tick();
    });
    addEventListener('online', () => { dirty = true; tick(); });
    addEventListener('pageshow', (e) => { if (e.persisted) { dirty = true; tick(); } });
    timer = setTimeout(tick, 1200);

    // refresh() resolves true when the page was patched, so a script can fall back to a normal reload if it was not
    window.GWLive = {
        refresh: () => refresh('poll'),
        visit: (u) => visit(u, { push: true, source: 'nav' }),
        replace: (u) => visit(u, { push: false, source: 'nav' }),   // same page, new query, no extra Back entry
        busy: busyNow,
    };
})();
