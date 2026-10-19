//=====================================================================Owner: Create Workshop modal + map picker====================================

const createWorkshopModal = document.getElementById('createWorkshopModal');
const createWorkshopForm = document.getElementById('createWorkshopForm');
const createWorkshopTriggers = document.querySelectorAll('#create-workshop-btn, [data-open-create-workshop], [data-open-edit-workshop]');
const SUBMIT_LABELS = { create: ['Create workshop', 'Creating…'], edit: ['Save changes', 'Saving…'] };
let workshopMode = createWorkshopForm && createWorkshopForm.dataset.mode ? createWorkshopForm.dataset.mode : 'create';

let pinMap = null;
let pinMarker = null;
let createWorkshopOpener = null;

function setLocationStatus(state, text) {
    const el = document.getElementById('location-status');
    if (!el) return;
    el.dataset.state = state; // empty | busy | ok | error
    el.textContent = text;
}

function showFieldError(inputId, errorId, message) {
    const input = document.getElementById(inputId);
    const error = document.getElementById(errorId);
    if (input) input.setAttribute('aria-invalid', 'true');
    if (error) {
        error.textContent = message;
        error.hidden = false;
    }
}

function clearFieldError(inputId, errorId) {
    const input = document.getElementById(inputId);
    const error = document.getElementById(errorId);
    if (input) input.removeAttribute('aria-invalid');
    if (error) error.hidden = true;
}

function clearLocationError() {
    const wrap = document.getElementById('cwMapWrap');
    const error = document.getElementById('cwLocationError');
    if (wrap) wrap.classList.remove('has-error');
    if (error) error.hidden = true;
}

function setPin(lat, lng) {
    document.getElementById('latitude').value = lat;
    document.getElementById('longitude').value = lng;
    setLocationStatus('ok', `Pin set at ${lat.toFixed(5)}, ${lng.toFixed(5)}`);
    clearLocationError();

    if (pinMarker) {
        pinMarker.setLatLng([lat, lng]);
    } else {
        pinMarker = L.marker([lat, lng], { draggable: true }).addTo(pinMap);
        pinMarker.on('dragend', () => {
            const pos = pinMarker.getLatLng();
            setPin(pos.lat, pos.lng);
        });
    }
}

function centerOnUserLocation(dropPin) {
    if (!navigator.geolocation) {
        setLocationStatus('error', "Your browser can't share its location. Click the map to set your pin instead.");
        return;
    }

    setLocationStatus('busy', 'Detecting your location…');
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;
            pinMap.setView([lat, lng], 16);
            if (dropPin) {
                setPin(lat, lng);
            } else {
                setLocationStatus('ok', 'Map centered on your current location.');
            }
        },
        () => {
            setLocationStatus('error', "Couldn't detect your location. Click the map to set your pin instead.");
        },
        { timeout: 10000 }
    );
}

function initPinMap() {
    if (pinMap) return;
    pinMap = L.map('workshop-pin-map').setView([26.1445, 91.7362], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(pinMap);
    pinMap.on('click', (e) => setPin(e.latlng.lat, e.latlng.lng));
}

// Edit mode: fill the form from the Edit Details button's data-* attributes and put the pin where it is now.
function fillFromWorkshop(btn) {
    createWorkshopForm.action = btn.dataset.action;
    document.getElementById('cwName').value = btn.dataset.name || '';
    document.getElementById('cwAddress').value = btn.dataset.address || '';
    document.getElementById('cwContact').value = btn.dataset.contact || '';
    ['cwName', 'cwAddress', 'cwContact'].forEach((id) => clearFieldError(id, id + 'Error'));
    clearLocationError();

    const lat = parseFloat(btn.dataset.lat);
    const lng = parseFloat(btn.dataset.lng);
    if (!isNaN(lat) && !isNaN(lng)) {
        pinMap.setView([lat, lng], 16);
        setPin(lat, lng);
    }
}

function openCreateWorkshop(opener) {
    if (!createWorkshopModal) return;
    createWorkshopOpener = opener || null;
    createWorkshopModal.classList.add('show');
    document.body.classList.add('fw-scroll-lock');
    initPinMap();
    workshopMode = opener && opener.hasAttribute('data-open-edit-workshop') ? 'edit' : 'create';
    if (workshopMode === 'edit') fillFromWorkshop(opener);
    // Leaflet must re-measure once the container is actually visible.
    setTimeout(() => pinMap && pinMap.invalidateSize(), 120);
    const first = document.getElementById('cwName');
    if (first) first.focus();
}

function closeCreateWorkshop() {
    if (!createWorkshopModal) return;
    createWorkshopModal.classList.remove('show');
    document.body.classList.remove('fw-scroll-lock');
    if (createWorkshopOpener && document.contains(createWorkshopOpener)) createWorkshopOpener.focus();
    createWorkshopOpener = null;
}

if (createWorkshopModal && createWorkshopForm) {
    createWorkshopTriggers.forEach((trigger) => {
        trigger.addEventListener('click', (e) => {
            e.preventDefault();
            openCreateWorkshop(trigger);
        });
    });

    // Close: X / Cancel buttons, a click on the dark backdrop, or Escape.
    createWorkshopModal.querySelectorAll('[data-close]').forEach((btn) => {
        btn.addEventListener('click', closeCreateWorkshop);
    });
    // Only treat it as a backdrop click if the press also STARTED on the backdrop,
    // so dragging to select text inside an input never closes the dialog.
    let pressStartedOnBackdrop = false;
    createWorkshopModal.addEventListener('pointerdown', (e) => {
        pressStartedOnBackdrop = e.target === createWorkshopModal;
    });
    createWorkshopModal.addEventListener('click', (e) => {
        if (e.target === createWorkshopModal && pressStartedOnBackdrop) closeCreateWorkshop();
    });
    document.addEventListener('keydown', (e) => {
        if (!createWorkshopModal.classList.contains('show')) return;
        if (e.key === 'Escape') {
            closeCreateWorkshop();
        } else if (e.key === 'Tab') {
            // keep keyboard focus inside the dialog
            const focusable = createWorkshopModal.querySelectorAll(
                'button:not([disabled]), input:not([type="hidden"]):not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
            );
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });

    document.getElementById('cwUseLocation').addEventListener('click', () => centerOnUserLocation(true));

    // Clear a field's error as soon as the person starts fixing it.
    [['cwName', 'cwNameError'], ['cwAddress', 'cwAddressError'], ['cwContact', 'cwContactError']].forEach(([i, e]) => {
        document.getElementById(i).addEventListener('input', () => clearFieldError(i, e));
    });

    // Validate in the browser first, with clear inline messages.
    createWorkshopForm.addEventListener('submit', (e) => {
        const name = document.getElementById('cwName');
        const address = document.getElementById('cwAddress');
        const contact = document.getElementById('cwContact');
        let firstInvalid = null;
        const fail = (el, errId, message) => {
            showFieldError(el.id, errId, message);
            if (!firstInvalid) firstInvalid = el;
        };

        clearFieldError('cwName', 'cwNameError');
        clearFieldError('cwAddress', 'cwAddressError');
        clearFieldError('cwContact', 'cwContactError');
        clearLocationError();

        if (!name.value.trim()) fail(name, 'cwNameError', 'Please enter your workshop name.');
        if (!address.value.trim()) fail(address, 'cwAddressError', 'Please enter your workshop address.');
        if (contact.value.trim() && !/^[0-9+()\-\s]{6,20}$/.test(contact.value.trim())) {
            fail(contact, 'cwContactError', 'Enter a valid phone number, e.g. +91 98765 43210.');
        }
        if (!document.getElementById('latitude').value || !document.getElementById('longitude').value) {
            const mapEl = document.getElementById('workshop-pin-map');
            const err = document.getElementById('cwLocationError');
            err.textContent = 'Please drop a pin so customers can find your workshop.';
            err.hidden = false;
            document.getElementById('cwMapWrap').classList.add('has-error');
            if (!firstInvalid) firstInvalid = mapEl;
        }

        if (firstInvalid) {
            e.preventDefault();
            firstInvalid.scrollIntoView({ block: 'center', behavior: 'smooth' });
            if (typeof firstInvalid.focus === 'function') firstInvalid.focus({ preventScroll: true });
            return;
        }

        const submit = document.getElementById('cwSubmit');
        submit.disabled = true; // prevent double submits
        submit.textContent = SUBMIT_LABELS[workshopMode][1];
    });

    // If the person comes back with the browser's Back button, don't leave the button stuck.
    window.addEventListener('pageshow', () => {
        const submit = document.getElementById('cwSubmit');
        submit.disabled = false;
        submit.textContent = SUBMIT_LABELS[workshopMode][0];
    });
}

//OWNER
const addServiceBtn = document.getElementById('add-service-btn');
const addServiceModal = document.getElementById('addServiceModal');

if (addServiceBtn && addServiceModal) {
    addServiceBtn.addEventListener('click', () => addServiceModal.classList.add('show'));
    addServiceModal.addEventListener('click', (e) => {
        if (e.target === addServiceModal) addServiceModal.classList.remove('show');
    });
}

//=====================================================================Filter popover=================================================================

const filterToggleBtn = document.getElementById('filter-toggle-btn');
const filterPopover = document.getElementById('filterPopover');

if (filterToggleBtn && filterPopover) {
    filterToggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        filterPopover.classList.toggle('show');
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.filter-wrapper')) {
            filterPopover.classList.remove('show');
        }
    });
}

//=====================================================================Hero search: attach location silently before submit=============================

const heroSearchForm = document.getElementById('hero-search-form');
if (heroSearchForm && navigator.geolocation) {
    heroSearchForm.addEventListener('submit', (e) => {
        const latField = document.getElementById('search-lat');
        if (latField.value) return; // already have coordinates, let it submit normally
        e.preventDefault();
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                document.getElementById('search-lat').value = pos.coords.latitude;
                document.getElementById('search-lng').value = pos.coords.longitude;
                heroSearchForm.submit();
            },
            () => heroSearchForm.submit() // proceed without location if denied
        );
    });
}

document.querySelectorAll(".number-stepper").forEach(stepper => {
    const input = stepper.querySelector("input");
    const decrease = stepper.querySelector(".decrease");
    const increase = stepper.querySelector(".increase");

    decrease.addEventListener("click", () => {
        const min = input.min !== "" ? Number(input.min) : -Infinity;
        const step = input.step !== "" && input.step !== "any"
            ? Number(input.step)
            : 1;
        const current = input.value === "" ? 0 : Number(input.value);

        input.value = Math.max(min, current - step);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    increase.addEventListener("click", () => {
        const max = input.max !== "" ? Number(input.max) : Infinity;
        const step = input.step !== "" && input.step !== "any"
            ? Number(input.step)
            : 1;
        const current = input.value === "" ? 0 : Number(input.value);

        input.value = Math.min(max, current + step);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    });
});