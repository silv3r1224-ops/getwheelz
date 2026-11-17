"""Inbox presentation rules (spec section 8). Pure Python: no Flask, no database.

* Notice categories and their icons. Admins pick one when they send a notice; notices the system
  sends itself (booking updates, approvals, review replies) use ``update``.
* ``relative_time`` for the compact rows ("5m ago", "Yesterday").
* ``preview`` for the one-line text under a row's title.
"""
from datetime import datetime

# key -> (label, boxicons class, may an admin choose it?)
CATEGORIES = {
    "general": ("General", "bx-envelope", True),
    "important": ("Important", "bxs-error", True),
    "maintenance": ("Maintenance", "bx-wrench", True),
    "update": ("Update", "bx-bell", False),  # sent by the system, not choosable
}
DEFAULT_CATEGORY = "general"
SYSTEM_CATEGORY = "update"
IMPORTANT = "important"
PREVIEW_LENGTH = 90


def admin_categories():
    """Categories an admin may choose when sending: ``[(key, label, icon), ...]``."""
    return [(k, v[0], v[1]) for k, v in CATEGORIES.items() if v[2]]


def clean_category(raw):
    """The category from a form value. Unknown, blank or system-only values become General, so a
    forged form can never send a notice that looks like it came from the system."""
    raw = (raw or "").strip().lower()
    return raw if raw in CATEGORIES and CATEGORIES[raw][2] else DEFAULT_CATEGORY


def category_label(key):
    return CATEGORIES.get(key, CATEGORIES[DEFAULT_CATEGORY])[0]


def category_icon(key):
    return CATEGORIES.get(key, CATEGORIES[DEFAULT_CATEGORY])[1]


def relative_time(moment, now=None):
    """'Just now', '5m ago', '3h ago', 'Yesterday', '4d ago', else '12 Mar' / '12 Mar 2025'."""
    if not moment:
        return ""
    now = now or datetime.now()
    seconds = (now - moment).total_seconds()
    if seconds < 0:  # a time slightly in the future (clock drift) is "just now"
        return "Just now" if seconds > -300 else moment.strftime("%d %b %Y")
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    days = (now.date() - moment.date()).days
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days}d ago"
    if moment.year == now.year:
        return moment.strftime("%d %b").lstrip("0")
    return moment.strftime("%d %b %Y").lstrip("0")


def preview(text, limit=PREVIEW_LENGTH):
    """One line of text: line breaks and runs of spaces collapsed, cut on a word with an ellipsis."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0] or flat[:limit]
    return cut.rstrip(" ,.;:-") + "…"
