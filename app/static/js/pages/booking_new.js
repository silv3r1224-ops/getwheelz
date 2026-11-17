/* ==================================================================
   booking_new.js — extracted from app/templates/bookings/new.html (inline <script>).
   Pure DOM logic; data comes from the page markup (and inline Jinja
   scripts that run just before this one).
   ================================================================== */

    (function () {
        const form = document.getElementById('booking-form');
        if (!form) return;
        const radios = form.querySelectorAll('input[name="s_id"]');
        const when = document.getElementById('requested_time');
        const vehicleRadios = form.querySelectorAll('input[name="vehicle_type"][type="radio"]');
        const vehicleHidden = form.querySelector('input[name="vehicle_type"][type="hidden"]');
        const description = document.getElementById('vehicle_description');
        const out = {
            vehicle: document.getElementById('sum-vehicle'),
            service: document.getElementById('sum-service'),
            price: document.getElementById('sum-price'),
            duration: document.getElementById('sum-duration'),
            when: document.getElementById('sum-when')
        };

        function pad(n) { return String(n).padStart(2, '0'); }
        function toLocalInput(d) {
            return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
        }

        // Only services that match the chosen vehicle type can be picked. Hidden ones are also
        // disabled so the browser skips them; the server checks the match again on submit.
        function currentVehicle() {
            const picked = form.querySelector('input[name="vehicle_type"]:checked');
            if (picked) return picked.value;
            return vehicleHidden ? vehicleHidden.value : '';
        }
        function filterServices() {
            const type = currentVehicle();
            form.querySelectorAll('.px-choice[data-vehicle]').forEach((label) => {
                const show = !type || label.dataset.vehicle === type;
                const input = label.querySelector('input');
                label.hidden = !show;
                input.disabled = !show;
                if (!show && input.checked) input.checked = false;
            });
        }

        function refresh() {
            const chosen = form.querySelector('input[name="s_id"]:checked');
            const typeInput = form.querySelector('input[name="vehicle_type"]:checked') || vehicleHidden;
            const typeLabel = typeInput && typeInput.value === 'two_wheeler' ? 'Two-wheeler' : (typeInput && typeInput.value ? 'Four-wheeler' : '');
            out.vehicle.textContent = description && description.value.trim()
                ? (typeLabel ? typeLabel + ': ' : '') + description.value.trim()
                : 'Not described yet';
            out.service.textContent = chosen ? chosen.dataset.name : 'Not chosen yet';
            out.price.textContent = (chosen && chosen.dataset.price) || '—';
            out.duration.textContent = (chosen && chosen.dataset.duration) || '—';
            if (when.value) {
                const d = new Date(when.value);
                out.when.textContent = isNaN(d) ? 'Not chosen yet' :
                    d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }) + ', ' +
                    d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
            } else {
                out.when.textContent = 'Not chosen yet';
            }
        }

        radios.forEach((r) => r.addEventListener('change', refresh));
        vehicleRadios.forEach((r) => r.addEventListener('change', () => { filterServices(); refresh(); }));
        if (description) description.addEventListener('input', refresh);
        when.addEventListener('input', refresh);
        when.addEventListener('change', refresh);

        form.querySelectorAll('.px-quick button').forEach((btn) => {
            btn.addEventListener('click', () => {
                const d = new Date();
                d.setDate(d.getDate() + Number(btn.dataset.days));
                d.setHours(10, 0, 0, 0);
                when.value = toLocalInput(d);
                refresh();
            });
        });

        filterServices();
        refresh();
    })();
