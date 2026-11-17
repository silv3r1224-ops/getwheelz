/* UX polish, loaded on every page.
   1) Submit lock: a form that is already on its way cannot be sent twice (double-clicked "Book",
      "Pay", "Accept" and friends used to be able to create duplicates), and the pressed button
      shows a small spinner so the visitor knows something is happening.
   2) Lets the browser's back/forward cache restore pages with live buttons, not stuck ones.
   Forms that handle themselves (they call preventDefault, e.g. login/sign-up, which already show
   their own "Signing in..." state) are left alone. Opt out of any form with data-no-lock. */
(() => {
  const LOCK_MS = 12000;                 // safety net: unlock if nothing navigated (e.g. a file download)
  const locked = new WeakMap();          // form -> { button, html, timer }

  function unlock(form) {
    const s = locked.get(form);
    if (!s) return;
    clearTimeout(s.timer);
    locked.delete(form);
    form.removeAttribute("aria-busy");
    if (s.button) {
      s.button.disabled = false;
      s.button.classList.remove("is-submitting");
      s.button.removeAttribute("aria-busy");
      s.spinner?.remove();
    }
  }

  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute("data-no-lock") || (form.target && form.target !== "_self")) return;

    // already sending: swallow the second submit
    if (locked.has(form)) { e.preventDefault(); return; }

    const submitter = e.submitter instanceof HTMLElement ? e.submitter : null;

    // Wait until every other submit listener has run: if one of them took over the form
    // (preventDefault), there is nothing to lock. The timeout also lets the browser read the
    // pressed button's name/value into the request BEFORE we disable it.
    setTimeout(() => {
      if (e.defaultPrevented) return;
      const button = submitter || form.querySelector('button[type="submit"], button:not([type]), input[type="submit"]');
      const state = { button, timer: setTimeout(() => unlock(form), LOCK_MS) };
      locked.set(form, state);
      form.setAttribute("aria-busy", "true");
      if (button) {
        button.classList.add("is-submitting");
        button.setAttribute("aria-busy", "true");
        if (button.tagName === "BUTTON") {
          const sp = document.createElement("span");
          sp.className = "gw-spin";
          sp.setAttribute("aria-hidden", "true");
          button.appendChild(sp);
          state.spinner = sp;
        }
        button.disabled = true;
      }
    }, 0);
  });

  // coming back via back/forward: the page may be restored from cache with a locked form
  addEventListener("pageshow", (e) => {
    if (!e.persisted) return;
    document.querySelectorAll("form[aria-busy]").forEach(unlock);
  });
})();
