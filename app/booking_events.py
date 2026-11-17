"""Booking events: who gets told what, safe status changes, and the 48-hour sweep.

Two layers:

* ``compose`` is pure. Given an event name and the people on a booking it returns the notices to
  send, so the wording and the "who is told" rules can be tested without a database.
* ``announce`` / ``change_status`` / ``sweep_unanswered`` run SQL on a cursor the caller owns. They
  never commit: the status change and the notices it causes are saved in ONE transaction, so a
  person is never left without the notice for a change (same rule as the Phase 2 approvals).

Notices are plain rows in ``messages`` (no sender, one recipient), the existing notice mechanism.

Why ``booking_parties``: a customer, an owner and a mechanic can each read only their own rows of
``customer`` / ``owner`` under row-level security, but a notice has to reach the *other* people on
the booking. ``booking_parties()`` is a SECURITY DEFINER function (scripts/booking_party_lookup.sql,
installed by scripts/migrate_booking_lifecycle.py) that returns the people on ONE booking, and only
to someone who is on that booking or is an admin.
"""
import logging

from app import booking_rules as rules

# One arbitrary number identifying "the sweep" to pg_try_advisory_xact_lock, so two workers that
# wake up together do not both run it.
SWEEP_LOCK_KEY = 7_340_001

SUBJECT_MAX = 150
BODY_MAX = 2000

_TIME_FORMAT = "%d %b %Y, %I:%M %p"


# ----------------------------------------------------------------------------- wording (pure)
def _when(p):
    t = p.get("requested_time")
    return t.strftime(_TIME_FORMAT) if t else "the requested time"


def _what(p):
    return f'{p["service_name"]} at {p["workshop_name"]} ({_when(p)})'


def _vehicle(p):
    text = (p.get("vehicle_description") or "").strip()
    return f"\nVehicle: {text}" if text else ""


def compose(event, p, actor_u_id=None, extra=None):
    """The notices an event sends, as ``[(recipient_u_id, subject, body), ...]``.

    ``p`` is a ``booking_parties`` row (a dict works). The person who caused the event is never
    notified about their own action. ``extra`` may hold ``reason`` and ``amount_label``.
    """
    extra = extra or {}
    customer, owner, mechanic = p.get("customer_u_id"), p.get("owner_u_id"), p.get("mechanic_u_id")
    ref = f'booking #{p["b_id"]}'
    out = []

    def to(u_id, subject, body):
        if u_id and u_id != actor_u_id:
            out.append((u_id, subject[:SUBJECT_MAX], body[:BODY_MAX]))

    if event == "requested":
        to(owner, f'New booking request from {p["customer_name"]}',
           f'{p["customer_name"]} asked for {_what(p)}.{_vehicle(p)}\n\n'
           "Please accept or decline it from your dashboard. If nobody answers within 48 hours "
           "the request is cancelled automatically.")
    elif event == "accepted":
        to(customer, f'{p["workshop_name"]} accepted your booking',
           f"Your {ref} is accepted: {_what(p)}. The workshop will assign a mechanic. "
           "You pay online after the job is completed.")
    elif event == "declined":
        to(customer, f'{p["workshop_name"]} could not take your booking',
           f"Your {ref} was declined: {_what(p)}. Nothing was charged. "
           "You can book another time or another workshop.")
    elif event == "owner_cancelled":
        body = f"Your {ref} was cancelled by the workshop: {_what(p)}. Nothing was charged."
        to(customer, f'{p["workshop_name"]} cancelled your booking', body)
        to(mechanic, f"A job you were assigned was cancelled ({ref})",
           f"{ref} ({_what(p)}) was cancelled by the workshop. You do not need to do it.")
    elif event == "customer_cancelled":
        to(owner, f'{p["customer_name"]} cancelled their booking',
           f"{p['customer_name']} cancelled {ref}: {_what(p)}.")
        to(mechanic, f"A job you were assigned was cancelled ({ref})",
           f"{ref} ({_what(p)}) was cancelled by the customer. You do not need to do it.")
    elif event == "cancel_requested":
        reason = f'\n\nTheir reason: {extra["reason"]}' if extra.get("reason") else ""
        to(owner, f'{p["customer_name"]} asked to cancel an accepted booking',
           f"{p['customer_name']} asked to cancel {ref}: {_what(p)}.{reason}\n\n"
           "Please approve or decline the request from your dashboard.")
    elif event == "cancel_approved":
        to(customer, f'{p["workshop_name"]} approved your cancellation',
           f"Your cancellation request for {ref} was approved. The booking is cancelled "
           "and nothing was charged.")
        to(mechanic, f"A job you were assigned was cancelled ({ref})",
           f"{ref} ({_what(p)}) was cancelled at the customer's request. You do not need to do it.")
    elif event == "cancel_declined":
        to(customer, f'{p["workshop_name"]} declined your cancellation request',
           f"Your cancellation request for {ref} was declined, so the booking stays: {_what(p)}. "
           "Please contact the workshop if you cannot come.")
    elif event == "assigned":
        to(mechanic, f"New job assigned: {p['service_name']}",
           f"You were assigned {ref}: {_what(p)}.{_vehicle(p)}")
    elif event == "started":
        body = f"Work has started on your {ref}: {_what(p)}."
        to(customer, f'Work started on your {p["service_name"]}', body)
        to(owner, f"Work started on {ref}",
           f"{p['mechanic_name'] or 'A mechanic'} started {ref}: {_what(p)}.")
    elif event == "completed":
        pay = "You can now pay for it online from My Bookings."
        to(customer, f'Your {p["service_name"]} is complete', f"Your {ref} is complete: {_what(p)}. {pay}")
        to(owner, f"{ref} was marked complete",
           f"{p['mechanic_name'] or 'A mechanic'} marked {ref} complete: {_what(p)}. "
           "The customer can now pay.")
    elif event == "paid":
        amount = extra.get("amount_label") or ""
        to(owner, f"Payment received for {ref}",
           f"{p['customer_name']} paid {amount} for {_what(p)}.".replace("  ", " "))
    elif event == "reminder":
        to(owner, f"Reminder: {p['customer_name']} is waiting for an answer",
           f"{p['customer_name']} asked for {_what(p)} and has not had an answer yet. "
           "Please accept or decline it. Unanswered requests are cancelled automatically after "
           "48 hours.")
    elif event == "auto_cancelled":
        to(customer, f'Your booking at {p["workshop_name"]} was cancelled automatically',
           f"The workshop did not answer within 48 hours, so your {ref} was cancelled "
           f"automatically: {_what(p)}. Nothing was charged. Please book again or try another workshop.")
        to(owner, f"{ref} was cancelled automatically",
           f"{ref} from {p['customer_name']} was not answered within 48 hours, so it was cancelled.")
    else:
        raise ValueError(f"unknown booking event: {event}")
    return out


# ----------------------------------------------------------------------------- database work
def get_parties(cur, b_id):
    """The people and names on one booking (see the module docstring), or None."""
    cur.execute("SELECT * FROM booking_parties(%s)", (b_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def send_notice(cur, recipient_u_id, subject, body, at=None):
    """One system notice (category 'update') in a person's inbox. Raises on failure (never best effort)."""
    cur.execute(
        """
        INSERT INTO messages (sender_u_id, recipient_u_id, subject, body, sent_at, category)
        VALUES (NULL, %s, %s, %s, %s, 'update')
        """,
        (recipient_u_id, subject[:SUBJECT_MAX], body[:BODY_MAX], at or rules.now()),
    )


def announce(cur, b_id, event, actor_u_id=None, extra=None, at=None):
    """Tell everyone involved about ``event``. Returns how many notices were queued."""
    parties = get_parties(cur, b_id)
    if not parties:
        logging.warning("No parties found for booking %s (event %s); no notice sent", b_id, event)
        return 0
    notices = compose(event, parties, actor_u_id, extra)
    for u_id, subject, body in notices:
        send_notice(cur, u_id, subject, body, at)
    return len(notices)


def change_status(cur, b_id, new_status, from_statuses, scope_sql="", scope_params=(), sets=None):
    """Move a booking to ``new_status`` in ONE conditional UPDATE. Returns True if it moved.

    ``from_statuses`` are the only statuses it may leave, so two people clicking at once cannot both
    win. ``scope_sql`` / ``scope_params`` add who-may-touch-this (their workshop, their job, their
    booking). ``sets`` is a list of ``("column = %s", value)`` for the other columns that change
    with the status (cancelled_by, cancelled_at, ...).
    """
    sets = sets or []
    assignments = ", ".join(["status = %s"] + [s for s, _ in sets])
    params = [new_status] + [v for _, v in sets] + [b_id, list(from_statuses)] + list(scope_params)
    cur.execute(
        f"UPDATE booking SET {assignments} WHERE b_id = %s AND status = ANY(%s) {scope_sql}",
        params,
    )
    return cur.rowcount > 0


# ----------------------------------------------------------------------------- the 48-hour sweep
def sweep_unanswered(cur, at=None):
    """Cancel pending bookings that ran out of time and remind owners of the ones running low.

    Safe to run as often and from as many places as you like: every change is a conditional UPDATE
    ... RETURNING, so a booking is cancelled (or reminded about) at most once, and a transaction
    level advisory lock stops two workers doing the work at the same moment. Does not commit.

    Returns ``{"cancelled": [b_id, ...], "reminded": [b_id, ...]}``, or ``None`` when another
    worker already holds the lock.
    """
    at = at or rules.now()
    expire_before, remind_before = rules.sweep_cutoffs(at)

    cur.execute("SELECT pg_try_advisory_xact_lock(%s) AS got", (SWEEP_LOCK_KEY,))
    if not cur.fetchone()["got"]:
        return None

    cur.execute(
        """
        UPDATE booking
        SET status = 'cancelled', cancelled_by = 'system', cancelled_at = %s
        WHERE status = 'pending' AND created_at <= %s
        RETURNING b_id
        """,
        (at, expire_before),
    )
    cancelled = [r["b_id"] for r in cur.fetchall()]
    for b_id in cancelled:
        announce(cur, b_id, "auto_cancelled", at=at)

    # reminders only for requests that are still inside their window (the ones past it were just cancelled)
    cur.execute(
        """
        UPDATE booking SET reminder_sent_at = %s
        WHERE status = 'pending' AND reminder_sent_at IS NULL
          AND created_at <= %s AND created_at > %s
        RETURNING b_id
        """,
        (at, remind_before, expire_before),
    )
    reminded = [r["b_id"] for r in cur.fetchall()]
    for b_id in reminded:
        announce(cur, b_id, "reminder", at=at)

    return {"cancelled": cancelled, "reminded": reminded}


def run_sweep(config, at=None):
    """Open a connection of its own, act as the system, run the sweep and commit.

    Used by the scheduled command (scripts/run_booking_sweep.py) and the throttled page-load check.
    The connection is separate from the request's, set to an admin context for this one connection
    only (the sweep must update other people's bookings, which row-level security otherwise blocks),
    and closed before returning, so nothing leaks into the request. Returns ``sweep_unanswered``'s
    result.
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        host=config["DB_HOST"],
        port=config["DB_PORT"],
        database=config["DB_NAME"],
        user=config["DB_USER"],
        password=config["DB_PASSWORD"],
        cursor_factory=psycopg2.extras.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.luid', '0', false)")
            cur.execute("SELECT set_config('app.lrole', 'admin', false)")
            cur.execute("SELECT set_config('app.ladmin', 'main', false)")
            result = sweep_unanswered(cur, at)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
