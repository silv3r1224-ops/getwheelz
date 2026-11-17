import logging
import os
import re
from decimal import Decimal

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from app import analytics, appeals, booking_events, contact, legal, vehicles
from app.routes.legal import accepted_pairs, record_consent, remember_consent
from app import booking_rules as rules
from app.db import get_db_connection
from app.payments import amount_due, money
from app.routes.dashboard import dashboard_bp
from app.utils import UPLOAD_FOLDER, decode_uid, role_required, save_upload_image


def _back_to(default_endpoint, anchor=""):
    """Where an owner action returns to: the inbox when it was taken from an inbox popup
    (the form sends next=inbox), otherwise the dashboard. Only these two places are possible, so
    the value cannot be used to redirect anywhere else."""
    if request.form.get("next") == "inbox":
        return redirect(url_for("main.inbox") + "#panelUpdates")
    return redirect(url_for(default_endpoint) + anchor)


# =================================================OWNER DASHBOARD=================================================#
@dashboard_bp.route("/owner")
@role_required("owner")
def owner():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session["user_id"],))
    owner_row = cur.fetchone()
    if not owner_row:
        cur.close()
        conn.close()
        abort(403)

    cur.execute(
        "SELECT w_id, name, address, contact_no, whatsapp_no, latitude, longitude, photo_path, capacity, is_open, status, rejection_reason, serves_cars, serves_two_wheelers FROM workshop WHERE o_id = %s",
        (owner_row["o_id"],),
    )
    workshop = cur.fetchone()

    # opening hours: one open/close pair, applied to every day. If a schedule exists,
    # the dashboard pre-fills the single pair from any day that has one.
    hours_pair = None
    if workshop:
        cur.execute(
            "SELECT dow, open_time, close_time FROM workshop_hours WHERE workshop_id = %s ORDER BY dow",
            (workshop["w_id"],),
        )
        hours = {r["dow"]: (r["open_time"], r["close_time"]) for r in cur.fetchall()}
        hours_pair = next((v for v in hours.values() if v[0] is not None), None)

    bookings = []
    booking_summary = None
    services = []
    mechanics = []
    stats = {
        "total_bookings": 0,
        "pending_bookings": 0,
        "total_services": 0,
        "total_mechanics": 0,
        "capacity": 0,
    }
    service_catalog = []

    # Only offer catalog entries of the vehicle types this workshop serves (spec section 5):
    # a two-wheeler-only workshop sees just the two-wheeler catalog, and so on.
    cur.execute("SELECT sc_id, s_name, vehicle_type FROM service_catalog ORDER BY s_name")
    service_catalog = [
        c
        for c in cur.fetchall()
        if workshop
        and vehicles.service_allowed(
            workshop["serves_cars"], workshop["serves_two_wheelers"], c["vehicle_type"]
        )
    ]

    if workshop:
        cur.execute(
            """
            SELECT b.b_id, b.requested_time, b.status,
                   (SELECT public_booking_customer_name(b.b_id)) AS customer_name, sc.s_name,
            b.assigned_m_id, mu.name AS mechanic_name, b.amount, s.price_range,
            b.vehicle_type, b.vehicle_description,
            b.created_at, b.cancelled_by, b.cancel_request_status, b.cancel_request_reason,
            pay.amount AS paid_amount, pay.method AS paid_method, pay.detail AS paid_detail,
            pay.paid_at AS paid_at
            FROM booking b
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            LEFT JOIN mechanic bm ON b.assigned_m_id = bm.m_id
            LEFT JOIN users mu ON bm.u_id = mu.u_id
            LEFT JOIN payment pay ON pay.b_id = b.b_id
            WHERE b.w_id = %s
            ORDER BY b.requested_time DESC
        """,
            (workshop["w_id"],),
        )
        # DictCursor rows can't take new keys, so work on plain dict copies
        bookings = [dict(b) for b in cur.fetchall()]

        # what the customer will pay (the bill if set, else an estimate), and payment status.
        # Everything the bookings table filters/sorts on is worked out here, once, on the server
        # (so "today" and "this month" follow the server's clock, not the browser's).
        now = rules.now()
        today = now.date()
        this_week = today.isocalendar()[:2]
        collected_month = Decimal(0)
        awaiting = Decimal(0)
        awaiting_count = 0
        booking_counts = dict.fromkeys(
            ("all", "active", "pending", "unpaid", "paid", "history"), 0
        )

        for b in bookings:
            due, source = amount_due(b["amount"], b["price_range"])
            b["due"] = due
            b["due_label"] = money(due)
            b["due_is_estimate"] = source == "estimate"
            b["bill_value"] = f"{b['amount']:.2f}" if b["amount"] is not None else ""
            b["is_paid"] = b["paid_amount"] is not None
            b["paid_label"] = money(b["paid_amount"])

            day = b["requested_time"].date()
            periods = []
            if day == today:
                periods.append("today")
            if day.isocalendar()[:2] == this_week:
                periods.append("week")
            if (day.year, day.month) == (today.year, today.month):
                periods.append("month")
            b["periods"] = " ".join(periods)
            b["is_today"] = day == today
            b["ts"] = int(b["requested_time"].timestamp())
            # nothing is paid upfront: a booking awaits payment only once it is COMPLETED
            b["is_unpaid"] = (not b["is_paid"]) and b["status"] in rules.PAYABLE_STATUSES
            b["status_label"] = rules.label(b["status"])
            b["cancel_requested"] = (
                b["cancel_request_status"] == rules.REQUEST_OPEN
                and b["status"] in rules.ACCEPTED_STATUSES
                and not b["is_paid"]
            )
            # needs the owner's answer: a new request, or a customer asking to cancel
            b["needs_action"] = b["status"] == rules.PENDING or b["cancel_requested"]
            b["hours_left"] = (
                rules.hours_left(b["created_at"], now) if b["status"] == rules.PENDING else None
            )

            booking_counts["all"] += 1
            if b["status"] in rules.OPEN_STATUSES:
                booking_counts["active"] += 1
            else:
                booking_counts["history"] += 1
            if b["needs_action"]:
                booking_counts["pending"] += 1
            if b["is_paid"]:
                booking_counts["paid"] += 1
                paid_at = b["paid_at"]
                if paid_at and (paid_at.year, paid_at.month) == (today.year, today.month):
                    collected_month += b["paid_amount"]
            elif b["is_unpaid"]:
                booking_counts["unpaid"] += 1
                if due is not None:
                    awaiting += due
                    awaiting_count += 1

        booking_summary = {
            "collected_month": money(collected_month),
            "awaiting": money(awaiting),
            "awaiting_count": awaiting_count,
            "counts": booking_counts,
        }

        cur.execute(
            """
            SELECT s.s_id, s.sc_id, sc.s_name, sc.vehicle_type, s.price_range, s.duration,
            (SELECT COUNT(*) FROM booking b WHERE b.s_id = s.s_id) AS booking_count
            FROM service s
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE s.w_id = %s
            ORDER BY sc.s_name
        """,
            (workshop["w_id"],),
        )
        services = cur.fetchall()

        cur.execute(
            """
            SELECT m.m_id, u.u_id, u.name, u.email, m.experience_yrs, m.active_stat,
            (m.leave_requested_at IS NOT NULL) AS leave_pending
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = %s
        """,
            (workshop["w_id"],),
        )
        mechanics = cur.fetchall()

        stats["total_bookings"] = len(bookings)
        stats["pending_bookings"] = len([b for b in bookings if b["needs_action"]])
        stats["total_services"] = len(services)
        stats["total_mechanics"] = len(mechanics)
        stats["capacity"] = workshop["capacity"]

    # Phase 6: may this owner still appeal the rejection? (one appeal per rejection; app/appeals.py)
    workshop_can_appeal = workshop_appeal_open = False
    if workshop and workshop["status"] == "rejected":
        cur.execute(
            """
            SELECT w.decided_at,
                   (SELECT MAX(a.created_at) FROM appeal a
                    WHERE a.u_id = %s AND a.kind = 'listing' AND a.w_id = w.w_id) AS last_appeal_at,
                   EXISTS (SELECT 1 FROM appeal a WHERE a.u_id = %s AND a.kind = 'listing'
                           AND a.w_id = w.w_id AND a.status = 'open') AS has_open
            FROM workshop w WHERE w.w_id = %s
            """,
            (session["user_id"], session["user_id"], workshop["w_id"]),
        )
        appeal_state = cur.fetchone()
        workshop_appeal_open = bool(appeal_state and appeal_state["has_open"])
        workshop_can_appeal = bool(
            appeal_state
            and appeals.can_appeal(
                appeal_state["decided_at"], appeal_state["last_appeal_at"], appeal_state["has_open"]
            )
        )

    # Phase 7: analytics for THIS owner's workshop only. The workshop id comes from the owner's own row
    # above, never from the request, and the same rows the bookings table shows feed every figure.
    analytics_data = None
    owner_rating_avg = None
    owner_rating_count = 0
    if workshop:
        cur.execute(
            """
            SELECT r.rating, r.created_at, b.vehicle_type
            FROM review r JOIN booking b ON b.b_id = r.b_id
            WHERE r.w_id = %s
            """,
            (workshop["w_id"],),
        )
        reviews = [dict(x) for x in cur.fetchall()]
        owner_rating_count = len(reviews)
        owner_rating_avg = (
            sum(r["rating"] for r in reviews) / owner_rating_count if owner_rating_count else None
        )
        serves_both = bool(workshop["serves_cars"] and workshop["serves_two_wheelers"])
        analytics_data = analytics.build(
            bookings,
            reviews,
            rules.now().date(),
            analytics.clean_vehicle(
                request.args.get("vehicle"), workshop["serves_cars"], workshop["serves_two_wheelers"]
            ),
            analytics.clean_range(request.args.get("range")),
            serves_both,
        )

    # the create-workshop form asks for the owner agreement unless it is already accepted
    owner_agreement_ok = legal.has_accepted(accepted_pairs(cur, session["user_id"]), legal.DOC_OWNER)

    cur.close()
    conn.close()

    return render_template(
        "dashboard/owner.html",
        owner_agreement_ok=owner_agreement_ok,
        analytics=analytics_data,
        vehicle_labels=analytics.VEHICLE_LABELS,
        range_options=analytics.RANGES,
        workshop_can_appeal=workshop_can_appeal,
        workshop_appeal_open=workshop_appeal_open,
        owner_rating_avg=owner_rating_avg,
        owner_rating_count=owner_rating_count,
        workshop=workshop,
        hours_pair=hours_pair,
        bookings=bookings,
        booking_summary=booking_summary,
        services=services,
        mechanics=mechanics,
        stats=stats,
        service_catalog=service_catalog,
    )

@dashboard_bp.route("/owner/mechanic/<token>")
@role_required("owner")
def mechanic_profile(token):
    """Read-only profile of a mechanic who works in, or has applied to, this owner's workshop."""
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.w_id, w.name, w.capacity,
                       (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size
                FROM workshop w JOIN owner o ON w.o_id = o.o_id
                WHERE o.u_id = %s
            """,
                (session["user_id"],),
            )
            ws = cur.fetchone()
            if not ws:
                abort(403)

            cur.execute(
                """
                SELECT u.u_id, u.name, u.email, u.profile_picture, u.created_at,
                       m.m_id, m.experience_yrs, m.active_stat, m.w_id,
                       (m.leave_requested_at IS NOT NULL) AS leave_pending,
                       (SELECT jr.jr_id FROM join_request jr
                        WHERE jr.m_id = m.m_id AND jr.w_id = %s AND jr.status = 'pending'
                        ORDER BY jr.created_at DESC LIMIT 1) AS jr_id
                FROM mechanic m JOIN users u ON m.u_id = u.u_id
                WHERE u.u_id = %s
            """,
                (ws["w_id"], u_id),
            )
            person = cur.fetchone()

            # only people connected to THIS workshop are viewable
            is_member = bool(person) and person["w_id"] == ws["w_id"]
            is_applicant = (
                bool(person) and person["w_id"] is None and person["jr_id"] is not None
            )
            if not (is_member or is_applicant):
                abort(404)

            jobs = None
            if is_member:
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status IN ('confirmed', 'in_progress')) AS active
                    FROM booking
                    WHERE assigned_m_id = %s AND w_id = %s
                """,
                    (person["m_id"], ws["w_id"]),
                )
                jobs = cur.fetchone()
    finally:
        conn.close()

    return render_template(
        "dashboard/mechanic_profile.html",
        person=person,
        workshop=ws,
        jobs=jobs,
        is_member=is_member,
        is_applicant=is_applicant,
        full=ws["team_size"] >= ws["capacity"],
    )


@dashboard_bp.route("/owner/service/<sealed(service):s_id>/edit", methods=["POST"])
@role_required("owner")
def edit_service(s_id):
    """Update the price range and duration of one of this owner's services."""
    price_range = (request.form.get("price_range") or "").strip()
    duration = (request.form.get("duration") or "").strip()

    # columns are VARCHAR(50)
    if len(price_range) > 50 or len(duration) > 50:
        flash("Price range and duration must be 50 characters or fewer.", "error")
        return redirect(url_for("dashboard.owner") + "#services")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # the service must belong to THIS owner's workshop (checked inside the UPDATE)
            cur.execute(
                """
                UPDATE service SET price_range = %s, duration = %s
                WHERE s_id = %s
                  AND w_id = (
                        SELECT w.w_id FROM workshop w
                        JOIN owner o ON w.o_id = o.o_id
                        WHERE o.u_id = %s
                  )
            """,
                (price_range or None, duration or None, s_id, session["user_id"]),
            )
            changed = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if changed:
        flash("Service updated.", "success")
    else:
        flash("Service not found.", "error")
    return redirect(url_for("dashboard.owner") + "#services")


@dashboard_bp.route("/owner/service/<sealed(service):s_id>/remove", methods=["POST"])
@role_required("owner")
def remove_service(s_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # the service must belong to THIS owner's workshop
    cur.execute(
        """
        SELECT s.s_id FROM service s
        JOIN workshop w ON s.w_id = w.w_id
        JOIN owner o ON w.o_id = o.o_id
        WHERE s.s_id = %s AND o.u_id = %s
    """,
        (s_id, session["user_id"]),
    )

    if not cur.fetchone():
        flash("Service not found.", "error")
    else:
        # never delete a service that customers have booked: it would wipe their booking history
        cur.execute("SELECT 1 FROM booking WHERE s_id = %s LIMIT 1", (s_id,))
        if cur.fetchone():
            flash("This service has bookings, so it can't be removed.", "error")
        else:
            try:
                cur.execute("DELETE FROM service WHERE s_id = %s", (s_id,))
                conn.commit()
                flash("Service removed.", "success")
            except Exception:
                conn.rollback()
                flash("Could not remove this service.", "error")

    cur.close()
    conn.close()
    return redirect(url_for("dashboard.owner"))


@dashboard_bp.route("/owner/leave/<sealed(leave):lr_id>/<action>", methods=["POST"])
@role_required("owner")
def review_leave(lr_id, action):
    if action not in ("approve", "reject"):
        abort(400)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT w.w_id FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """,
        (session["user_id"],),
    )
    ws = cur.fetchone()
    if not ws:
        cur.close()
        conn.close()
        abort(403)

    # the mechanic must work in THIS owner's workshop and have a pending request
    cur.execute(
        """
        SELECT m_id FROM mechanic
        WHERE m_id = %s AND w_id = %s AND leave_requested_at IS NOT NULL
    """,
        (lr_id, ws["w_id"]),
    )
    req = cur.fetchone()

    if not req:
        flash("Leave request not found.", "error")
    elif action == "reject":
        cur.execute(
            """
            UPDATE mechanic
            SET leave_requested_at = NULL, leave_reason = NULL, leave_rejected_at = NOW()
            WHERE m_id = %s
        """,
            (lr_id,),
        )
        conn.commit()
        flash("Leave request declined. The mechanic stays in your workshop.", "success")
    else:
        cur.execute(
            """
            UPDATE mechanic
            SET w_id = NULL, leave_requested_at = NULL, leave_reason = NULL, leave_rejected_at = NULL
            WHERE m_id = %s
        """,
            (lr_id,),
        )
        # jobs not yet finished go back to "needs a mechanic" so the owner can reassign them
        cur.execute(
            """
            UPDATE booking SET assigned_m_id = NULL
            WHERE assigned_m_id = %s AND status IN ('pending', 'confirmed', 'in_progress')
            RETURNING b_id, status, requested_time
        """,
            (lr_id,),
        )
        returned = cur.fetchall()
        if returned:
            # the owner is told which jobs now need a mechanic, in the same transaction (spec section 8)
            lines = "\n".join(
                f"- booking #{r['b_id']} ({rules.label(r['status'])}, "
                f"{r['requested_time'].strftime('%d %b %Y, %I:%M %p')})"
                for r in returned
            )
            booking_events.send_notice(
                cur,
                session["user_id"],
                f"{len(returned)} job{'s' if len(returned) != 1 else ''} need a mechanic again",
                "A mechanic you let go was assigned to these jobs. They are back to "
                f"\"needs a mechanic\" so you can reassign them:\n{lines}",
                rules.now(),
            )
        conn.commit()
        flash(
            "Leave approved. The mechanic has been released from your workshop."
            + (f" {len(returned)} job(s) need a new mechanic." if returned else ""),
            "success",
        )

    cur.close()
    conn.close()
    return redirect(url_for("main.inbox"))


@dashboard_bp.route("/owner/request/<sealed(joinreq):jr_id>/<action>", methods=["POST"])
@role_required("owner")
def review_mechanic(jr_id, action):
    if action not in ("accept", "reject"):
        abort(400)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT w.w_id, w.capacity FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """,
        (session["user_id"],),
    )
    ws = cur.fetchone()
    if not ws:
        cur.close()
        conn.close()
        abort(403)

    # request must belong to THIS owner's workshop and still be pending
    cur.execute(
        """
        SELECT m_id FROM join_request
        WHERE jr_id = %s AND w_id = %s AND status = 'pending'
    """,
        (jr_id, ws["w_id"]),
    )
    req = cur.fetchone()

    if not req:
        flash("Request not found.", "error")
    elif action == "reject":
        cur.execute(
            "UPDATE join_request SET status = 'rejected' WHERE jr_id = %s", (jr_id,)
        )
        conn.commit()
        flash("Request rejected.", "success")
    else:  # action == 'accept'
        cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (ws["w_id"],))
        current = cur.fetchone()["n"]

        if current >= ws["capacity"]:
            flash(
                "Your workshop is full. Increase capacity to accept more mechanics.",
                "error",
            )
        else:
            cur.execute(
                "UPDATE mechanic SET w_id = %s WHERE m_id = %s AND w_id IS NULL",
                (ws["w_id"], req["m_id"]),
            )
            if cur.rowcount:
                cur.execute(
                    "UPDATE join_request SET status = 'accepted' WHERE jr_id = %s",
                    (jr_id,),
                )
                cur.execute(
                    """
                    UPDATE join_request SET status = 'rejected'
                    WHERE m_id = %s AND status = 'pending'
                """,
                    (req["m_id"],),
                )
                flash("Mechanic added to your workshop.", "success")
            else:
                cur.execute(
                    "UPDATE join_request SET status = 'rejected' WHERE jr_id = %s",
                    (jr_id,),
                )
                flash("That mechanic already joined another workshop.", "error")
            conn.commit()

    cur.close()
    conn.close()
    return redirect(url_for("main.inbox"))


@dashboard_bp.route("/owner/booking/<sealed(booking):booking_id>/<action>", methods=["POST"])
@role_required("owner")
def update_booking_status(booking_id, action):
    """Accept, decline, cancel, start or complete a booking of THIS owner's workshop.

    The rules (which status each action may start from) live in app/booking_rules.py. Each change
    is one conditional UPDATE plus the notices it causes, saved in one transaction.
    """
    if action not in rules.OWNER_ACTIONS:
        abort(400)
    new_status, allowed_from = rules.OWNER_ACTIONS[action]

    at = rules.now()
    expire_before, _ = rules.sweep_cutoffs(at)
    # only bookings that belong to THIS owner's workshop
    scope_sql = """AND w_id = (SELECT w.w_id FROM workshop w
                               JOIN owner o ON w.o_id = o.o_id WHERE o.u_id = %s)"""
    scope_params = [session["user_id"]]
    sets = []
    event = {
        "confirm": "accepted",
        "decline": "declined",
        "cancel": "owner_cancelled",
        "start": "started",
        "complete": "completed",
    }[action]

    if action == "confirm":
        # the 48-hour rule holds even if the scheduled sweep has not run yet
        scope_sql += " AND created_at > %s"
        scope_params.append(expire_before)
    if action in ("decline", "cancel"):
        sets = [("cancelled_by = %s", rules.BY_OWNER), ("cancelled_at = %s", at)]
        scope_sql += " AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)"

    expired = False
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            changed = booking_events.change_status(
                cur, booking_id, new_status, allowed_from, scope_sql, scope_params, sets
            )
            if changed:
                booking_events.announce(
                    cur, booking_id, event, actor_u_id=session["user_id"], at=at
                )
            elif action == "confirm":
                # was it too late? then cancel it now, exactly as the sweep would have
                expired = booking_events.change_status(
                    cur,
                    booking_id,
                    rules.CANCELLED,
                    (rules.PENDING,),
                    """AND w_id = (SELECT w.w_id FROM workshop w
                                   JOIN owner o ON w.o_id = o.o_id WHERE o.u_id = %s)
                       AND created_at <= %s""",
                    (session["user_id"], expire_before),
                    [("cancelled_by = %s", rules.BY_SYSTEM), ("cancelled_at = %s", at)],
                )
                if expired:
                    booking_events.announce(cur, booking_id, "auto_cancelled", at=at)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    done = {
        "confirm": "Booking accepted. Assign a mechanic when you are ready.",
        "decline": "Booking declined.",
        "cancel": "Booking cancelled.",
        "start": "Work started on this booking.",
        "complete": "Booking marked completed. The customer can now pay.",
    }
    if changed:
        flash(done[action], "success")
    elif expired:
        flash(
            "This request was not answered within 48 hours, so it has been cancelled "
            "automatically and the customer was told.",
            "error",
        )
    else:
        flash("Booking not found or cannot be changed.", "error")
    return _back_to("dashboard.owner", "#bookings")


@dashboard_bp.route(
    "/owner/booking/<sealed(booking):booking_id>/cancel-request/<decision>", methods=["POST"]
)
@role_required("owner")
def review_cancellation(booking_id, decision):
    """Approve or decline a customer's request to cancel an accepted booking."""
    if decision not in ("approve", "decline"):
        abort(400)
    at = rules.now()
    scope_sql = """AND cancel_request_status = 'requested'
                   AND w_id = (SELECT w.w_id FROM workshop w
                               JOIN owner o ON w.o_id = o.o_id WHERE o.u_id = %s)
                   AND NOT EXISTS (SELECT 1 FROM payment p WHERE p.b_id = booking.b_id)"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if decision == "approve":
                changed = booking_events.change_status(
                    cur,
                    booking_id,
                    rules.CANCELLED,
                    rules.ACCEPTED_STATUSES,
                    scope_sql,
                    (session["user_id"],),
                    [
                        ("cancelled_by = %s", rules.BY_CUSTOMER),
                        ("cancelled_at = %s", at),
                        ("cancel_request_status = %s", rules.REQUEST_APPROVED),
                    ],
                )
                event = "cancel_approved"
            else:
                # the booking keeps its status; only the request is answered
                cur.execute(
                    f"""
                    UPDATE booking SET cancel_request_status = 'declined'
                    WHERE b_id = %s AND status = ANY(%s) {scope_sql}
                    """,
                    (booking_id, list(rules.ACCEPTED_STATUSES), session["user_id"]),
                )
                changed = cur.rowcount > 0
                event = "cancel_declined"
            if changed:
                booking_events.announce(
                    cur, booking_id, event, actor_u_id=session["user_id"], at=at
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not changed:
        flash("That cancellation request is no longer open.", "error")
    elif decision == "approve":
        flash("Cancellation approved. The booking is cancelled.", "success")
    else:
        flash("Cancellation request declined. The booking stays.", "success")
    return _back_to("dashboard.owner", "#bookings")


@dashboard_bp.route("/owner/booking/<sealed(booking):booking_id>/assign", methods=["POST"])
@role_required("owner")
def assign_booking(booking_id):
    """Assign an accepted (or in-progress) booking to a mechanic of this owner's workshop (blank = unassign)."""
    raw = (request.form.get("m_id") or "").strip()
    try:
        m_id = int(raw) if raw else None
    except ValueError:
        abort(400)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.w_id FROM workshop w
                JOIN owner o ON w.o_id = o.o_id
                WHERE o.u_id = %s
            """,
                (session["user_id"],),
            )
            ws = cur.fetchone()
            if not ws:
                abort(403)

            mech_name = None
            if m_id is not None:
                # the mechanic must work in THIS workshop (row is locked so a leave
                # approval can't slip in between this check and the update)
                cur.execute(
                    """
                    SELECT u.name FROM mechanic m
                    JOIN users u ON m.u_id = u.u_id
                    WHERE m.m_id = %s AND m.w_id = %s
                    FOR SHARE OF m
                """,
                    (m_id, ws["w_id"]),
                )
                row = cur.fetchone()
                if not row:
                    conn.rollback()
                    flash("That mechanic is not part of your workshop.", "error")
                    return _back_to("dashboard.owner")
                mech_name = row["name"]

            # only this workshop's bookings, and only once the owner has accepted them
            cur.execute(
                """
                UPDATE booking SET assigned_m_id = %s
                WHERE b_id = %s AND w_id = %s AND status = ANY(%s)
            """,
                (m_id, booking_id, ws["w_id"], list(rules.ASSIGNABLE_STATUSES)),
            )
            changed = cur.rowcount
            if changed and m_id is not None:
                booking_events.announce(
                    cur, booking_id, "assigned", actor_u_id=session["user_id"]
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not changed:
        flash("Only accepted bookings of your workshop can be assigned.", "error")
    elif mech_name:
        flash(f"Booking assigned to {mech_name}.", "success")
    else:
        flash("Booking is now unassigned.", "success")
    return _back_to("dashboard.owner", "#bookings")


# add service for owner
@dashboard_bp.route("/owner/add-service", methods=["POST"])
@role_required("owner")
def add_service():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session["user_id"],))
    owner_row = cur.fetchone()
    cur.execute(
        "SELECT w_id, serves_cars, serves_two_wheelers FROM workshop WHERE o_id = %s",
        (owner_row["o_id"],),
    )
    workshop = cur.fetchone()

    if not workshop:
        cur.close()
        conn.close()
        return redirect(url_for("dashboard.owner"))

    price_range = request.form.get("price_range")
    duration = request.form.get("duration")

    # The service must exist and come from a catalog this workshop is allowed to use.
    try:
        sc_id = int(request.form.get("sc_id", ""))
    except ValueError:
        sc_id = None
    catalog_row = None
    if sc_id is not None:
        cur.execute("SELECT vehicle_type FROM service_catalog WHERE sc_id = %s", (sc_id,))
        catalog_row = cur.fetchone()
    if catalog_row is None:
        flash("Please choose a service from the list.", "error")
        cur.close()
        conn.close()
        return redirect(url_for("dashboard.owner"))
    if not vehicles.service_allowed(
        workshop["serves_cars"], workshop["serves_two_wheelers"], catalog_row["vehicle_type"]
    ):
        flash(
            "Your workshop does not serve "
            f"{vehicles.PLURAL_LABELS[catalog_row['vehicle_type']].lower()}, so you can't offer that service. "
            "Change what your workshop serves first if that is wrong.",
            "error",
        )
        cur.close()
        conn.close()
        return redirect(url_for("dashboard.owner"))

    try:
        cur.execute(
            "INSERT INTO service (w_id, sc_id, price_range, duration) VALUES (%s, %s, %s, %s)",
            (workshop["w_id"], sc_id, price_range, duration),
        )
        conn.commit()
        flash("Service added.", "success")
    except Exception:
        conn.rollback()
        flash("You already offer this service.", "error")

    cur.close()
    conn.close()
    return redirect(url_for("dashboard.owner"))


# create workshop for owner
@dashboard_bp.route("/owner/create-workshop", methods=["POST"])
@role_required("owner")
def create_workshop():
    # ---- validate the form before touching the database ----
    name = " ".join((request.form.get("name") or "").split())
    address = " ".join((request.form.get("address") or "").split())
    contact_no = (request.form.get("contact_no") or "").strip() or None
    whatsapp_no = (request.form.get("whatsapp_no") or "").strip() or None
    error = None

    if not name or len(name) > 150:
        error = "Please enter your workshop name (up to 150 characters)."
    elif not address or len(address) > 300:
        error = "Please enter your workshop address (up to 300 characters)."
    elif contact_no and not re.fullmatch(r"[0-9+()\-\s]{6,20}", contact_no):
        error = "Please enter a valid contact number."
    elif whatsapp_no and not (contact.valid_number(whatsapp_no) and contact.whatsapp_href(whatsapp_no)):
        error = "Please enter a valid WhatsApp number, including the country code if it is not an Indian number."

    # what the workshop serves: cars, two-wheelers or both (at least one)
    serves_cars, serves_two_wheelers, types_error = vehicles.parse_workshop_types(request.form)
    error = error or types_error

    latitude = longitude = None
    raw_lat = (request.form.get("latitude") or "").strip()
    raw_lng = (request.form.get("longitude") or "").strip()
    if not error and (raw_lat or raw_lng):
        try:
            latitude, longitude = float(raw_lat), float(raw_lng)
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError
        except ValueError:
            error = "That map location is not valid. Please set your pin again."

    if error:
        flash(error, "error")
        return redirect(url_for("dashboard.owner"))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session["user_id"],))
    owner_row = cur.fetchone()

    cur.execute("SELECT w_id FROM workshop WHERE o_id = %s", (owner_row["o_id"],))
    if cur.fetchone():
        cur.close()
        conn.close()
        return redirect(url_for("dashboard.owner"))

    # Owners accept the Workshop Owner Agreement before they can list a workshop (spec section 11). The
    # acceptance of the CURRENT version is recorded together with the listing.
    if not legal.has_accepted(accepted_pairs(cur, session["user_id"]), legal.DOC_OWNER):
        if request.form.get("accept_owner_agreement") not in ("on", "1", "true", "yes"):
            cur.close()
            conn.close()
            flash("Please read and accept the Workshop Owner Agreement before you list a workshop.", "error")
            return redirect(url_for("dashboard.owner"))
        record_consent(cur, session["user_id"], [legal.DOC_OWNER])

    cur.execute(
        "INSERT INTO workshop (o_id, name, address, contact_no, whatsapp_no, latitude, longitude, "
        "serves_cars, serves_two_wheelers, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')",
        (owner_row["o_id"], name, address, contact_no, whatsapp_no, latitude, longitude,
         serves_cars, serves_two_wheelers),
    )
    conn.commit()
    cur.close()
    conn.close()
    remember_consent("owner", True)  # they now list a workshop, so the owner agreement is a requirement

    flash(
        "Workshop submitted for approval. An admin needs to approve it before it goes live.",
        "success",
    )
    return redirect(url_for("dashboard.owner"))


@dashboard_bp.route("/owner/edit-workshop", methods=["POST"])
@role_required("owner")
def edit_workshop():
    """Let an owner change their own workshop's name, address, phone number and map pin."""
    name = " ".join((request.form.get("name") or "").split())
    address = " ".join((request.form.get("address") or "").split())
    contact_no = (request.form.get("contact_no") or "").strip() or None
    whatsapp_no = (request.form.get("whatsapp_no") or "").strip() or None
    error = None

    if not name or len(name) > 150:
        error = "Please enter your workshop name (up to 150 characters)."
    elif not address or len(address) > 300:
        error = "Please enter your workshop address (up to 300 characters)."
    elif contact_no and not re.fullmatch(r"[0-9+()\-\s]{6,20}", contact_no):
        error = "Please enter a valid contact number."
    elif whatsapp_no and not (contact.valid_number(whatsapp_no) and contact.whatsapp_href(whatsapp_no)):
        error = "Please enter a valid WhatsApp number, including the country code if it is not an Indian number."

    serves_cars, serves_two_wheelers, types_error = vehicles.parse_workshop_types(request.form)
    error = error or types_error

    latitude = longitude = None
    raw_lat = (request.form.get("latitude") or "").strip()
    raw_lng = (request.form.get("longitude") or "").strip()
    if not error and (raw_lat or raw_lng):
        try:
            latitude, longitude = float(raw_lat), float(raw_lng)
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError
        except ValueError:
            error = "That map location is not valid. Please set your pin again."

    if error:
        flash(error, "error")
        return redirect(url_for("dashboard.owner"))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # A workshop can't stop serving a vehicle type while it still offers services of that type.
        cur.execute(
            """
            SELECT DISTINCT sc.vehicle_type
            FROM service s
            JOIN service_catalog sc ON sc.sc_id = s.sc_id
            JOIN workshop w ON w.w_id = s.w_id
            JOIN owner o ON o.o_id = w.o_id
            WHERE o.u_id = %s
            """,
            (session["user_id"],),
        )
        blocked = vehicles.orphaned_types(
            serves_cars, serves_two_wheelers, [r["vehicle_type"] for r in cur.fetchall()]
        )
        if blocked:
            names = " and ".join(vehicles.SINGULAR_LABELS[t].lower() for t in blocked)
            flash(
                f"You still offer {names} services. Remove them before you stop serving that vehicle type.",
                "error",
            )
            return redirect(url_for("dashboard.owner"))

        # Was this workshop rejected? Then editing it resubmits it for approval.
        cur.execute(
            """
            SELECT w.status FROM workshop w JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            """,
            (session["user_id"],),
        )
        prev_row = cur.fetchone()
        resubmitting = bool(prev_row and prev_row["status"] == "rejected")

        # The WHERE clause ties the update to the signed-in owner's own workshop only.
        cur.execute(
            """
            UPDATE workshop w
            SET name = %s, address = %s, contact_no = %s, whatsapp_no = %s, latitude = %s, longitude = %s,
                serves_cars = %s, serves_two_wheelers = %s
            FROM owner o
            WHERE w.o_id = o.o_id AND o.u_id = %s
            """,
            (name, address, contact_no, whatsapp_no, latitude, longitude, serves_cars,
             serves_two_wheelers, session["user_id"]),
        )
        updated = cur.rowcount
        if updated and resubmitting:
            cur.execute(
                """
                UPDATE workshop SET status = 'pending', rejection_reason = NULL
                WHERE o_id = (SELECT o_id FROM owner WHERE u_id = %s)
                AND status = 'rejected'
                """,
                (session["user_id"],),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Failed to edit workshop for user_id=%s", session.get("user_id"))
        flash("Could not save your changes. Please try again.", "error")
        return redirect(url_for("dashboard.owner"))
    finally:
        cur.close()
        conn.close()

    if updated:
        if resubmitting:
            flash("Changes saved — your workshop is back under review.", "success")
        else:
            flash("Workshop details updated.", "success")
    else:
        flash("You do not have a workshop to edit.", "error")
    return redirect(url_for("dashboard.owner"))


# upload workshop photo for owner
@dashboard_bp.route("/owner/upload-photo", methods=["POST"])
@role_required("owner")
def upload_workshop_photo():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session["user_id"],))
    owner_row = cur.fetchone()
    cur.execute("SELECT w_id FROM workshop WHERE o_id = %s", (owner_row["o_id"],))
    workshop = cur.fetchone()

    if not workshop:
        cur.close()
        conn.close()
        flash("Create your workshop first.", "error")
        return redirect(url_for("dashboard.owner"))

    photo = request.files.get("photo")
    filename = save_upload_image(photo, UPLOAD_FOLDER, f"workshop_{workshop['w_id']}")
    if filename:
        photo_path = f"uploads/workshops/{filename}"

        cur.execute(
            "UPDATE workshop SET photo_path = %s WHERE w_id = %s",
            (photo_path, workshop["w_id"]),
        )
        conn.commit()
        flash("Workshop photo updated.", "success")
    else:
        flash("Please upload a valid image (png, jpg, jpeg, webp).", "error")

    cur.close()
    conn.close()
    return redirect(url_for("dashboard.owner"))


@dashboard_bp.route("/owner/delete-workshop", methods=["POST"])
@role_required("owner")
def delete_workshop():
    """Delete the current owner's workshop after cleaning up dependent records."""
    conn = get_db_connection()
    cur = conn.cursor()
    photo_path = None

    try:
        # Only ever select a workshop owned by the signed-in user.
        cur.execute(
            """
            SELECT w.w_id, w.name, w.photo_path
            FROM workshop w
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            FOR UPDATE OF w
        """,
            (session["user_id"],),
        )
        workshop = cur.fetchone()

        if not workshop:
            flash("You do not have a workshop to delete.", "error")
        else:
            workshop_id = workshop["w_id"]
            photo_path = workshop["photo_path"]

            # Remove requests first in case their foreign key does not cascade.
            cur.execute("DELETE FROM join_request WHERE w_id = %s", (workshop_id,))

            # Keep mechanic accounts; simply make them available to apply elsewhere.
            cur.execute(
                """
                UPDATE mechanic
                SET w_id = NULL,
                    leave_requested_at = NULL,
                    leave_reason = NULL
                WHERE w_id = %s
            """,
                (workshop_id,),
            )

            # The workshop foreign keys in the project schema cascade to bookings
            # and service records when the workshop is removed.
            cur.execute("DELETE FROM workshop WHERE w_id = %s", (workshop_id,))
            conn.commit()
            flash("Workshop deleted. Its mechanics are now unassigned.", "success")
    except Exception:
        conn.rollback()
        logging.exception(
            "Failed to delete workshop for user_id=%s", session.get("user_id")
        )
        flash("Could not delete the workshop. No changes were saved.", "error")
        photo_path = None
    finally:
        cur.close()
        conn.close()

    # Remove only the image file from the workshop upload directory, after commit.
    if photo_path:
        try:
            filename = os.path.basename(photo_path)
            image_file = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(image_file):
                os.remove(image_file)
        except OSError:
            logging.exception(
                "Workshop deleted, but its image file could not be removed."
            )

    return redirect(url_for("dashboard.owner"))


@dashboard_bp.route("/owner/capacity", methods=["POST"])
@role_required("owner")
def update_capacity():
    try:
        capacity = int(request.form.get("capacity", ""))
    except ValueError:
        flash("Capacity must be a number.", "error")
        return redirect(url_for("dashboard.owner"))

    if capacity < 1 or capacity > 100:
        flash("Capacity must be between 1 and 100.", "error")
        return redirect(url_for("dashboard.owner"))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT w.w_id FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """,
        (session["user_id"],),
    )
    ws = cur.fetchone()
    if not ws:
        cur.close()
        conn.close()
        abort(403)

    # can't set capacity below the number of mechanics already working here
    cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (ws["w_id"],))
    current = cur.fetchone()["n"]

    if capacity < current:
        flash(
            f"You already have {current} mechanics, so capacity can't be lower than that.",
            "error",
        )
    else:
        cur.execute(
            "UPDATE workshop SET capacity = %s WHERE w_id = %s", (capacity, ws["w_id"])
        )
        conn.commit()
        flash("Capacity updated.", "success")

    cur.close()
    conn.close()
    return redirect(url_for("dashboard.owner"))


@dashboard_bp.route("/owner/open-status", methods=["POST"])
@role_required("owner")
def update_open_status():
    """Owner switches the workshop between Open and Closed."""
    is_open = request.form.get("is_open") == "1"

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workshop SET is_open = %s
                WHERE o_id = (SELECT o_id FROM owner WHERE u_id = %s)
            """,
                (is_open, session["user_id"]),
            )
            changed = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not changed:
        flash("Create your workshop first.", "error")
    elif is_open:
        flash("Your workshop is now shown as Open.", "success")
    else:
        flash("Your workshop is now shown as Closed.", "success")
    return redirect(url_for("dashboard.owner"))


@dashboard_bp.route("/owner/hours", methods=["POST"])
@role_required("owner")
def update_workshop_hours():
    """Save the workshop's opening hours: one open/close pair applied to EVERY day.

    Both fields blank means no schedule at all: the workshop follows the Open/Closed
    switch only. A day's window may cross midnight (e.g. 20:00-02:00).
    """
    time_re = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    conn = get_db_connection()
    error = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT w_id FROM workshop WHERE o_id = (SELECT o_id FROM owner WHERE u_id = %s)",
                (session["user_id"],),
            )
            row = cur.fetchone()
            if not row:
                error = "Create your workshop first."
            else:
                w_id = row["w_id"]
                op = (request.form.get("open_time") or "").strip()
                cl = (request.form.get("close_time") or "").strip()
                if bool(op) != bool(cl) or (op and (not time_re.match(op) or not time_re.match(cl))):
                    error = "Enter both an open and a close time (or leave both empty)."
                else:
                    cur.execute("DELETE FROM workshop_hours WHERE workshop_id = %s", (w_id,))
                    if op:
                        cur.executemany(
                            "INSERT INTO workshop_hours (workshop_id, dow, open_time, close_time) "
                            "VALUES (%s, %s, %s, %s)",
                            [(w_id, dow, op, cl) for dow in range(7)],
                        )
        if error is None:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if error:
        flash(error, "error")
    else:
        flash("Opening hours saved — these apply every day. Customers see your workshop open only during this window.", "success")
    return redirect(url_for("dashboard.owner"))
