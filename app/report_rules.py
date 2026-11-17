"""Report verification rules (spec section 9). Pure Python: no Flask, no database.

A report moves through these steps; the routes in app/routes/main.py enforce them with SQL and the
admin popup (templates/inbox.html) shows the same state, so the wording and the gating live here:

1. OPEN        filed; the reporter was acknowledged.
2. RESPONSE    the admin decides, per report, whether to ask the reported person to respond:
               - ``requested``: they get 72 hours (``RESPONSE_WINDOW``) to answer from their Reports section;
               - ``skipped``: for urgent safety cases, with a reason that is recorded on the report.
3. VERIFY      the admin marks the report Verified. Allowed only once the response step is settled:
               the response arrived, the window ran out, or the request was skipped.
4. ACTION      Warn and Suspend stay LOCKED until the report is Verified. Dismiss is ALWAYS available.
5. OUTCOME     recorded in report_resolution (a report is resolved once); both sides are notified.
"""
from datetime import timedelta

RESPONSE_WINDOW = timedelta(hours=72)

MODE_REQUESTED, MODE_SKIPPED = "requested", "skipped"

# response states
NOT_DECIDED = "not_decided"    # the admin has not chosen yet
WAITING = "waiting"            # asked, still inside the window, no answer yet
RESPONDED = "responded"        # the reported person answered
WINDOW_ENDED = "window_ended"  # asked, the window ran out with no answer
SKIPPED = "skipped"            # the admin skipped the request (reason recorded)

SKIP_REASON_MIN, SKIP_REASON_MAX = 10, 300
RESPONSE_MIN, RESPONSE_MAX = 5, 2000

STATE_LABELS = {
    NOT_DECIDED: "Response not decided",
    WAITING: "Waiting for their response",
    RESPONDED: "Response received",
    WINDOW_ENDED: "Window ended without a response",
    SKIPPED: "Response request skipped",
}


def deadline(requested_at):
    """When the reported person's window closes."""
    return requested_at + RESPONSE_WINDOW


def response_state(mode, requested_at, responded_at, now):
    """Where the response step stands. ``requested_at`` may be None unless mode is 'requested'."""
    if mode == MODE_SKIPPED:
        return SKIPPED
    if mode != MODE_REQUESTED or requested_at is None:
        return NOT_DECIDED
    if responded_at is not None:
        return RESPONDED
    return WAITING if now < deadline(requested_at) else WINDOW_ENDED


def can_verify(state):
    """Verified needs the response step settled (answered, ran out, or skipped), never NOT_DECIDED
    or WAITING. Dismiss does not need this."""
    return state in (RESPONDED, WINDOW_ENDED, SKIPPED)


def can_respond(state):
    """The reported person may answer only while the window is open and only once."""
    return state == WAITING


def can_sanction(verified):
    """Warn and Suspend are locked until the report is Verified."""
    return bool(verified)


def outcome_allowed(outcome, verified, can_suspend=True):
    """``(allowed, reason)`` for a resolve outcome. Dismiss is always allowed."""
    if outcome == "dismiss":
        return True, ""
    if outcome not in ("warn", "suspend"):
        return False, "Please choose how to resolve this report."
    if not can_sanction(verified):
        return False, "Verify the report first: Warn and Suspend are locked until it is verified."
    if outcome == "suspend" and not can_suspend:
        return False, "This kind of report cannot be resolved by suspending."
    return True, ""


def clean_skip_reason(raw):
    text = " ".join((raw or "").split())
    if len(text) < SKIP_REASON_MIN:
        return None, f"Please say why the request is skipped (at least {SKIP_REASON_MIN} characters)."
    if len(text) > SKIP_REASON_MAX:
        return None, f"Please keep the reason under {SKIP_REASON_MAX} characters."
    return text, None


def clean_response(raw):
    """The reported person's answer; line breaks are kept."""
    lines = [" ".join(line.split()) for line in (raw or "").replace("\r\n", "\n").split("\n")]
    text = "\n".join(lines).strip()
    if len(text) < RESPONSE_MIN:
        return None, "Please write your response."
    if len(text) > RESPONSE_MAX:
        return None, f"Please keep your response under {RESPONSE_MAX} characters."
    return text, None


def hours_left(requested_at, now):
    """Whole hours (rounded up) left in the window; 0 when it has ended."""
    seconds = (deadline(requested_at) - now).total_seconds()
    return 0 if seconds <= 0 else int(-(-seconds // 3600))
