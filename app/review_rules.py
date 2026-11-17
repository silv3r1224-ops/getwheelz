"""Review rules (spec section 7): input checks and display names. Pure Python, no database.

Who may review is enforced in SQL (routes/workshops.py inserts only for the customer's own
COMPLETED booking, one review per booking) and again by the review table's constraints and
row-level security; this file only cleans and validates what the person typed.
"""

RATING_MIN, RATING_MAX = 1, 5
TEXT_MAX = 1000  # review.comment and review.owner_reply are limited to this
NAME_MAX = 60  # review.reviewer_name


def clean_review(rating_raw, text_raw):
    """``(rating, text, error)``. A review needs a whole-number rating 1-5 and some text."""
    try:
        rating = int(str(rating_raw).strip())
    except (TypeError, ValueError):
        return None, None, "Please choose a rating from 1 to 5 stars."
    if not RATING_MIN <= rating <= RATING_MAX:
        return None, None, "Please choose a rating from 1 to 5 stars."
    text = _tidy(text_raw)
    if not text:
        return None, None, "Please write a few words about your visit."
    if len(text) > TEXT_MAX:
        return None, None, f"Please keep your review under {TEXT_MAX} characters."
    return rating, text, None


def clean_reply(text_raw):
    """``(text, error)`` for the owner's one public reply."""
    text = _tidy(text_raw)
    if not text:
        return None, "Please write your reply."
    if len(text) > TEXT_MAX:
        return None, f"Please keep your reply under {TEXT_MAX} characters."
    return text, None


def public_name(full_name):
    """'Asha Kumar' -> 'Asha K.'; one name stays as it is. Reviews never show a full surname."""
    parts = (full_name or "").split()
    if not parts:
        return "Customer"
    if len(parts) == 1:
        return parts[0][:NAME_MAX]
    return f"{parts[0]} {parts[-1][0].upper()}."[:NAME_MAX]


def stars(avg):
    """Whole stars to fill for an average (rounded to the nearest half is overkill here)."""
    return int(round(float(avg))) if avg is not None else 0


def _tidy(raw):
    """Trim and collapse runs of spaces, but keep the line breaks a person typed."""
    lines = [" ".join(line.split()) for line in (raw or "").replace("\r\n", "\n").split("\n")]
    text = "\n".join(lines).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text
