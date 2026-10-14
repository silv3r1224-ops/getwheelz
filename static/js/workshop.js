//=====================================================================Owner: Create Workshop modal + map picker====================================

const createWorkshopBtn = document.getElementById('create-workshop-btn');
const createWorkshopModal = document.getElementById('createWorkshopModal');

let pinMap = null;
let pinMarker = null;

function setPin(lat, lng) {
    document.getElementById('latitude').value = lat;
    document.getElementById('longitude').value = lng;
    document.getElementById('location-status').textContent =
        `Pin set ✓ (${lat.toFixed(5)}, ${lng.toFixed(5)})`;

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
    if (!navigator.geolocation) return;

    document.getElementById('location-status').textContent = 'Detecting your location...';
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;
            pinMap.setView([lat, lng], 16);
            if (dropPin) {
                setPin(lat, lng);
            } else {
                document.getElementById('location-status').textContent =
                    'Map centered on your current location.';
            }
        },
        () => {
            document.getElementById('location-status').textContent =
                'Could not detect location — click the map to set your pin manually.';
        }
    );
}

if (createWorkshopBtn && createWorkshopModal) {
    createWorkshopBtn.addEventListener('click', () => {
        createWorkshopModal.classList.add('show');
        if (!pinMap) {
            pinMap = L.map('workshop-pin-map').setView([26.1445, 91.7362], 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors',
            }).addTo(pinMap);

            const LocateControl = L.Control.extend({
                options: { position: 'topright' },
                onAdd: function () {
                    const container = L.DomUtil.create('div', 'leaflet-bar leaflet-control locate-control');
                    container.innerHTML = `<a href="#" title="Go to my location"><i class='bx bx-current-location'></i></a>`;
                    L.DomEvent.disableClickPropagation(container);
                    L.DomEvent.on(container, 'click', (e) => {
                        e.preventDefault();
                        centerOnUserLocation(true);
                    });
                    return container;
                },
            });
            pinMap.addControl(new LocateControl());
            pinMap.on('click', (e) => {
                setPin(e.latlng.lat, e.latlng.lng);
            });
            centerOnUserLocation(true);
        } else {
            setTimeout(() => pinMap.invalidateSize(), 100);
        }
    });

    createWorkshopModal.addEventListener('click', (e) => {
        if (e.target === createWorkshopModal) {
            createWorkshopModal.classList.remove('show');
        }
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