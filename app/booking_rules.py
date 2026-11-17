"""Booking lifecycle rules (spec section 6).

Everything here is plain Python: no Flask, no database. Routes, templates, the scheduled sweep and
the tests all read the same rules from this one file, and every time-based rule goes through
``now()`` so a test can swap in a fake clock instead of waiting two days.

Lifecycle
---------
    pending ──owner accepts──▶ confirmed ──start──▶ in_progress ──complete──▶ completed ──customer pays
       │                          │  │                   │
       │ customer cancels         │  └── customer asks to cancel; the owner approves or declines
       │ owner declines           │      (approve ⇒ cancelled)
       │ 48 hours pass ⇒ system   │
       ▼                          ▼
    cancelled                  cancelled

``confirmed`` is the stored value for what customers see as "Accepted". The name is kept because
existing rows, pages and tests already use it.
"""
from datetime import datetime, timedelta

PENDING = "pending"
CONFIRMED = "confirmed"  # shown to people as "Accepted"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
CANCELLED = "cancelled"

STATUSES = (PENDING, CONFIRMED, IN_PROGRESS, COMPLETED, CANCELLED)

STATUS_LABELS = {
    PENDING: "Pending",
    CONFIRMED: "Accepted",
    IN_PROGRESS: "In progress",
    COMPLETED: "Completed",
    CANCELLED: "Cancelled",
}

# Statuses where the owner has accepted the booking (the customer can only *ask* to cancel).
ACCEPTED_STATUSES = (CONFIRMED, IN_PROGRESS)
# Statuses that are still open: not finished and not cancelled.
OPEN_STATUSES = (PENDING, CONFIRMED, IN_PROGRESS)

# booking.cancelled_by
BY_CUSTOMER, BY_OWNER, BY_SYSTEM = "customer", "owner", "system"

# booking.cancel_request_status (NULL = the customer never asked)
REQUEST_OPEN, REQUEST_APPROVED, REQUEST_DECLINED = "requested", "approved", "declined"

# booking.payment_status
UNPAID, PAID = "unpaid", "paid"

CANCEL_REASON_MAX = 300  # booking.cancel_request_reason is VARCHAR(300)

# --- the 48-hour rule -------------------------------------------------------------------------
# An unanswered request is cancelled automatically after RESPONSE_WINDOW. The owner is reminded
# once, REMINDER_AFTER after the request was made. (Spec: "the owner gets a reminder"; the spec
# does not say when, so halfway is an assumption.)
RESPONSE_WINDOW = timedelta(hours=48)
REMINDER_AFTER = timedelta(hours=24)

# What an owner may do, as action -> (new status, statuses it may start from).
OWNER_ACTIONS = {
    "confirm": (CONFIRMED, (PENDING,)),
    "decline": (CANCELLED, (PENDING,)),
    "cancel": (CANCELLED, (PENDING, CONFIRMED)),
    "start": (IN_PROGRESS, (CONFIRMED,)),
    "complete": (COMPLETED, (IN_PROGRESS,)),
}

# What the assigned mechanic may do.
MECHANIC_ACTIONS = {
    "start": (IN_PROGRESS, (CONFIRMED,)),
    "complete": (COMPLETED, (IN_PROGRESS,)),
}

# The owner can still be handed a job to assign / re-assign while it is open and accepted.
ASSIGNABLE_STATUSES = ACCEPTED_STATUSES

# A bill may be set (or changed) until the booking is paid, but not on a cancelled booking.
BILLABLE_STATUSES = (CONFIRMED, IN_PROGRESS, COMPLETED)

# Nothing is paid upfront (spec section 6): the customer pays after the job is completed.
PAYABLE_STATUSES = (COMPLETED,)


def label(status):
    """'in_progress' -> 'In progress'. Unknown values are tidied rather than shown raw."""
    if status in STATUS_LABELS:
        return STATUS_LABELS[status]
    return str(status or "").replace("_", " ").capitalize()


# --- clock ------------------------------------------------------------------------------------
class SystemClock:
    """The real time of the server (naive local time, the same convention the rest of the app uses)."""

    def now(self):
        return datetime.now()


class FakeClock:
    """A clock a test controls. ``advance(hours=25)`` moves it forward."""

    def __init__(self, start):
        self._now = start

    def now(self):
        return self._now

    def set(self, moment):
        self._now = moment

    def advance(self, **kwargs):
        self._now = self._now + timedelta(**kwargs)
        return self._now


_clock = SystemClock()


def now():
    return _clock.now()


def use_clock(clock):
    """Swap the clock (tests). Returns the previous one so it can be put back."""
    global _clock
    previous, _clock = _clock, clock
    return previous


# --- 48-hour timing ----------------------------------------------------------------------------
def response_deadline(created_at):
    """When an unanswered request is cancelled automatically."""
    return created_at + RESPONSE_WINDOW


def is_expired(created_at, at):
    """True once the owner has had the whole window. Exactly at the deadline counts as expired."""
    return at >= response_deadline(created_at)


def reminder_due(created_at, reminder_sent_at, at):
    """True when the owner should be reminded now: not reminded yet, past the reminder point,
    and the request is not already past its deadline (an expired one is cancelled instead)."""
    if reminder_sent_at is not None:
        return False
    return created_at + REMINDER_AFTER <= at < response_deadline(created_at)


def hours_left(created_at, at):
    """Whole hours (rounded up) until automatic cancellation; 0 when it is due."""
    seconds = (response_deadline(created_at) - at).total_seconds()
    if seconds <= 0:
        return 0
    return int(-(-seconds // 3600))


def sweep_cutoffs(at):
    """``(expire_before, remind_before)`` for a sweep run at ``at``.

    A pending booking created at or before ``expire_before`` has run out of time; one created at or
    before ``remind_before`` (and after ``expire_before``) is due its reminder. The SQL compares
    ``created_at`` to these values, so the database never has to know what time it is.
    """
    return at - RESPONSE_WINDOW, at - REMINDER_AFTER


# --- who may cancel, and how ------------------------------------------------------------------
def customer_cancel_mode(status, request_status, is_paid):
    """What the customer can do about cancelling right now.

    ``'cancel'``  cancel immediately (the owner has not accepted yet)
    ``'request'`` send a cancellation request the owner will decide (accepted, not yet finished)
    ``None``      nothing: finished, cancelled, paid, or a request was already made
    """
    if is_paid:
        return None
    if status == PENDING:
        return "cancel"
    if status in ACCEPTED_STATUSES and request_status is None:
        return "request"
    return None


def clean_cancel_reason(raw):
    """Tidy the customer's optional reason. Returns ``(text or None, error or None)``."""
    text = " ".join((raw or "").split())
    if len(text) > CANCEL_REASON_MAX:
        return None, f"Please keep the reason under {CANCEL_REASON_MAX} characters."
    return (text or None), None


def can_pay(status, is_paid):
    """The customer can pay only after the job is completed, and only once."""
    return status in PAYABLE_STATUSES and not is_paid
