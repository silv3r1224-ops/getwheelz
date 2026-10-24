"""Tiny email helper (standard library only). Configure it with the MAIL_* values in .env."""

import smtplib
import threading
import time
from email.message import EmailMessage

from flask import current_app


def mail_configured():
    return bool(current_app.config.get("MAIL_SERVER"))


_send_lock = threading.Lock()


def _smtp_send(cfg, msg):
    host, port = cfg["MAIL_SERVER"], cfg["MAIL_PORT"]
    if cfg.get("MAIL_USE_SSL"):
        server = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
    with server:
        server.ehlo()
        if cfg.get("MAIL_USE_TLS") and not cfg.get("MAIL_USE_SSL"):
            server.starttls()
            server.ehlo()
        if cfg.get("MAIL_USERNAME"):
            server.login(cfg["MAIL_USERNAME"], cfg.get("MAIL_PASSWORD") or "")
        server.send_message(msg)


def send_email(to, subject, text, html=None, reply_to=None):
    """Send one email. Raises if the SMTP server refuses or cannot be reached.

    Mailtrap's free sandbox allows roughly one email per second ("Too many emails per second"),
    and a sign-up can fire several emails at once, so sends are done one at a time and a
    rate-limit refusal is retried a few times after a short pause.
    """
    cfg = current_app.config
    sender = cfg.get("MAIL_FROM") or cfg.get("MAIL_USERNAME")
    if not sender:
        raise RuntimeError("Set MAIL_FROM (or MAIL_USERNAME) in .env")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    with _send_lock:
        for attempt in range(4):
            try:
                _smtp_send(cfg, msg)
                break
            except smtplib.SMTPResponseException as e:
                limited = e.smtp_code in (450, 451, 452, 421, 550) and (
                    b"too many" in (e.smtp_error or b"").lower()
                    or b"rate" in (e.smtp_error or b"").lower()
                )
                if not limited or attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        time.sleep(float(cfg.get("MAIL_MIN_INTERVAL", 0) or 0))


# ==========================================================================================
# Account emails: welcome (sign-up), new sign-in, password changed.
#
# They are sent from a background thread, so a slow mail server never slows down signing up or
# logging in, and a failure is only logged (it never breaks the page). Accounts here are dummy
# accounts for now, so nothing asks the person to confirm their email: these are plain notices.
#   - MAIL_SERVER not set  -> nothing is sent; the email is printed in the Flask console instead
#   - MAIL_NOTIFICATIONS=0 -> account emails are switched off (reset-password emails still work)
#   - MAIL_SKIP_DOMAINS    -> addresses on these domains are skipped (fake addresses only bounce)
# ==========================================================================================
import logging
import threading
import time
from datetime import datetime, timezone
from html import escape

from flask import request, url_for

_last_login_mail = {}
_last_login_lock = threading.Lock()

ROLE_LABELS = {
    "customer": "customer",
    "owner": "workshop owner",
    "mechanic": "mechanic",
}
ROLE_NEXT_STEP = {
    "customer": "Search for a workshop near you, pick a service and send a booking request.",
    "owner": "Add your workshop, list your services and set your opening status so customers can book you.",
    "mechanic": "Browse workshops and send a join request. The owner reviews it, and then jobs can be assigned to you.",
}


def send_email_async(to, subject, text, html=None):
    """Send in a background thread. Errors are logged, never raised."""
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                send_email(to, subject, text, html)
            except Exception:
                logging.exception('Could not send the "%s" email to %s', subject, to)

    threading.Thread(target=run, daemon=True).start()


def _skipped(to):
    domain = to.rsplit("@", 1)[-1].strip().lower()
    for d in current_app.config.get("MAIL_SKIP_DOMAINS", ()):
        if domain == d or domain.endswith("." + d):
            return True
    return False


def _deliver(to, subject, text, html):
    cfg = current_app.config
    if not cfg.get("MAIL_NOTIFICATIONS", True) or not to or "@" not in to:
        return
    if _skipped(to):
        logging.info(
            'Skipped the "%s" email: %s is on a MAIL_SKIP_DOMAINS domain.', subject, to
        )
        return
    if not mail_configured():
        logging.warning(
            'MAIL_SERVER is not set, so no email was sent. To %s, "%s":\n%s',
            to,
            subject,
            text,
        )
        return
    send_email_async(to, subject, text, html)


def _base_url():
    return (current_app.config.get("APP_BASE_URL") or request.url_root).rstrip("/")


def _link(endpoint):
    return _base_url() + url_for(endpoint)


def _device(ua):
    ua = ua or ""
    browser = next(
        (
            n
            for k, n in (
                ("Edg/", "Edge"),
                ("OPR/", "Opera"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if k in ua
        ),
        "a browser",
    )
    system = next(
        (
            n
            for k, n in (
                ("Windows", "Windows"),
                ("Android", "Android"),
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Mac OS X", "macOS"),
                ("Linux", "Linux"),
            )
            if k in ua
        ),
        "an unknown device",
    )
    return f"{browser} on {system}"


def _who():
    """When / where this request came from, read now (inside the request) for the email."""
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return [
        ("When", datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")),
        ("Device", _device(request.headers.get("User-Agent"))),
        ("IP address", forwarded or request.remote_addr or "unknown"),
    ]


def _layout(heading, paragraphs, details=None, button=None, note=None):
    """(text, html) versions of one branded email. Every value that came from a person is escaped."""
    text = [heading, ""]
    text += [p[0] for p in paragraphs]
    if details:
        text += [""] + [f"{k}: {v}" for k, v in details]
    if button:
        text += ["", f"{button[0]}: {button[1]}"]
    if note:
        text += ["", note]
    text += ["", "- Getwheelz"]

    rows = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#8b8b96;font-size:13px">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#f4f4f6;font-size:13px">{escape(v)}</td></tr>'
        for k, v in (details or [])
    )
    body = "".join(
        f'<p style="margin:0 0 14px;color:#c9c9d1;font-size:15px;line-height:1.6">{p[1]}</p>'
        for p in paragraphs
    )
    html = (
        '<div style="background:#08080a;padding:28px 12px;font-family:Segoe UI,Arial,sans-serif">'
        '<table role="presentation" width="100%" style="max-width:520px;margin:0 auto;background:#141418;'
        'border:1px solid #26262c;border-radius:14px;overflow:hidden"><tr><td style="padding:0">'
        '<div style="padding:18px 28px;border-bottom:3px solid #bf5d6f;color:#ffffff;font-weight:800;'
        'letter-spacing:3px;font-size:14px">GETWHEELZ</div>'
        f'<div style="padding:28px"><h1 style="margin:0 0 16px;color:#ffffff;font-size:22px">{escape(heading)}</h1>{body}'
        + (
            f'<table role="presentation" style="margin:6px 0 18px;border-top:1px solid #26262c;width:100%">{rows}</table>'
            if rows
            else ""
        )
        + (
            f'<p style="margin:18px 0"><a href="{escape(button[1])}" style="display:inline-block;padding:12px 24px;'
            f'background:#bf5d6f;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:600">{escape(button[0])}</a></p>'
            if button
            else ""
        )
        + (
            f'<p style="margin:0;color:#8b8b96;font-size:13px;line-height:1.6">{escape(note)}</p>'
            if note
            else ""
        )
        + "</div></td></tr></table></div>"
    )
    return "\n".join(text), html


def notify_signup(name, email, role):
    """Welcome email after a new account is created."""
    try:
        label = ROLE_LABELS.get(role, "member")
        step = ROLE_NEXT_STEP.get(role, "")
        text, html = _layout(
            f"Welcome to Getwheelz, {name}!",
            [
                (
                    f"Your {label} account is ready.",
                    f"Your <b>{escape(label)}</b> account is ready.",
                ),
                (step, escape(step)),
            ],
            button=("Open Getwheelz", _base_url()),
            note=f"You signed up with {email}. If this was not you, you can ignore this email.",
        )
        _deliver(email, f"Welcome to Getwheelz, {name}", text, html)
    except Exception:
        logging.exception("Could not prepare the welcome email")


def notify_login(name, email, method="password"):
    """ "New sign-in" notice after a successful login."""
    try:
        minutes = current_app.config.get("MAIL_LOGIN_COOLDOWN_MINUTES", 0)
        if minutes:
            with _last_login_lock:
                last = _last_login_mail.get(email)
                if last and time.monotonic() - last < minutes * 60:
                    return
                _last_login_mail[email] = time.monotonic()
        text, html = _layout(
            "New sign-in to your account",
            [
                (
                    f"Hi {name}, we noticed a sign-in to your Getwheelz account.",
                    f"Hi {escape(name)}, we noticed a sign-in to your Getwheelz account.",
                )
            ],
            details=[("Method", method)] + _who(),
            button=("Secure my account", _link("auth.forgot_password")),
            note="If this was you, there is nothing to do. If it was not, reset your password right away.",
        )
        _deliver(email, "New sign-in to your Getwheelz account", text, html)
    except Exception:
        logging.exception("Could not prepare the sign-in email")


def notify_password_changed(name, email, first_time=False, via="your profile"):
    """Confirmation after a password was changed (or set for the first time)."""
    try:
        what = "set" if first_time else "changed"
        text, html = _layout(
            f"Your password was {what}",
            [
                (
                    f"Hi {name}, the password for your Getwheelz account was just {what} using {via}.",
                    f"Hi {escape(name)}, the password for your Getwheelz account was just {what} using {escape(via)}.",
                )
            ],
            details=_who(),
            button=("This was not me", _link("auth.forgot_password")),
            note="If you did this, you can ignore this email. If not, reset your password right away.",
        )
        _deliver(email, f"Your Getwheelz password was {what}", text, html)
    except Exception:
        logging.exception("Could not prepare the password-changed email")