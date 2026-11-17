/* Motion governor: pauses endless CSS animations while they cannot be seen.
   The site has ~70 infinite animations (glows, floats, shimmers). Off-screen or in a background
   tab they still cost style/paint work, which drains phone batteries and steals frames from the
   things the visitor is actually looking at. This pauses each one when its element leaves the
   viewport (or the tab is hidden) and resumes it, in phase, when it returns. It never touches
   CSS, finite animations, transitions, or anything the visitor's reduced-motion setting already
   stopped. Unsupported browsers simply keep the plain CSS behaviour. */
(() => {
  if (!("IntersectionObserver" in window) || typeof document.getAnimations !== "function") return;

  const visible = new WeakMap();          // element -> is (nearly) on screen
  const mine = new WeakSet();             // animations this script paused (so it only resumes those)
  const watched = new WeakSet();          // elements already observed

  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      visible.set(e.target, e.isIntersecting);
      apply(e.target);
    }
  }, { rootMargin: "160px 0px" });         // start a little early so nothing pops in mid-cycle

  const isEndless = (a) => {
    if (!(typeof CSSAnimation !== "undefined" && a instanceof CSSAnimation)) return false;
    try { return a.effect && a.effect.getComputedTiming().iterations === Infinity; } catch (e) { return false; }
  };

  const root = document.documentElement;
  const lite = () => root.classList.contains("perf-lite");
  // things that must keep moving even in lite mode: busy spinners and the scrolling marquee
  const ESSENTIAL = ".gw-spin, [aria-busy='true'], .px-marquee, .px-marquee-track";

  function apply(el) {
    const keepRunning = !lite() || el.closest(ESSENTIAL);
    const show = visible.get(el) !== false && !document.hidden && keepRunning;
    // subtree:true is what also returns animations on the element's ::before / ::after
    // (the aurora glows); keep only the ones that belong to this element or its pseudo-elements
    for (const a of el.getAnimations({ subtree: true })) {
      if (!a.effect || a.effect.target !== el || !isEndless(a)) continue;
      if (show) {
        if (mine.has(a) && a.playState === "paused") { a.play(); }
        mine.delete(a);
      } else if (a.playState === "running") {
        mine.add(a);
        a.pause();
      }
    }
  }

  function watch(el) {
    if (!(el instanceof Element) || watched.has(el)) return;
    watched.add(el);
    io.observe(el);
  }

  function scan() {
    for (const a of document.getAnimations()) {
      if (!isEndless(a)) continue;
      const t = a.effect && a.effect.target;
      if (t) watch(t);
    }
  }

  // every animation announces itself when it starts, including ones created after load
  document.addEventListener("animationstart", (e) => {
    if (e.target instanceof Element) { watch(e.target); }
  }, true);

  const applyAll = () => {
    document.querySelectorAll("*").forEach((el) => {
      if (watched.has(el)) apply(el);
    });
  };
  document.addEventListener("visibilitychange", applyAll);

  /* Adaptive lite mode. On a weak or busy machine the decorative motion (floating cards, glows,
     pulses) is exactly what makes scrolling stutter. After the page has settled we sample ~55
     frames; if the typical frame takes longer than ~42ms (under 24 fps) we freeze the decorative
     endless animations (paused, never removed, so nothing can vanish) and remember that for a day.
     ?perf=lite forces it on, ?perf=full turns it off and clears the memory. */
  const KEY = "gw:perf";
  let forced = null;
  try { forced = new URLSearchParams(location.search).get("perf"); } catch (e) { /* ignore */ }
  // (the tiny script in <head> already applied ?perf=, the remembered state, and weak-hardware detection)

  function goLite() {
    if (lite()) return;
    root.classList.add("perf-lite");
    // Lite applies to this page straight away. It is only REMEMBERED (for a day) if the device was
    // slow twice within ten minutes, so one busy moment cannot downgrade the site for everyone.
    try {
      const now = Date.now(), lastStrike = +localStorage.getItem("gw:strike") || 0;
      if (now - lastStrike < 10 * 60 * 1000) localStorage.setItem(KEY, String(now));
      else localStorage.setItem("gw:strike", String(now));
    } catch (e) { /* storage blocked: judged again on the next page */ }
    scan();
    applyAll();
    dispatchEvent(new Event("gw:lite"));
  }

  function judge(attempt = 0) {
    if (lite() || forced === "full" || forced === "lite") return;
    if (document.hidden) { if (attempt < 8) setTimeout(() => judge(attempt + 1), 2000); return; }
    const gaps = [];
    let last = 0;
    const step = (now) => {
      if (document.hidden) { return judge(attempt + 1); }          // tab switched mid-sample: start over later
      if (last) gaps.push(now - last);
      last = now;
      const g = gaps.slice(3).sort((a, b) => a - b);              // ignore the first frames while things settle
      const median = g[Math.floor(g.length / 2)];
      // very slow: decide after ~10 frames (about 1s on a weak phone); otherwise after ~28 frames
      if (g.length >= 8 && median > 90 && g[0] < 600) return goLite();
      if (g.length >= 25) { if (median > 40 && g[0] < 400) goLite(); return; }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    let judged = false;
    const once = () => { if (judged) return; judged = true; setTimeout(judge, 500); };
    addEventListener("fw:loaded", once);
    addEventListener("load", () => setTimeout(once, 3000), { once: true });   // pages without the intro curtain
  }

  if (document.readyState === "complete") scan();
  else addEventListener("load", () => setTimeout(scan, 300), { once: true });
  addEventListener("fw:loaded", () => setTimeout(scan, 100));
})();
