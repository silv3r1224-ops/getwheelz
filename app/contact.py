"""The workshop's Call and WhatsApp buttons (spec section 7). Pure Python, no database.

Who sees the number is decided in ONE place, ``can_see_contact``: only a signed-in customer or
mechanic. Everyone else (visitors, owners, admins) gets no number from the public workshop page;
visitors are shown a log-in prompt instead. There is no in-site chat.
"""
import re

CONTACT_ROLES = ("customer", "mechanic")

# What an owner may type: digits and the usual separators, 6-20 characters (same rule as the
# existing contact_no field).
NUMBER_PATTERN = re.compile(r"[0-9+()\-\s]{6,20}")
DEFAULT_COUNTRY_CODE = "91"  # the demo runs in India; a bare 10-digit number is treated as +91


def can_see_contact(role):
    return role in CONTACT_ROLES


def valid_number(raw):
    """True for something that looks like a phone number. Blank is handled by the caller."""
    return bool(NUMBER_PATTERN.fullmatch((raw or "").strip()))


def digits(raw):
    return re.sub(r"\D", "", raw or "")


def tel_href(raw):
    """A tel: link, or None."""
    cleaned = re.sub(r"[^0-9+]", "", raw or "")
    return f"tel:{cleaned}" if len(digits(cleaned)) >= 6 else None


def whatsapp_href(raw):
    """A wa.me link (international digits only), or None if the number cannot be a WhatsApp number."""
    number = digits(raw)
    if (raw or "").strip().startswith("00"):
        number = number[2:]
    elif len(number) == 10:
        number = DEFAULT_COUNTRY_CODE + number
    elif len(number) == 11 and number.startswith("0"):
        number = DEFAULT_COUNTRY_CODE + number[1:]
    if not 8 <= len(number) <= 15:
        return None
    return f"https://wa.me/{number}"


def public_buttons(contact_no, whatsapp_no):
    """The workshop hero card shows its Call / WhatsApp details to everyone — the owner
    publishes them so customers can reach the workshop. Returns the same shape as
    ``buttons_for`` with state "show"; hrefs are None when a number is missing/invalid."""
    return {"state": "show", "call": tel_href(contact_no), "whatsapp": whatsapp_href(whatsapp_no)}


def buttons_for(role, contact_no, whatsapp_no):
    """What the workshop page should show this viewer.

    Returns ``{"state": ..., "call": href|None, "whatsapp": href|None}`` where state is
    ``"show"`` (signed-in customer/mechanic who may use the buttons), ``"login"`` (a visitor: show
    the log-in prompt, NO number), or ``"hidden"`` (owner, admin: nothing). The numbers are only
    returned for ``"show"``, so a template cannot leak one by mistake.
    """
    if can_see_contact(role):
        return {"state": "show", "call": tel_href(contact_no), "whatsapp": whatsapp_href(whatsapp_no)}
    if not role:
        return {"state": "login", "call": None, "whatsapp": None}
    return {"state": "hidden", "call": None, "whatsapp": None}
