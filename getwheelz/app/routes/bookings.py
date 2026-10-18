import logging
from datetime import datetime, timedelta
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    abort,
)
from app.db import get_db_connection
from app.utils import role_required
from app.payments import (
    BANKS,
    amount_due,
    money,
    new_reference,
    parse_bill_input,
    process_demo_payment,
    validate_bank,
    validate_card,
    validate_upi,
)

bookings_bp = Blueprint("bookings", __name__)


@bookings_bp.route("/new/<int:w_id>", methods=["GET", "POST"])
@role_required("customer")
def new(w_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT w_id, name, address FROM workshop WHERE w_id = %s", (w_id,)
            )
            workshop = cur.fetchone()
            if workshop is None:
                abort(404)

            cur.execute(
                """
                SELECT s.s_id, sc.s_name, s.price_range, s.duration
                FROM service s
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE s.w_id = %s
            """,
                (w_id,),
            )
            services = cur.fetchall()

            selected_service = request.args.get("s_id", type=int)
            time_value = ""

            if request.method == "POST":
                selected_service = request.form.get("s_id", type=int)
                time_value = request.form.get("requested_time", "").strip()

                valid_ids = {s["s_id"] for s in services}
                error = None
                requested_time = None

                if selected_service not in valid_ids:
                    error = "Please choose a valid service for this workshop."
                else:
                    try:
                        requested_time = datetime.fromisoformat(time_value)
                    except ValueError:
                        error = "Please enter a valid date and time."

                if not error:
                    now = datetime.now()
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
                    cur.execute(
                        """
                        INSERT INTO booking (c_id, w_id, s_id, requested_time, status)
                        VALUES (%s, %s, %s, %s, 'pending')
                        RETURNING b_id
                    """,
                        (customer["c_id"], w_id, selected_service, requested_time),
                    )
                    b_id = cur.fetchone()["b_id"]
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
        time_value=time_value,
        min_time=datetime.now().strftime("%Y-%m-%dT%H:%M"),
    )


@bookings_bp.route("/confirmation/<int:b_id>")
@role_required("customer")
def confirmation(b_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, w.address, sc.s_name
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
               mu.name AS mechanic_name, b.amount, s.price_range,
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
    bookings = cur.fetchall()

    for b in bookings:
        due, source = amount_due(b["amount"], b["price_range"])
        b["due_label"] = money(due)  # '' when the workshop has not billed yet
        b["due_is_estimate"] = source == "estimate"
        b["paid_label"] = money(b["paid_amount"]) if b["paid_reference"] else ""

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


@bookings_bp.route("/<int:b_id>/pay", methods=["GET", "POST"])
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
            if booking["status"] not in ("confirmed", "completed"):
                flash(
                    "You can pay once the workshop has confirmed your booking.", "error"
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

            approved, message = process_demo_payment(method, cleaned)
            if not approved:
                return _checkout_page(booking, due, source, form, {}, message, 400)

            try:
                cur.execute(
                    """
                    INSERT INTO payment (b_id, amount, method, detail, reference, paid_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (b_id) DO NOTHING
                    RETURNING p_id
                """,
                    (
                        b_id,
                        due,
                        method,
                        cleaned["detail"],
                        new_reference(),
                        datetime.now(),
                    ),
                )
                inserted = cur.fetchone()
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
                "Payment successful." if inserted else "This booking was already paid.",
                "success",
            )
            return redirect(url_for("bookings.receipt", b_id=b_id))
    finally:
        conn.close()


@bookings_bp.route("/<int:b_id>/receipt")
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


@bookings_bp.route("/<int:b_id>/bill", methods=["POST"])
@role_required("owner")
def set_bill(b_id):
    """The workshop owner sets (or clears) the bill for a confirmed/completed booking that is not paid yet."""
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
                  AND status IN ('confirmed', 'completed')
                  AND w_id = (SELECT w.w_id FROM workshop w
                              JOIN owner o ON w.o_id = o.o_id WHERE o.u_id = %s)
                  AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)
            """,
                (amount, b_id, session["user_id"]),
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
            "The bill can't be changed: the booking isn't confirmed yet, or it has already been paid.",
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


@bookings_bp.route("/cancel/<int:b_id>", methods=["POST"])
@role_required("customer")
def cancel(b_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE booking SET status = 'cancelled'
                WHERE b_id = %s
                AND status IN ('pending', 'confirmed')
                AND c_id = (SELECT c_id FROM customer WHERE u_id = %s)
                AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)
            """,
                (b_id, session["user_id"]),
            )
            changed = cur.rowcount
            paid = False
            if not changed:
                cur.execute("SELECT 1 FROM payment WHERE b_id = %s", (b_id,))
                paid = cur.fetchone() is not None
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if changed:
        flash("Booking cancelled.", "success")
    elif paid:
        flash(
            "This booking has already been paid, so it can no longer be cancelled.",
            "error",
        )
    else:
        flash("Booking not found or can no longer be cancelled.", "error")
    return redirect(url_for("bookings.my_bookings"))
