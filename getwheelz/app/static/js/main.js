//=====================================================================Header====================================================================

//subnav
const dropdownMenu = document.getElementById("dropdownMenu");
const dropdown = document.getElementById("dropdown");

if (dropdownMenu && dropdown) {
    dropdown.addEventListener("click", (e) => {
        e.preventDefault();
        dropdownMenu.classList.add("show");
    });

    window.onclick = (e) => {
        if (e.target != dropdown) {
            dropdownMenu.classList.remove("show");
        }
    }
}

//theme toggle
const themeToggle = document.getElementById("theme-toggle");
const theme = document.getElementById("theme");

if (localStorage.getItem("theme") === "light") {
    document.body.classList.add("light");
    theme.classList.replace("bx-sun", "bx-moon");
} else {
    theme.classList.replace("bx-moon", "bx-sun");
}

themeToggle.addEventListener("click", () => {
    document.body.classList.toggle("light");

    if (document.body.classList.contains("light")) {
        theme.classList.replace("bx-sun", "bx-moon");
        localStorage.setItem("theme", "light");
    } else {
        theme.classList.replace("bx-moon", "bx-sun");
        localStorage.setItem("theme", "dark");
    }
});

//=====================================================================Header: Use my location=====================================================
const locationBtn = document.getElementById('location-btn');

if (locationBtn) {
    locationBtn.addEventListener('click', () => {
        if (!navigator.geolocation) {
            alert('Your browser does not support location access.');
            return;
        }

        locationBtn.querySelector('i').classList.add('bx-spin');

        navigator.geolocation.getCurrentPosition(
            (position) => {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                window.location.href = `/workshops/search?lat=${lat}&lng=${lng}`;
            },
            (error) => {
                locationBtn.querySelector('i').classList.remove('bx-spin');
                alert('Could not access your location. Please allow location access and try again.');
            }
        );
    });
}
//=====================================================================Body========================================================================
//login form
const header = document.querySelector("header");
const loginModal = document.getElementById("loginModal");
const signUp = document.getElementById("signUp");
const signUpModal = document.getElementById("signUpModal");
const loginForm = document.getElementById("loginForm");
const mainCon = document.getElementById("mainCon");

document.addEventListener("click", (e) => {
    const loginBtn = e.target.closest("[data-login]");
    const signupBtn = e.target.closest("[data-signup]");

    if (loginBtn || signupBtn) {
        e.preventDefault();
        loginModal?.classList.toggle("show", !!loginBtn);
        signUpModal?.classList.toggle("show", !!signupBtn);
        header?.classList.add("modal-open");
        mainCon?.classList.add("show");
        return;
    }

    if (!e.target.closest(".login-form, .signup-form")) {
        loginModal?.classList.remove("show");
        signUpModal?.classList.remove("show");
        header?.classList.remove("modal-open");
        mainCon?.classList.remove("show");
    }
});
//==================================================Admin======================================================

const sideBar = document.getElementById("sideBar");
const menuBar = document.getElementById("menuBar");

if (sideBar && menuBar) {
    menuBar.addEventListener("click", (e) => {
        e.preventDefault();
        sideBar.classList.toggle("appear");
    });

    document.addEventListener("click", (e) => {
        if (!e.target.closest("#sideBar, #menuBar")) {
            sideBar.classList.remove("appear");
        }
    });
}

const sideBarLinks = document.querySelectorAll(".sidebar-link");

sideBarLinks.forEach((sideBarLink) => {
    sideBarLink.addEventListener("click", (e) => {

        sideBarLinks.forEach((link) => link.classList.remove("active"));
        sideBarLink.classList.add("active");
    });
});


//delete part
const deleteCon = document.getElementById("deleteCon");
const adminLayout = document.getElementById("adminLayout");
const cancelDel = document.getElementById("cancelDel");
const confirmDel = document.getElementById("confirmDel");

document.addEventListener("click", (e) => {
    const trigger = e.target.closest(".deleteAcc");
    if (trigger) {
        e.preventDefault();
        const deleteUrl = trigger.getAttribute("data-delete-url");
        if (!deleteUrl) return; // safety: link has no destination yet

        confirmDel.setAttribute("href", deleteUrl);
        deleteCon.classList.add("appear");
        adminLayout?.classList.add("appear");
    }
});

cancelDel?.addEventListener("click", (e) => {
    e.preventDefault();
    deleteCon.classList.remove("appear");
    adminLayout?.classList.remove("appear");
});

window.addEventListener("click", (e) => {
    if (
        deleteCon.classList.contains("appear") &&
        !deleteCon.contains(e.target) &&
        !e.target.closest(".deleteAcc")
    ) {
        deleteCon.classList.remove("appear");
        adminLayout?.classList.remove("appear");
    }
});

//====================================================Copy email to clipboard=========================================================
const copyButtons = document.querySelectorAll(".copy-email");

copyButtons.forEach((link) => {
    link.addEventListener("click", (e) => {
        e.preventDefault();

        const email = link.dataset.email;

        navigator.clipboard.writeText(email)
            .then(() => {
                link.innerHTML = "<i class='bx bx-check'></i> Copied!";

                setTimeout(() => {
                    link.innerHTML = "<i class='bx bx-copy'></i> Copy";
                }, 1500);
            })
            .catch((error) => {
                console.error("Failed to copy email:", error);
            });
    });
});

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

//=====================================================================Recommended carousel buttons====================================================
const recTrack = document.getElementById('rec-track');
const recPrev = document.getElementById('rec-prev');
const recNext = document.getElementById('rec-next');

if (recTrack && recPrev && recNext) {
    recPrev.addEventListener('click', () => recTrack.scrollBy({ left: -300, behavior: 'smooth' }));
    recNext.addEventListener('click', () => recTrack.scrollBy({ left: 300, behavior: 'smooth' }));
}

//=====================================================================Nearby workshops carousel (passive, geolocation-driven)=========================
const nearbySection = document.getElementById('nearby-section');
const nearbyTrack = document.getElementById('nearby-track');
const nearbyPrev = document.getElementById('nearby-prev');
const nearbyNext = document.getElementById('nearby-next');

if (nearbySection && nearbyTrack && navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
        (pos) => {
            fetch(`/workshops/nearby?lat=${pos.coords.latitude}&lng=${pos.coords.longitude}`)
                .then(res => res.json())
                .then(data => {
                    if (!data.length) return;

                    nearbySection.style.display = 'block';
                    nearbyTrack.innerHTML = data.map(w => `
                        <a href="/workshops/${w.w_id}" class="carousel-card">
                            <div class="carousel-card-img">
                                ${w.photo_url
                                    ? `<img src="/static/${w.photo_url}" alt="${w.name}">`
                                    : `<div class="carousel-card-img-placeholder"><i class='bx bx-store'></i></div>`}
                            </div>
                            <div class="carousel-card-body">
                                <h3>${w.name}</h3>
                                <p class="carousel-card-address"><i class='bx bx-map'></i> ${w.distance_km} km away</p>
                                <div class="carousel-card-tags">
                                    ${w.service_names.slice(0, 3).map(s => `<span class="service-tag">${s}</span>`).join('')}
                                </div>
                            </div>
                        </a>
                    `).join('');
                })
                .catch(() => { /* fail silently — section just stays hidden */ });
        },
        () => { /* permission denied — section stays hidden, no error shown */ }
    );

    if (nearbyPrev && nearbyNext) {
        nearbyPrev.addEventListener('click', () => nearbyTrack.scrollBy({ left: -300, behavior: 'smooth' }));
        nearbyNext.addEventListener('click', () => nearbyTrack.scrollBy({ left: 300, behavior: 'smooth' }));
    }
}