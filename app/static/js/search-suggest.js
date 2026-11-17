/* Hero search suggestions: a small combobox over the service catalog.
   Progressive enhancement — the form submits fine without it. Typing filters
   catalog service names; ↑/↓ move through the list, Enter submits, Escape
   dismisses, and clicking a suggestion fills the box and searches at once. */
(() => {
  const form = document.querySelector('.lp-search') || document.querySelector('.px-search');
  if (!form) return;
  const input = form.querySelector('input[name="service"]');
  const box = document.getElementById('searchSuggestions');
  if (!input || !box) return;

  let services = [];
  try {
    const feed = document.getElementById('serviceNames');
    if (feed) {
      const parsed = JSON.parse(feed.textContent || '[]');
      if (Array.isArray(parsed)) services = parsed;
    }
  } catch (_) { /* no suggestions without the feed */ }
  services = [...new Set(services.map(s => String(s).trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  if (!services.length) return;

  const MIN = 1;
  let items = [], active = -1, hideTimer = 0;

  const iconFor = name => {
    const n = name.toLowerCase();
    if (n.includes('engine') || /electr|battery/.test(n)) return 'bx-bolt-circle';
    if (/tire|tyre|wheel/.test(n)) return 'bx-disc';
    if (/\bac\b|air|conditioning|cooling/.test(n)) return 'bx-wind';
    if (n.includes('brake')) return 'bx-stop-circle';
    if (/oil|fluid/.test(n)) return 'bx-droplet';
    if (/paint|body|dent/.test(n)) return 'bx-brush';
    if (/wash|clean|detail/.test(n)) return 'bx-water';
    return 'bx-wrench';
  };

  const close = () => {
    box.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  };
  const open = () => {
    box.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  function setActive(i) {
    if (active >= 0 && active < items.length) items[active].classList.remove('is-active');
    if (i < 0 || i >= items.length) {
      active = -1;
      input.removeAttribute('aria-activedescendant');
      return;
    }
    active = i;
    items[active].classList.add('is-active');
    input.setAttribute('aria-activedescendant', items[active].id);
    items[active].scrollIntoView({ block: 'nearest' });
  }

  function render(q) {
    const query = q.trim().toLowerCase();
    if (query.length < MIN) { close(); return; }
    const matches = services.filter(s => s.toLowerCase().includes(query)).slice(0, 8);
    if (!matches.length) { close(); return; }
    box.innerHTML = '';
    items = [];
    matches.forEach((s, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'option');
      b.id = 'sugg-' + i;
      b.style.setProperty('--i', i);
      const icon = document.createElement('i');
      icon.className = 'bx ' + iconFor(s);
      const label = document.createElement('span');
      label.textContent = s;
      const tag = document.createElement('small');
      tag.textContent = 'Service';
      b.append(icon, label, tag);
      b.addEventListener('pointerdown', e => {
        e.preventDefault();
        input.value = s;
        form.submit();
      });
      b.addEventListener('mousemove', () => setActive(i));
      box.appendChild(b);
      items.push(b);
    });
    active = -1;
    open();
  }

  let timer = 0;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => render(input.value), 80);
  });

  input.addEventListener('keydown', e => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
    else if (e.key === 'Enter') {
      if (active >= 0) {
        e.preventDefault();
        input.value = items[active].querySelector('span').textContent;
        form.submit();
      }
    } else if (e.key === 'Escape') {
      close();
      input.blur();
    }
  });

  input.addEventListener('blur', () => { hideTimer = setTimeout(close, 140); });
  input.addEventListener('focus', () => {
    clearTimeout(hideTimer);
    if (input.value.trim()) render(input.value);
  });
  box.addEventListener('pointerdown', () => clearTimeout(hideTimer));
})();
