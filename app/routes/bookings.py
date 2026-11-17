import logging
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import booking_events, crypto, vehicles
from app import booking_rules as rules
from app.db import get_db_connection
from app.workshop_hours import open_now
from app.payments import (
    BANKS,
    ChargeRequest,
    amount_due,
    get_gateway,
    money,
    parse_bill_input,
    validate_bank,
    validate_card,
    validate_upi,
)
from app.utils import role_required

bookings_bp = Blueprint("bookings", __name__)


@bookings_bp.route("/new/<sealed(workshop):w_id>", methods=["GET", "POST"])
@role_required("customer")
def new(w_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT w_id, name, address, is_open, serves_cars, serves_two_wheelers "
                "FROM workshop WHERE w_id = %s AND status = 'approved'",
                (w_id,),
            )
            workshop = cur.fetchone()
            if workshop is None:
                abort(404)

            # the "closed" gate uses the effective status (manual switch AND today's schedule)
            cur.execute(
                "SELECT dow, open_time, close_time FROM workshop_hours WHERE workshop_id = %s",
                (workshop["w_id"],),
            )
            hours_map = {r["dow"]: (r["open_time"], r["close_time"]) for r in cur.fetchall()}
            workshop["is_open"] = open_now(workshop["is_open"], hours_map)

            cur.execute(
                """
                SELECT s.s_id, sc.s_name, sc.vehicle_type, s.price_range, s.duration
                FROM service s
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE s.w_id = %s
            """,
                (w_id,),
            )
            services = cur.fetchall()

            # No saved vehicle profiles: every booking says what is being brought in (spec section 5).
            served_types = vehicles.workshop_types(workshop["serves_cars"], workshop["serves_two_wheelers"])
            service_types = {s["s_id"]: s["vehicle_type"] for s in services}
            only_type = served_types[0] if len(served_types) == 1 else None

            selected_service = crypto.open_("service", request.args.get("s_id", ""))
            time_value = ""
            description_value = ""
            vehicle_type = None

            if request.method == "GET":
                # start from the service they clicked, else the type they picked while browsing
                vehicle_type = service_types.get(selected_service) or vehicles.chosen_vehicle()
                if vehicle_type not in served_types:
                    vehicle_type = only_type

            if request.method == "POST":
                selected_service = request.form.get("s_id", type=int)
                time_value = request.form.get("requested_time", "").strip()
                description_value = request.form.get("vehicle_description", "")
                vehicle_type = vehicles.normalize(request.form.get("vehicle_type")) or only_type

                valid_ids = {s["s_id"] for s in services}
                error = None
                requested_time = None
                description = ""

                if vehicle_type is None:
                    error = "Please choose whether you are bringing a four-wheeler or a two-wheeler."
                elif vehicle_type not in served_types:
                    error = f"This workshop does not serve {vehicles.PLURAL_LABELS[vehicle_type].lower()}."
                elif selected_service not in valid_ids:
                    error = "Please choose a valid service for this workshop."
                elif service_types[selected_service] != vehicle_type:
                    error = (
                        f"That service is for {vehicles.PLURAL_LABELS[service_types[selected_service]].lower()}. "
                        "Please choose a service that matches your vehicle."
                    )
                else:
                    description, error = vehicles.clean_description(description_value)
                    if not error:
                        try:
                            requested_time = datetime.fromisoformat(time_value)
                        except ValueError:
                            error = "Please enter a valid date and time."

                if not error:
                    now = rules.now()  # the app clock, so tests can fake the time
                    if requested_time <= now:
                        error = "Please choose a time in the future."
                    elif requested_time > now + timedelta(days=365):
                        error = "Bookings can be made up to one year ahead."

                if not error:
                    cur.execute(
                        "SELECT c_id FROM customer WHERE u_id = %s",
                        (session["user_id"],),
                    )
                    customer = cur.fetchone()
                    if customer is None:
                        error = "Customer account not found."

                if error:
                    flash(error, "error")
                else:
                    # created_at comes from the app clock (not the database's) because the 48-hour
                    # answer window is measured against it (app/booking_rules.py).
                    cur.execute(
                        """
                        INSERT INTO booking (c_id, w_id, s_id, requested_time, status,
                                             vehicle_type, vehicle_description, created_at)
                        VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s)
                        RETURNING b_id
                    """,
                        (
                            customer["c_id"],
                            w_id,
                            selected_service,
                            requested_time,
                            vehicle_type,
                            description,
                            rules.now(),
                        ),
                    )
                    b_id = cur.fetchone()["b_id"]
                    # the owner is told in the same transaction: no request without a notice
                    booking_events.announce(cur, b_id, "requested", actor_u_id=session["user_id"])
                    conn.commit()
                    flash("Booking request sent.", "success")
                    return redirect(url_for("bookings.confirmation", b_id=b_id))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return render_template(
        "bookings/new.html",
        workshop=workshop,
        services=services,
        preselected_service=selected_service,
        served_types=served_types,
        booking_vehicle=vehicle_type,
        vehicle_description=description_value,
        time_value=time_value,
        min_time=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@bookings_bp.route("/confirmation/<sealed(booking):b_id>")
@role_required("customer")
def confirmation(b_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, w.address, sc.s_name,
               b.vehicle_type, b.vehicle_description
        FROM booking b
        JOIN workshop w ON b.w_id = w.w_id
        JOIN service s ON b.s_id = s.s_id
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        JOIN customer c ON b.c_id = c.c_id
        WHERE b.b_id = %s AND c.u_id = %s
    """,
        (b_id, session["user_id"]),
    )
    booking = cur.fetchone()
    cur.close()
    conn.close()

    if booking is None:
        abort(404)

    return render_template("bookings/confirmation.html", booking=booking)


@bookings_bp.route("/my-bookings")
@role_required("customer")
def my_bookings():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
    customer = cur.fetchone()

    cur.execute(
        """
        SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, w.w_id, sc.s_name,
        mu.name AS mechanic_name, b.amount, s.price_range, b.vehicle_type, b.vehicle_description,
        b.created_at, b.cancelled_by, b.cancel_request_status, b.cancel_request_reason,
        EXISTS (SELECT 1 FROM review r WHERE r.b_id = b.b_id) AS reviewed,
        p.reference AS paid_reference, p.amount AS paid_amount
        FROM booking b
        JOIN workshop w ON b.w_id = w.w_id
        JOIN service s ON b.s_id = s.s_id
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        LEFT JOIN mechanic bm ON b.assigned_m_id = bm.m_id
        LEFT JOIN users mu ON bm.u_id = mu.u_id
        LEFT JOIN payment p ON p.b_id = b.b_id
        WHERE b.c_id = %s
        ORDER BY b.requested_time DESC
    """,
        (customer["c_id"],),
    )
    # DictCursor rows can't take new keys, so work on plain dict copies
    bookings = [dict(b) for b in cur.fetchall()]

    now = rules.now()
    for b in bookings:
        due, source = amount_due(b["amount"], b["price_range"])
        b["due_label"] = money(due)  # "" when the workshop has not billed yet
        b["due_is_estimate"] = source == "estimate"
        b["paid_label"] = money(b["paid_amount"]) if b["paid_reference"] else ""
        is_paid = bool(b["paid_reference"])
        # nothing is paid upfront: only a COMPLETED, unpaid booking shows under "To pay"
        b["to_pay"] = rules.can_pay(b["status"], is_paid)
        b["status_label"] = rules.label(b["status"])
        # what the customer can do about cancelling: cancel now, send a request, or nothing
        b["cancel_mode"] = rules.customer_cancel_mode(
            b["status"], b["cancel_request_status"], is_paid
        )
        # pending requests show how long the workshop has left to answer
        b["hours_left"] = (
            rules.hours_left(b["created_at"], now) if b["status"] == rules.PENDING else None
        )

    # Upcoming appointments first (soonest at the top), then history newest-first.
    upcoming = sorted(
        (b for b in bookings if b["status"] in rules.OPEN_STATUSES),
        key=lambda b: b["requested_time"],
    )
    history = [b for b in bookings if b["status"] not in rules.OPEN_STATUSES]
    bookings = upcoming + history

    cur.close()
    conn.close()

    return render_template("bookings/my_bookings.html", bookings=bookings)


# ----------------------------------------------------------------------------------------------
# DEMO payments: no real money moves. The full card number and CVV are checked and then discarded.
# ----------------------------------------------------------------------------------------------
_BOOKING_FOR_PAYMENT = """
    SELECT b.b_id, b.requested_time, b.status, b.amount, s.price_range,
           w.name AS workshop_name, w.address, sc.s_name, mu.name AS mechanic_name,
           p.reference, p.amount AS paid_amount, p.method AS paid_method,
           p.detail AS paid_detail, p.paid_at
    FROM booking b
    JOIN customer c ON b.c_id = c.c_id
    JOIN workshop w ON b.w_id = w.w_id
    JOIN service s ON b.s_id = s.s_id
    JOIN service_catalog sc ON sc.sc_id = s.sc_id
    LEFT JOIN mechanic bm ON b.assigned_m_id = bm.m_id
    LEFT JOIN users mu ON bm.u_id = mu.u_id
    LEFT JOIN payment p ON p.b_id = b.b_id
    WHERE b.b_id = %s AND c.u_id = %s
"""


def _checkout_page(
    booking, due, source, form=None, errors=None, message=None, status=200
):
    return (
        render_template(
            "bookings/checkout.html",
            booking=booking,
            due_label=money(due),
            is_estimate=(source == "estimate"),
            expected_amount=f"{due:.2f}",
            banks=BANKS,
            form=form or {"method": "card"},
            errors=errors or {},
            message=message,
        ),
        status,
    )


@bookings_bp.route("/<sealed(booking):b_id>/pay", methods=["GET", "POST"])
@role_required("customer")
def pay(b_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_BOOKING_FOR_PAYMENT, (b_id, session["user_id"]))
            booking = cur.fetchone()
            if not booking:
                abort(404)

            if booking["reference"]:
                flash("This booking is already paid.", "success")
                return redirect(url_for("bookings.receipt", b_id=b_id))
            if booking["status"] not in rules.PAYABLE_STATUSES:
                flash(
                    "Nothing is paid upfront. You can pay once the job is completed.",
                    "error",
                )
                return redirect(url_for("bookings.my_bookings"))

            # the amount always comes from the database, never from the browser
            due, source = amount_due(booking["amount"], booking["price_range"])
            if due is None:
                flash(
                    "The workshop hasn't set the bill yet. Please check back soon.",
                    "error",
                )
                return redirect(url_for("bookings.my_bookings"))

            if request.method == "GET":
                return _checkout_page(booking, due, source)

            method = request.form.get("method", "")
            form = {
                "method": method,
                "name": " ".join(request.form.get("name", "").split()),
                "expiry": request.form.get("expiry", "").strip(),
                "upi": request.form.get("upi", "").strip(),
                "bank": request.form.get("bank", ""),
            }  # the card number and CVV are deliberately NOT sent back to the page
            errors, cleaned, message = {}, {}, None

            if request.form.get("expected_amount") != f"{due:.2f}":
                message = "The amount for this booking has changed. Please review it and try again."
            elif method == "card":
                errors, cleaned = validate_card(
                    form["name"],
                    request.form.get("number", ""),
                    form["expiry"],
                    request.form.get("cvv", ""),
                )
            elif method == "upi":
                errors, cleaned = validate_upi(form["upi"])
            elif method == "netbanking":
                errors, cleaned = validate_bank(form["bank"])
            else:
                message = "Please choose a payment method."

            if message or errors:
                return _checkout_page(booking, due, source, form, errors, message, 400)

            # The gateway (app/payments.py) takes the payment. Today that is the demo gateway; a
            # real provider replaces it without changing this route.
            result = get_gateway().charge(
                ChargeRequest(booking_id=b_id, amount=due, method=method, cleaned=cleaned)
            )
            if not result.ok:
                return _checkout_page(booking, due, source, form, {}, result.message, 400)

            try:
                paid_at = rules.now()
                cur.execute(
                    """
                    INSERT INTO payment (b_id, amount, method, detail, reference, paid_at, provider)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (b_id) DO NOTHING
                    RETURNING p_id
                """,
                    (
                        b_id,
                        due,
                        method,
                        result.detail or cleaned.get("detail"),
                        result.reference,
                        paid_at,
                        result.provider,
                    ),
                )
                inserted = cur.fetchone()
                if inserted:
                    # record the payment status on the booking and tell the workshop, in the same
                    # transaction as the payment itself
                    cur.execute(
                        "UPDATE booking SET payment_status = 'paid' WHERE b_id = %s", (b_id,)
                    )
                    booking_events.announce(
                        cur,
                        b_id,
                        "paid",
                        actor_u_id=session["user_id"],
                        extra={"amount_label": money(due)},
                        at=paid_at,
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                logging.exception("Demo payment could not be saved")
                return _checkout_page(
                    booking,
                    due,
                    source,
                    form,
                    {},
                    "Something went wrong. You have not been charged. Please try again.",
                    500,
                )

            flash(
                (
                    "Payment successful."
                    if inserted
                    else "This booking was already paid."
                ),
                "success",
            )
            return redirect(url_for("bookings.receipt", b_id=b_id))
    finally:
        conn.close()


@bookings_bp.route("/<sealed(booking):b_id>/receipt")
@role_required("customer")
def receipt(b_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_BOOKING_FOR_PAYMENT, (b_id, session["user_id"]))
            booking = cur.fetchone()
    finally:
        conn.close()

    if not booking:
        abort(404)
    if not booking["reference"]:
        flash("There is no payment for this booking yet.", "error")
        return redirect(url_for("bookings.my_bookings"))
    return render_template(
        "bookings/receipt.html",
        booking=booking,
        paid_label=money(booking["paid_amount"]),
    )


@bookings_bp.route("/<sealed(booking):b_id>/bill", methods=["POST"])
@role_required("owner")
def set_bill(b_id):
    """The workshop owner sets (or clears) the bill for an accepted, in-progress or completed booking that is not paid yet."""
    amount, error = parse_bill_input(request.form.get("amount"))
    back = url_for("dashboard.owner") + "#bookings"
    if error:
        flash(error, "error")
        return redirect(back)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE booking SET amount = %s
                WHERE b_id = %s
                  AND status = ANY(%s)
                  AND w_id = (SELECT w.w_id FROM workshop w
                              JOIN owner o ON w.o_id = o.o_id WHERE o.u_id = %s)
                  AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)
            """,
                (amount, b_id, list(rules.BILLABLE_STATUSES), session["user_id"]),
            )
            changed = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not changed:
        flash(
            "The bill can't be changed: the booking isn't accepted yet, it was cancelled, or it has already been paid.",
            "error",
        )
    elif amount is None:
        flash(
            "Bill cleared. The customer will see an estimate from your listed price.",
            "success",
        )
    else:
        flash(f"Bill set to {money(amount)}.", "success")
    return redirect(back)


@bookings_bp.route("/cancel/<sealed(booking):b_id>", methods=["POST"])
@role_required("customer")
def cancel(b_id):
    """Free cancellation, but only until the owner accepts (spec section 6).

    After acceptance the customer sends a cancellation request instead (request_cancel below).
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            at = rules.now()
            changed = booking_events.change_status(
                cur,
                b_id,
                rules.CANCELLED,
                (rules.PENDING,),
                scope_sql="""AND c_id = (SELECT c_id FROM customer WHERE u_id = %s)
                             AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)""",
                scope_params=(session["user_id"],),
                sets=[("cancelled_by = %s", rules.BY_CUSTOMER), ("cancelled_at = %s", at)],
            )
            current = None
            if changed:
                booking_events.announce(
                    cur, b_id, "customer_cancelled", actor_u_id=session["user_id"], at=at
                )
            else:
                cur.execute(
                    """
                    SELECT b.status, EXISTS (SELECT 1 FROM payment p WHERE p.b_id = b.b_id) AS paid
                    FROM booking b
                    WHERE b.b_id = %s AND b.c_id = (SELECT c_id FROM customer WHERE u_id = %s)
                    """,
                    (b_id, session["user_id"]),
                )
                current = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if changed:
        flash("Booking cancelled.", "success")
    elif current and current["paid"]:
        flash(
            "This booking has already been paid, so it can no longer be cancelled.",
            "error",
        )
    elif current and current["status"] in rules.ACCEPTED_STATUSES:
        flash(
            "The workshop has already accepted this booking, so it can't be cancelled "
            "directly. Send a cancellation request instead.",
            "error",
        )
    else:
        flash("Booking not found or can no longer be cancelled.", "error")
    return redirect(url_for("bookings.my_bookings"))


@bookings_bp.route("/request-cancel/<sealed(booking):b_id>", methods=["POST"])
@role_required("customer")
def request_cancel(b_id):
    """After acceptance the customer can only ask to cancel; the owner approves or declines."""
    reason, error = rules.clean_cancel_reason(request.form.get("reason"))
    if error:
        flash(error, "error")
        return redirect(url_for("bookings.my_bookings"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            at = rules.now()
            cur.execute(
                """
                UPDATE booking
                SET cancel_request_status = 'requested', cancel_requested_at = %s,
                    cancel_request_reason = %s
                WHERE b_id = %s
                  AND status = ANY(%s)
                  AND cancel_request_status IS NULL
                  AND c_id = (SELECT c_id FROM customer WHERE u_id = %s)
                  AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)
                """,
                (at, reason, b_id, list(rules.ACCEPTED_STATUSES), session["user_id"]),
            )
            changed = cur.rowcount > 0
            if changed:
                booking_events.announce(
                    cur,
                    b_id,
                    "cancel_requested",
                    actor_u_id=session["user_id"],
                    extra={"reason": reason},
                    at=at,
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if changed:
        flash("Cancellation request sent. The workshop will approve or decline it.", "success")
    else:
        flash(
            "A cancellation request can only be sent once, for an accepted booking that "
            "is not finished or paid.",
            "error",
        )
    return redirect(url_for("bookings.my_bookings"))
