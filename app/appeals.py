"""Appeal rules (spec sections 4 and 9). Pure Python: no Flask, no database.

A suspended user or a rejected owner can appeal once per decision. The appeal is a case an admin must
answer by upholding or overturning it, with a note.

WHO REVIEWS (``choose_reviewer``)
* The main admin reviews appeals.
* If the MAIN admin made the original decision, another admin reviews: the sub-admin who covers the
  appellant's area (customers, owners and their workshops, or mechanics).
* Fallback (spec assumption): if the main admin decided and no active sub-admin covers that area, the
  appeal waits for the main admin and is flagged ``needs_second_reviewer``.
"""
KIND_SUSPENSION, KIND_LISTING = "suspension", "listing"
KINDS = (KIND_SUSPENSION, KIND_LISTING)

OPEN, UPHELD, OVERTURNED = "open", "upheld", "overturned"
DECISIONS = {"uphold": UPHELD, "overturn": OVERTURNED}

MAIN = "main"
# the user role each sub-admin moderates, and the reverse: which sub-admin covers a role
ADMIN_AREA_FOR_ROLE = {
    "customer": "customer_manager",
    "owner": "owner_workshop_manager",
    "mechanic": "mechanic_manager",
}

MESSAGE_MIN, MESSAGE_MAX = 10, 1000
NOTE_MIN, NOTE_MAX = 5, 500


def area_admin_type(appellant_role):
    """The sub-admin type that covers this kind of person, or None (admins cannot appeal)."""
    return ADMIN_AREA_FOR_ROLE.get(appellant_role)


def choose_reviewer(decided_by_type, appellant_role, active_area_admins):
    """``(reviewer_type, needs_second_reviewer)``.

    ``decided_by_type`` is the admin_type of whoever made the original decision (None if unknown).
    ``active_area_admins`` is how many ACTIVE sub-admins cover the appellant's area.
    """
    area = area_admin_type(appellant_role)
    if decided_by_type == MAIN:
        if area and active_area_admins > 0:
            return area, False
        return MAIN, True
    return MAIN, False


def can_review(admin_type, reviewer_type, status=OPEN):
    """Only the assigned reviewer may answer an open appeal (the main admin cannot review one that
    belongs to a sub-admin, and no sub-admin can take one assigned to someone else)."""
    return status == OPEN and admin_type == reviewer_type


def can_appeal(decision_at, last_appeal_at, has_open):
    """One appeal per decision. ``decision_at`` is when the suspension / rejection happened (None for
    old data); ``last_appeal_at`` the newest earlier appeal of this kind (None if none)."""
    if has_open:
        return False
    if last_appeal_at is None:
        return True
    if decision_at is None:
        return False  # old data: they already appealed once
    return last_appeal_at < decision_at  # only a NEW decision can be appealed again


def clean_message(raw):
    text = _tidy(raw)
    if len(text) < MESSAGE_MIN:
        return None, f"Please tell us why the decision should be reconsidered (at least {MESSAGE_MIN} characters)."
    if len(text) > MESSAGE_MAX:
        return None, f"Please keep your appeal under {MESSAGE_MAX} characters."
    return text, None


def clean_note(raw):
    text = " ".join((raw or "").split())
    if len(text) < NOTE_MIN:
        return None, "Please write a short note explaining the decision."
    if len(text) > NOTE_MAX:
        return None, f"Please keep the note under {NOTE_MAX} characters."
    return text, None


def decision_status(raw):
    """'uphold' / 'overturn' -> 'upheld' / 'overturned', else None."""
    return DECISIONS.get((raw or "").strip().lower())


def _tidy(raw):
    lines = [" ".join(line.split()) for line in (raw or "").replace("\r\n", "\n").split("\n")]
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text
