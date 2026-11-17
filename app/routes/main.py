import json
import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import appeals, inbox_ui, limiter, report_rules, vehicles
from app import booking_rules as rules
from app.db import get_db_connection
from app.utils import admin_access_required

main_bp = Blueprint('main', __name__)

# where each kind of account lands after login (same targets as the login route)
ROLE_HOME = {
    'admin': 'dashboard.admin',
    'customer': 'customer.home',
    'owner': 'dashboard.owner',
    'mechanic': 'mechanics.home',
}

# Fixed categories for account reports; checked reasons are stored as the subject.
REPORT_CATEGORIES = {
    'scam_fraud': 'Scam or fraud',
    'harassment': 'Harassment / abuse',
    'fake_info': 'Fake information',
    'spam': 'Spam',
    'other': 'Something else',
}

# Fixed categories for workshop reports; checked reasons are stored as the subject.
WORKSHOP_REPORT_CATEGORIES = {
    'scam_fraud': 'Scam or fraud',
    'fake_info': 'Fake information',
    'poor_service': 'Poor service experience',
    'overcharged': 'Overcharging',
    'unlicensed': 'Suspected unlicensed work',
    'unsafe': 'Unsafe practices',
    'other': 'Something else',
}

# Keys that render in the report form as checkboxes, so templates share one list.
REPORT_CATEGORY_CHOICES = list(REPORT_CATEGORIES.items())
WORKSHOP_REPORT_CATEGORY_CHOICES = list(WORKSHOP_REPORT_CATEGORIES.items())

# Fixed categories for leave-workshop requests; checked reasons are stored with the request.
LEAVE_REASON_CATEGORIES = {
    'another_workshop': 'Another workshop',
    'relocation': 'Relocating',
    'schedule': 'Schedule conflicts',
    'workload': 'Workload',
    'expectations': 'Expectations gap',
    'other': 'Something else',
}
LEAVE_REASON_CATEGORY_CHOICES = list(LEAVE_REASON_CATEGORIES.items())


def _report_subject(reasons, categories):
    """Join checked reason keys into the stored subject (column is 150 chars)."""
    labels = [categories[r] for r in reasons if r in categories]
    return ', '.join(labels)[:150]


def _parse_workshop_report(body):
    """Body of a workshop report stores {w_id, details} as JSON; tolerate legacy
    text bodies (e.g. rows written before this format) by falling back to raw text."""
    try:
        data = json.loads(body)
        if isinstance(data, dict) and isinstance(data.get('w_id'), int):
            return data['w_id'], str(data.get('details', ''))
    except (ValueError, TypeError):
        pass
    return None, body


# ---------------------------------------------------------------------------
# Report lifecycle
#
#   filed ---> (open) ---> verified  (warning or suspension)  |  dismissed
#
# The report itself stays a row in `messages` (target_role 'account_report' /
# 'workshop_report'); its outcome is a row in report_resolution (no row = open).
# People are told what is happening through two kinds of system mail, both shown
# in the Reports section rather than Notices:
#   'report_update' -> to the REPORTER: received, then the outcome
#   'report_notice' -> to the REPORTED person, only once a report is verified
# The reported person never learns who reported them, and is not told about a
# report that was dismissed or is still open.
# ---------------------------------------------------------------------------
REPORT_OUTCOMES = ('warn', 'suspend', 'dismiss')
REPORT_MAIL_KINDS = ('report_update', 'report_notice')
# admin sub-type -> the one user role it moderates
ADMIN_DOMAIN_ROLE = {
    'customer_manager': 'customer',
    'owner_workshop_manager': 'owner',
    'mechanic_manager': 'mechanic',
}


def _notify(cur, recipient_u_id, kind, subject, body, ref=None):
    """Queue a system mail (no sender) for one person. ``ref`` = (ref_type, ref_id) links the mail to
    something the reader can act on, such as the report they are asked to respond to."""
    ref_type, ref_id = ref if ref else (None, None)
    cur.execute("""
        INSERT INTO messages (sender_u_id, recipient_u_id, target_role, subject, body, ref_type, ref_id)
        VALUES (NULL, %s, %s, %s, %s, %s, %s)
    """, (recipient_u_id, kind, subject[:150], body[:2000], ref_type, ref_id))


def _back_to_inbox():
    """Send the reporter back where they came from, falling back to the inbox."""
    ref = request.referrer
    if ref and ref.startswith(request.host_url):
        return redirect(ref)
    return redirect(url_for('main.inbox'))


def _came_from_this_site():
    """True when the visitor clicked a link on this site (logo, footer Home) rather than opening it fresh."""
    ref = request.referrer
    return bool(ref) and ref.startswith(request.host_url)


@main_bp.route('/')
def index():
    # Someone who is already logged in and just opened the website (typed the address, used a bookmark,
    # reopened the browser) goes straight to their own home page. Clicking the logo inside the site
    # still shows this landing page.
    role = session.get('role')
    if session.get('user_id') and role in ROLE_HOME and not _came_from_this_site():
        return redirect(url_for(ROLE_HOME[role]))


    # ?vehicle=car|two_wheeler is how the landing page's first step is answered; it is remembered so
    # the rest of the site (search, workshop pages, booking) agrees with it.
    vehicle = vehicles.chosen_vehicle(remember=True)
    serves_filter = ""
    if vehicle == vehicles.CAR:
        serves_filter = "AND serves_cars"
    elif vehicle == vehicles.TWO_WHEELER:
        serves_filter = "AND serves_two_wheelers"

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT w_id, name, address, latitude, longitude
        FROM workshop
        WHERE status = 'approved'
          {serves_filter}
          AND latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY w_id DESC
        LIMIT 50
    """)
    workshops = cur.fetchall()

    stats = _landing_stats(cur)
    cur.close()
    conn.close()
    return render_template('index.html', workshops=workshops, stats=stats)


def _landing_stats(cur):
    cur.execute("""
        SELECT (SELECT COUNT(*) FROM workshop WHERE status = 'approved') AS workshops,
            (SELECT COUNT(*) FROM mechanic WHERE w_id IS NOT NULL) AS mechanics,
            (SELECT COUNT(*) FROM service) AS services,
            (SELECT COUNT(*) FROM booking WHERE status = 'completed') AS jobs
    """)
    return cur.fetchone()

@main_bp.route('/about')
def about():
    conn = get_db_connection()
    cur = conn.cursor()
    stats = _landing_stats(cur)
    cur.close()
    conn.close()
    return render_template('about.html', stats=stats)

@main_bp.route('/contact', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def contact():
    if request.method == 'POST':
        # trim and cap everything to the size of its database column
        name = ' '.join(request.form.get('name', '').split())[:100]
        email = request.form.get('email', '').strip()[:100]
        subject = ' '.join(request.form.get('subject', '').split())[:150] or None
        message = request.form.get('message', '').strip()[:2000]

        if not name or not message or '@' not in email or any(ch.isspace() for ch in email):
            flash('Please enter your name, a valid email and a message.', 'error')
            return redirect(url_for('main.contact'))

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO feedback (name, email, subject, message) VALUES (%s, %s, %s, %s)",
                    (name, email, subject, message)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            logging.exception('Could not save a contact message')
            flash('Something went wrong and your message was not sent. Please try again.', 'error')
            return redirect(url_for('main.contact'))
        finally:
            conn.close()

        flash('Message sent — thank you for reaching out!', 'success')
        return redirect(url_for('main.contact'))

    # signed-in visitors do not have to retype their name and email
    prefill = {}
    if session.get('user_id'):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT name, email FROM users WHERE u_id = %s", (session['user_id'],))
                row = cur.fetchone()
                if row:
                    prefill = {'name': row['name'], 'email': row['email']}
        finally:
            conn.close()

    cfg = current_app.config
    conn = get_db_connection()
    cur = conn.cursor()
    stats = _landing_stats(cur)
    cur.close()
    conn.close()
    return render_template(
        'contact.html',
        prefill=prefill,
        stats=stats,
        contact_email=cfg.get('CONTACT_EMAIL'),
        contact_phone=cfg.get('CONTACT_PHONE'),
        contact_location=cfg.get('CONTACT_LOCATION'),
    )


@main_bp.route('/sitemap.xml')
def sitemap():
    """Static sitemap of public pages. Authenticated areas (dashboard, inbox, bookings,
    customer, mechanic) are intentionally excluded."""
    pages = [
        url_for('main.index', _external=True),
        url_for('main.about', _external=True),
        url_for('main.contact', _external=True),
        url_for('workshops.search', _external=True),
        url_for('legal.terms', _external=True),
        url_for('legal.privacy', _external=True),
        url_for('legal.owner_agreement', _external=True),
    ]
    urls = ''.join('<url><loc>%s</loc></url>' % p for p in pages)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls + '\n</urlset>\n'
    )
    return current_app.response_class(xml, mimetype='application/xml')


@main_bp.route('/robots.txt')
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /auth/\n"
        "Disallow: /dashboard/\n"
        "Disallow: /customer/\n"
        "Disallow: /bookings/\n"
        "Disallow: /mechanics/\n"
        "Disallow: /inbox\n"
        "Disallow: /legal/accept\n"
        "Sitemap: " + url_for('main.sitemap', _external=True) + "\n"
    )
    return current_app.response_class(body, mimetype='text/plain')


@main_bp.route('/tour/done', methods=['POST'])
def tour_done():
    """NEO's first-login tour was finished or skipped: remember it so it is not shown again."""
    if 'user_id' not in session:
        return jsonify(ok=False), 401
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET tour_seen = TRUE WHERE u_id = %s", (session['user_id'],))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logging.exception('Could not save tour_seen')
        return jsonify(ok=False), 500
    session['tour_seen'] = True
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Per-viewer notice state
#
# A notice is a row in `messages`. Direct mail (recipient_u_id set) has exactly
# one recipient, so messages.is_read belongs to them. A broadcast
# (recipient_u_id NULL, target_role 'all' or a role name) is ONE shared row for
# every recipient, so its read/deleted state is kept per viewer in
# inbox_message_state instead -- one person reading or deleting a broadcast must
# never change what anyone else sees.
# ---------------------------------------------------------------------------
_NOTICE_STATE_JOIN = "LEFT JOIN inbox_message_state s ON s.msg_id = m.msg_id AND s.u_id = %s"
_NOTICE_READ_SQL = ("(CASE WHEN m.recipient_u_id IS NULL THEN s.read_at IS NOT NULL "
                    "ELSE COALESCE(m.is_read, FALSE) END)")
# Which notices the viewer can see: params are (user_id, role); the state join's
# own user_id parameter comes first in the statement.
_NOTICE_VISIBLE_SQL = """(m.recipient_u_id = %s
                 OR (m.recipient_u_id IS NULL AND m.target_role IN ('all', %s)))
          AND COALESCE(m.target_role, '') NOT IN ('account_report', 'report_update', 'report_notice')
          AND s.deleted_at IS NULL"""


def _mark_broadcast_read(cur, user_id, msg_id):
    cur.execute("""
        INSERT INTO inbox_message_state (u_id, msg_id, read_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (u_id, msg_id)
        DO UPDATE SET read_at = COALESCE(inbox_message_state.read_at, NOW())
    """, (user_id, msg_id))


def _hide_broadcast(cur, user_id, msg_id):
    """Delete a broadcast for THIS viewer only (a hidden broadcast counts as read)."""
    cur.execute("""
        INSERT INTO inbox_message_state (u_id, msg_id, read_at, deleted_at)
        VALUES (%s, %s, NOW(), NOW())
        ON CONFLICT (u_id, msg_id)
        DO UPDATE SET deleted_at = COALESCE(inbox_message_state.deleted_at, NOW()),
                      read_at = COALESCE(inbox_message_state.read_at, NOW())
    """, (user_id, msg_id))



# ---------------------------------------------------------------------------
# Inbox sections (Phase 5). Each section's items belong to the viewer through one of these scopes;
# the bottom bar's "Mark all as read" / "Delete all" act only on the section being viewed, and the
# per-item read/delete checks reuse the SAME scope so they can never disagree with what is listed.
# Every scope takes the viewer's user id as its single %s.
# ---------------------------------------------------------------------------
INBOX_SECTIONS = ('notices', 'updates', 'joins', 'leaves', 'reports')

_BOOKING_SCOPE = {
    'owner': """FROM booking b JOIN workshop w ON w.w_id = b.w_id
                JOIN owner o ON o.o_id = w.o_id WHERE o.u_id = %s""",
    'customer': """FROM booking b JOIN customer c ON c.c_id = b.c_id WHERE c.u_id = %s""",
    'mechanic': """FROM booking b JOIN mechanic m ON m.m_id = b.assigned_m_id WHERE m.u_id = %s""",
}
_JOIN_SCOPE = {
    'owner': """FROM join_request jr JOIN workshop w ON w.w_id = jr.w_id
                JOIN owner o ON o.o_id = w.o_id WHERE o.u_id = %s""",
    'mechanic': """FROM join_request jr JOIN mechanic m ON m.m_id = jr.m_id WHERE m.u_id = %s""",
}
_LEAVE_SCOPE = {
    'owner': """FROM mechanic m JOIN workshop w ON w.w_id = m.w_id JOIN owner o ON o.o_id = w.o_id
                WHERE o.u_id = %s
                  AND (m.leave_requested_at IS NOT NULL
                       OR m.leave_rejected_at > NOW() - INTERVAL '7 days')""",
}
# which items of each kind may be hidden: resolved ones only, never something still waiting on an answer
_BOOKING_RESOLVED = "AND b.status IN ('completed', 'cancelled')"
_JOIN_RESOLVED = "AND jr.status <> 'pending'"
_LEAVE_RESOLVED = "AND m.leave_rejected_at IS NOT NULL"


def _mark_section_read(cur, user_id, role, section):
    """Mark everything in ONE section as read for this viewer. Returns how many rows changed, or
    None for an unknown section."""
    if section == 'notices':
        cur.execute("""
            UPDATE messages SET is_read = TRUE
            WHERE is_read = FALSE AND recipient_u_id = %s AND target_role IS NULL
        """, (user_id,))
        n = cur.rowcount
        cur.execute("""
            INSERT INTO inbox_message_state (u_id, msg_id, read_at)
            SELECT %s, m.msg_id, NOW() FROM messages m
            WHERE m.recipient_u_id IS NULL AND m.target_role IN ('all', %s)
            ON CONFLICT (u_id, msg_id)
            DO UPDATE SET read_at = COALESCE(inbox_message_state.read_at, NOW())
            WHERE inbox_message_state.read_at IS NULL
        """, (user_id, role))
        return n + cur.rowcount
    if section == 'reports':
        cur.execute("""
            UPDATE messages SET is_read = TRUE
            WHERE is_read = FALSE AND recipient_u_id = %s AND target_role = ANY(%s)
        """, (user_id, list(REPORT_MAIL_KINDS)))
        n = cur.rowcount
        if role == 'admin':
            cur.execute("UPDATE feedback SET is_read = TRUE WHERE is_read = FALSE")
            n += cur.rowcount
            cur.execute(
                "UPDATE messages SET is_read = TRUE WHERE is_read = FALSE AND target_role = ANY(%s)",
                (list(_REPORT_KINDS),),
            )
            n += cur.rowcount
        return n
    scopes = {'updates': ('booking', _BOOKING_SCOPE, 'b.b_id'),
              'joins': ('join_request', _JOIN_SCOPE, 'jr.jr_id'),
              'leaves': ('leave_request', _LEAVE_SCOPE, 'm.m_id')}
    if section not in scopes:
        return None
    item_type, by_role, id_col = scopes[section]
    scope = by_role.get(role)
    if not scope:
        return 0
    cur.execute(f"""
        INSERT INTO inbox_read_state (u_id, item_type, item_id)
        SELECT %s, %s, {id_col} {scope}
        ON CONFLICT (u_id, item_type, item_id) DO NOTHING
    """, (user_id, item_type, user_id))
    return cur.rowcount


def _delete_section(cur, user_id, role, section):
    """Delete (for this viewer) everything deletable in ONE section. Items still waiting on the
    viewer (a pending booking or request) and evidence admins need (reports filed to them) stay.
    Returns how many were removed, or None for an unknown section."""
    if section == 'notices':
        cur.execute(
            "DELETE FROM messages WHERE recipient_u_id = %s AND target_role IS NULL", (user_id,)
        )
        n = cur.rowcount
        cur.execute("""
            INSERT INTO inbox_message_state (u_id, msg_id, read_at, deleted_at)
            SELECT %s, m.msg_id, NOW(), NOW() FROM messages m
            WHERE m.recipient_u_id IS NULL AND m.target_role IN ('all', %s)
              AND NOT EXISTS (SELECT 1 FROM inbox_message_state x
                              WHERE x.u_id = %s AND x.msg_id = m.msg_id
                                AND x.deleted_at IS NOT NULL)
            ON CONFLICT (u_id, msg_id)
            DO UPDATE SET deleted_at = NOW(),
                          read_at = COALESCE(inbox_message_state.read_at, NOW())
        """, (user_id, role, user_id))
        return n + cur.rowcount
    if section == 'reports':
        cur.execute(
            "DELETE FROM messages WHERE recipient_u_id = %s AND target_role = ANY(%s)",
            (user_id, list(REPORT_MAIL_KINDS)),
        )
        n = cur.rowcount
        if role != 'admin':
            # reports the viewer filed: plain ones, and resolved account/workshop reports (an
            # unresolved one is evidence under review, exactly as for single deletes)
            cur.execute("""
                DELETE FROM messages m
                WHERE m.sender_u_id = %s
                  AND (m.target_role = 'report'
                       OR (m.target_role IN ('account_report', 'workshop_report')
                           AND EXISTS (SELECT 1 FROM report_resolution rr WHERE rr.msg_id = m.msg_id)))
            """, (user_id,))
            n += cur.rowcount
        return n
    scopes = {'updates': ('booking', _BOOKING_SCOPE, 'b.b_id', _BOOKING_RESOLVED),
              'joins': ('join_request', _JOIN_SCOPE, 'jr.jr_id', _JOIN_RESOLVED),
              'leaves': ('leave_request', _LEAVE_SCOPE, 'm.m_id', _LEAVE_RESOLVED)}
    if section not in scopes:
        return None
    item_type, by_role, id_col, resolved = scopes[section]
    scope = by_role.get(role)
    if not scope:
        return 0
    cur.execute(f"""
        INSERT INTO inbox_dismissal (u_id, item_type, item_id)
        SELECT %s, %s, {id_col} {scope} {resolved}
        ON CONFLICT (u_id, item_type, item_id) DO NOTHING
    """, (user_id, item_type, user_id))
    return cur.rowcount


def login_banner(cur, user_id, role):
    """Important notices to show once as a banner right after login (spec section 8).

    Returns ``[{id, subject, message, time}, ...]`` (newest first, at most 3, sent in the last 30
    days) and marks each as shown for THIS viewer in the same transaction, so a notice banners once
    per person whether or not they dismiss it. Direct and broadcast notices both work, because the
    marker lives in inbox_message_state, not on the shared message row. Does not commit.
    """
    cur.execute(f"""
        SELECT m.msg_id AS id, m.subject, m.body AS message, m.sent_at AS time
        FROM messages m
        {_NOTICE_STATE_JOIN}
        WHERE m.category = 'important'
          AND {_NOTICE_VISIBLE_SQL}
          AND s.banner_seen_at IS NULL
          AND m.sent_at > NOW() - INTERVAL '30 days'
        ORDER BY m.sent_at DESC LIMIT 3
    """, (user_id, user_id, role))
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        cur.execute("""
            INSERT INTO inbox_message_state (u_id, msg_id, banner_seen_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (u_id, msg_id)
            DO UPDATE SET banner_seen_at = COALESCE(inbox_message_state.banner_seen_at, NOW())
        """, (user_id, r['id']))
    return rows


@main_bp.route('/inbox', methods=['GET', 'POST'])
def inbox():
    if not session.get('user_id'):
        flash('Please log in to view your inbox.', 'error')
        return redirect(url_for('main.index'))

    user_id = session.get('user_id')
    role = session.get('role')
    # Only the main admin may send mail from inside the inbox; every other
    # account (sub-admins included) gets a read-only inbox.
    is_main_admin = session.get('admin_type') == 'main'

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST' and is_main_admin:
        target = request.form.get('target', 'all')
        subject = request.form.get('subject', '').strip()[:150]
        body = request.form.get('body', '').strip()[:2000]
        # a forged or system-only category falls back to General (app/inbox_ui.py)
        category = inbox_ui.clean_category(request.form.get('category'))

        if not subject or not body:
            flash('Please provide both a subject and message body.', 'error')
            return redirect(url_for('main.inbox'))

        try:
            if target in ('all', 'customer', 'owner', 'mechanic', 'admin'):
                cur.execute("""
                    INSERT INTO messages (sender_u_id, target_role, subject, body, category)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, target, subject, body, category))
            elif target.startswith('user:'):
                recip_id = int(target.split(':', 1)[1])
                cur.execute("""
                    INSERT INTO messages (sender_u_id, recipient_u_id, subject, body, category)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, recip_id, subject, body, category))
            conn.commit()
            flash('Message broadcasted/sent successfully!', 'success')
        except Exception:
            conn.rollback()
            logging.exception('Could not send inbox message')
            flash('Failed to send message.', 'error')
        return redirect(url_for('main.inbox'))

    items = []
    if role == 'admin':
        cur.execute("SELECT f_id AS id, name, email, subject, message, submitted_at AS time, is_read FROM feedback ORDER BY submitted_at DESC LIMIT 50")
        items = cur.fetchall()
    elif role == 'owner':
        cur.execute("""
            SELECT b.b_id AS id, 'booking' AS type, b.status, b.requested_time AS time,
                   (SELECT public_booking_customer_name(b.b_id)) AS sender_name, sc.s_name AS detail, NULL AS reason,
                   EXISTS (SELECT 1 FROM inbox_read_state r
                       WHERE r.u_id = %s AND r.item_type = 'booking'
                         AND r.item_id = b.b_id) AS is_read
            FROM booking b
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            JOIN workshop w ON b.w_id = w.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM inbox_dismissal d
                  WHERE d.u_id = %s AND d.item_type = 'booking' AND d.item_id = b.b_id)
            UNION ALL
            SELECT jr.jr_id AS id, 'join_request' AS type, jr.status, jr.created_at AS time,
                   u.name AS sender_name, w.name AS detail, NULL AS reason,
                   EXISTS (
                       SELECT 1 FROM inbox_read_state r
                       WHERE r.u_id = %s AND r.item_type = 'join_request'
                         AND r.item_id = jr.jr_id) AS is_read
            FROM join_request jr
            JOIN mechanic m ON jr.m_id = m.m_id
            JOIN users u ON m.u_id = u.u_id
            JOIN workshop w ON jr.w_id = w.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM inbox_dismissal d
                  WHERE d.u_id = %s AND d.item_type = 'join_request'
                    AND d.item_id = jr.jr_id)
            UNION ALL
            SELECT m.m_id AS id, 'leave_request' AS type,
                   CASE WHEN m.leave_rejected_at IS NOT NULL THEN 'rejected' ELSE 'pending' END AS status,
                   COALESCE(m.leave_requested_at, m.leave_rejected_at) AS time,
                   u.name AS sender_name, w.name AS detail, m.leave_reason AS reason,
                   EXISTS (
                       SELECT 1 FROM inbox_read_state r
                       WHERE r.u_id = %s AND r.item_type = 'leave_request'
                         AND r.item_id = m.m_id) AS is_read
            FROM mechanic m
            JOIN users u ON m.u_id = u.u_id
            JOIN workshop w ON m.w_id = w.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM inbox_dismissal d
                  WHERE d.u_id = %s AND d.item_type = 'leave_request'
                    AND d.item_id = m.m_id)
              AND (m.leave_requested_at IS NOT NULL
                   OR m.leave_rejected_at > NOW() - INTERVAL '7 days')
            ORDER BY time DESC LIMIT 50
        """, (user_id,) * 9)
        items = cur.fetchall()
    elif role == 'mechanic':
        cur.execute("""
            SELECT b.b_id AS id, 'job' AS type, b.status, b.requested_time AS time,
                   w.name AS sender_name, sc.s_name AS detail,
                   EXISTS (SELECT 1 FROM inbox_read_state r
                       WHERE r.u_id = %s AND r.item_type = 'booking'
                         AND r.item_id = b.b_id) AS is_read
            FROM booking b
            JOIN mechanic m ON b.assigned_m_id = m.m_id
            JOIN workshop w ON b.w_id = w.w_id
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE m.u_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM inbox_dismissal d
                  WHERE d.u_id = %s AND d.item_type = 'booking' AND d.item_id = b.b_id)
            UNION ALL
            SELECT jr.jr_id AS id, 'join_request' AS type, jr.status, jr.created_at AS time,
                   w.name AS sender_name, 'Join request update' AS detail,
                   EXISTS (
                       SELECT 1 FROM inbox_read_state r
                       WHERE r.u_id = %s AND r.item_type = 'join_request'
                         AND r.item_id = jr.jr_id) AS is_read
            FROM join_request jr
            JOIN mechanic m ON jr.m_id = m.m_id
            JOIN workshop w ON jr.w_id = w.w_id
            WHERE m.u_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM inbox_dismissal d
                  WHERE d.u_id = %s AND d.item_type = 'join_request'
                    AND d.item_id = jr.jr_id)
            ORDER BY time DESC LIMIT 50
        """, (user_id,) * 6)
        items = cur.fetchall()
    elif role == 'customer':
        cur.execute("""
            SELECT b.b_id AS id, 'booking' AS type, b.status, b.requested_time AS time,
                   w.name AS sender_name, sc.s_name AS detail, NULL AS reason,
                   EXISTS (SELECT 1 FROM inbox_read_state r
                       WHERE r.u_id = %s AND r.item_type = 'booking'
                         AND r.item_id = b.b_id) AS is_read
            FROM booking b
            JOIN customer c ON b.c_id = c.c_id
            JOIN workshop w ON b.w_id = w.w_id
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE c.u_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM inbox_dismissal d
                  WHERE d.u_id = %s AND d.item_type = 'booking' AND d.item_id = b.b_id)
            ORDER BY time DESC LIMIT 50
        """, (user_id,) * 3)
        items = cur.fetchall()

    # Direct / broadcast messages
    cur.execute(f"""
        SELECT m.msg_id AS id, m.subject, m.body AS message, m.sent_at AS time,
               {_NOTICE_READ_SQL} AS is_read,
               m.recipient_u_id AS recipient_id,
               COALESCE(u.name, 'System Administrator') AS sender_name, m.target_role,
               m.category, m.ref_type, m.ref_id
        FROM messages m
        LEFT JOIN users u ON m.sender_u_id = u.u_id
        {_NOTICE_STATE_JOIN}
        WHERE {_NOTICE_VISIBLE_SQL}
        ORDER BY time DESC LIMIT 50
    """, (user_id, user_id, role))
    msg_items = cur.fetchall()

    # Reports: problem reports and account reports live in messages.
    # - 'report'           -> a user filing a problem to the admins (target_role='report')
    # - 'account_report'   -> a user reporting another account (target_role='account_report',
    #                         sender = reporter, recipient = reported user)
    # - 'workshop_report'  -> a user reporting a workshop (target_role='workshop_report',
    #                         sender = reporter, no recipient = workshop id in JSON body)
    # Admins see everything; everyone else sees only what they filed.
    reports = []
    account_reports = []
    reported_accounts = []
    workshop_reports = []
    if role == 'admin':
        cur.execute("""
            SELECT m.msg_id AS id, m.target_role AS kind, m.subject, m.body AS message, m.sent_at AS time,
                   COALESCE(u.name, 'System Administrator') AS sender_name
            FROM messages m
            LEFT JOIN users u ON m.sender_u_id = u.u_id
            WHERE m.target_role = 'report'
            ORDER BY m.sent_at DESC LIMIT 50
        """)
        account_reports = cur.fetchall()

        cur.execute("""
            SELECT m.msg_id AS id, m.subject, m.body AS message, m.sent_at AS time,
                   COALESCE(rp.name, 'Unknown') AS reporter_name,
                   rp.u_id AS reporter_u_id, rp.role AS reporter_role,
                   COALESCE(rd.name, 'Deleted account') AS reported_name,
                   rd.u_id AS reported_u_id, rd.role AS reported_role,
                   rd.is_suspended AS reported_suspended,
                   rr.status AS res_status, rr.outcome AS res_outcome, rr.note AS res_note,
                   rr.handled_at AS res_at, hu.name AS res_by
            FROM messages m
            LEFT JOIN users rp ON m.sender_u_id = rp.u_id
            LEFT JOIN users rd ON m.recipient_u_id = rd.u_id
            LEFT JOIN report_resolution rr ON rr.msg_id = m.msg_id
            LEFT JOIN users hu ON rr.handled_by = hu.u_id
            WHERE m.target_role = 'account_report'
            ORDER BY (rr.msg_id IS NOT NULL), m.sent_at DESC LIMIT 50
        """)
        reported_accounts = [dict(row) for row in cur.fetchall()]

        # Which reported accounts may the current admin suspend? The main admin may
        # suspend anyone; a manager only within their assigned role domain.
        manager_type = session.get('admin_type')
        allowed_roles = ADMIN_DOMAIN_ROLE
        for r in reported_accounts:
            # Abmins themselves can never be banned via this UI (the suspension
            # route refuses admin-role targets), so never offer the button.
            r['can_ban'] = (
                r.get('reported_role') != 'admin'
                and (manager_type == 'main' or allowed_roles.get(manager_type) == r.get('reported_role'))
            )
            # resolving (warn / dismiss) follows the same domain rule as banning
            r['can_resolve'] = (
                r.get('res_status') is None
                and (manager_type == 'main' or allowed_roles.get(manager_type) == r.get('reported_role'))
            )

        cur.execute("""
            SELECT m.msg_id AS id, m.subject, m.body AS message, m.sent_at AS time,
                   COALESCE(rp.name, 'Unknown') AS reporter_name,
                   rp.u_id AS reporter_u_id, rp.role AS reporter_role,
                   rr.status AS res_status, rr.outcome AS res_outcome, rr.note AS res_note,
                   rr.handled_at AS res_at, hu.name AS res_by
            FROM messages m
            LEFT JOIN users rp ON m.sender_u_id = rp.u_id
            LEFT JOIN report_resolution rr ON rr.msg_id = m.msg_id
            LEFT JOIN users hu ON rr.handled_by = hu.u_id
            WHERE m.target_role = 'workshop_report'
            ORDER BY (rr.msg_id IS NOT NULL), m.sent_at DESC LIMIT 50
        """)
        workshop_reports = [dict(row) for row in cur.fetchall()]
        for r in workshop_reports:
            r['w_id'], r['details'] = _parse_workshop_report(r['message'])
            r['can_resolve'] = (r.get('res_status') is None
                                and session.get('admin_type') in ('main', 'owner_workshop_manager'))
        ws_ids = [r['w_id'] for r in workshop_reports if r.get('w_id')]
        if ws_ids:
            cur.execute("""
                SELECT w.w_id, w.name, u.u_id AS owner_uid, u.name AS owner_name
                FROM workshop w
                JOIN owner o ON w.o_id = o.o_id
                JOIN users u ON o.u_id = u.u_id
                WHERE w.w_id = ANY(%s)
            """, (ws_ids,))
            workshops_by_id = {row['w_id']: dict(row) for row in cur.fetchall()}
            for r in workshop_reports:
                r['workshop'] = workshops_by_id.get(r.get('w_id'))
    else:
        cur.execute("""
            SELECT m.msg_id AS id, m.target_role AS kind, m.subject, m.body AS message,
                   m.sent_at AS time, COALESCE(rd.name, 'Deleted account') AS reported_name,
                   rr.status AS res_status, rr.outcome AS res_outcome, rr.handled_at AS res_at
            FROM messages m
            LEFT JOIN users rd ON m.recipient_u_id = rd.u_id
            LEFT JOIN report_resolution rr ON rr.msg_id = m.msg_id
            WHERE m.sender_u_id = %s AND m.target_role IN ('report', 'account_report', 'workshop_report')
            ORDER BY m.sent_at DESC LIMIT 50
        """, (user_id,))
        reports = [dict(row) for row in cur.fetchall()]
        # workshop reports carry their target and details in the JSON body — unpack
        # them so the reporter sees the same info admins see
        ws_ids = []
        for r in reports:
            if r.get('kind') == 'workshop_report':
                r['w_id'], r['details'] = _parse_workshop_report(r.get('message'))
                if r.get('w_id'):
                    ws_ids.append(r['w_id'])
        if ws_ids:
            cur.execute("SELECT w_id, name FROM workshop WHERE w_id = ANY(%s)", (ws_ids,))
            ws_map = {row['w_id']: row['name'] for row in cur.fetchall()}
            for r in reports:
                if r.get('kind') == 'workshop_report':
                    r['workshop_name'] = ws_map.get(r.get('w_id'))

    # Report mail: acknowledgements/outcomes for reports this user filed, and
    # notices that a report about them was verified.
    cur.execute("""
        SELECT m.msg_id AS id, m.target_role AS kind, m.subject, m.body AS message,
               m.sent_at AS time, COALESCE(m.is_read, FALSE) AS is_read, m.ref_type, m.ref_id
        FROM messages m
        WHERE m.recipient_u_id = %s AND m.target_role IN ('report_update', 'report_notice')
        ORDER BY m.sent_at DESC LIMIT 50
    """, (user_id,))
    report_mail = [dict(row) for row in cur.fetchall()]

    # Extra detail for the update popups, fetched in one query per kind instead of widening the UNION
    # above: who is assigned, an open cancellation request, vehicle, payment; and for an owner the
    # workshop's mechanics (to assign) and each leave request's active jobs (to warn about).
    items = [dict(i) for i in items]
    mechanics = []
    booking_ids = [i['id'] for i in items if i.get('type') in ('booking', 'job')]
    if booking_ids:
        cur.execute("""
            SELECT b.b_id, b.assigned_m_id, mu.name AS mechanic_name, b.cancel_request_status,
                   b.cancel_request_reason, b.created_at, b.vehicle_description, b.vehicle_type,
                   b.payment_status, b.amount, b.cancelled_by
            FROM booking b
            LEFT JOIN mechanic mm ON mm.m_id = b.assigned_m_id
            LEFT JOIN users mu ON mu.u_id = mm.u_id
            WHERE b.b_id = ANY(%s)
        """, (booking_ids,))
        extra = {r['b_id']: dict(r) for r in cur.fetchall()}
        now = rules.now()
        for i in items:
            if i.get('type') in ('booking', 'job'):
                e = extra.get(i['id'], {})
                i['extra'] = e
                i['status_label'] = rules.label(i['status'])
                i['cancel_requested'] = (e.get('cancel_request_status') == rules.REQUEST_OPEN
                                         and i['status'] in rules.ACCEPTED_STATUSES)
                i['hours_left'] = (rules.hours_left(e['created_at'], now)
                                   if i['status'] == rules.PENDING and e.get('created_at') else None)
                # needs an answer from the owner: such items cannot be deleted from the inbox
                i['needs_action'] = i['status'] == rules.PENDING or i['cancel_requested']
                i['resolved'] = i['status'] in (rules.COMPLETED, rules.CANCELLED) and not i['cancel_requested']
    if role == 'owner':
        cur.execute("""
            SELECT m.m_id, u.name
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            JOIN workshop w ON m.w_id = w.w_id JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s ORDER BY u.name
        """, (user_id,))
        mechanics = [dict(r) for r in cur.fetchall()]
        leave_ids = [i['id'] for i in items if i.get('type') == 'leave_request']
        if leave_ids:
            cur.execute("""
                SELECT b.assigned_m_id AS m_id, b.b_id, b.status, b.requested_time, sc.s_name
                FROM booking b
                JOIN service s ON s.s_id = b.s_id
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE b.assigned_m_id = ANY(%s) AND b.status = ANY(%s)
                ORDER BY b.requested_time
            """, (leave_ids, list(rules.OPEN_STATUSES)))
            jobs_by_mechanic = {}
            for r in cur.fetchall():
                jobs_by_mechanic.setdefault(r['m_id'], []).append(dict(r))
            for i in items:
                if i.get('type') == 'leave_request':
                    i['active_jobs'] = jobs_by_mechanic.get(i['id'], [])

    # ---- Phase 6: review stage, evidence, response forms and appeals -------------------------------
    now = rules.now()
    msg_items = [dict(m) for m in msg_items]
    # 1) a reported person's response form: the report_notice that asked them to respond
    response_ids = [m['ref_id'] for m in report_mail if m.get('ref_type') == 'report_response']
    if response_ids:
        reviews = _load_reviews(cur, response_ids)
        for m in report_mail:
            if m.get('ref_type') == 'report_response':
                m['review'] = _review_view(reviews.get(m['ref_id']), now)
    # 2) an owner's rejection notice: can they still appeal? (one appeal per decision)
    appeal_ids = [m['ref_id'] for m in msg_items if m.get('ref_type') == 'listing_appeal']
    if appeal_ids and role == 'owner':
        cur.execute("""
            SELECT w.w_id, w.status, w.decided_at,
                   (SELECT MAX(a.created_at) FROM appeal a
                    WHERE a.u_id = %s AND a.kind = 'listing' AND a.w_id = w.w_id) AS last_appeal_at,
                   EXISTS (SELECT 1 FROM appeal a WHERE a.u_id = %s AND a.kind = 'listing'
                           AND a.w_id = w.w_id AND a.status = 'open') AS has_open
            FROM workshop w JOIN owner o ON o.o_id = w.o_id
            WHERE o.u_id = %s AND w.w_id = ANY(%s)
        """, (user_id, user_id, user_id, appeal_ids))
        listing_state = {r['w_id']: dict(r) for r in cur.fetchall()}
        for m in msg_items:
            if m.get('ref_type') == 'listing_appeal':
                st = listing_state.get(m['ref_id'])
                m['appeal'] = {
                    'w_id': m['ref_id'],
                    'open': bool(st and st['has_open']),
                    'can_appeal': bool(st and st['status'] == 'rejected' and appeals.can_appeal(
                        st['decided_at'], st['last_appeal_at'], st['has_open'])),
                    'state': st['status'] if st else None,
                }
    # 3) admins: the review stage and the evidence panel for each report, and the appeals queue
    appeals_list = []
    if role == 'admin':
        admin_type = session.get('admin_type')
        review_ids = [r['id'] for r in reported_accounts + workshop_reports]
        reviews = _load_reviews(cur, review_ids)
        for group, kind in ((reported_accounts, 'account_report'), (workshop_reports, 'workshop_report')):
            for r in group:
                r['kind'] = kind
                r['rv'] = _review_view(reviews.get(r['id']), now)
                r['can_sanction'] = r['rv']['verified']
                if r.get('res_status') is None and r.get('can_resolve'):
                    reported_uid = (r.get('workshop') or {}).get('owner_uid') if kind == 'workshop_report' \
                        else r.get('reported_u_id')
                    r['evidence'] = _evidence(cur, r['id'], r.get('reporter_u_id'), reported_uid)
        cur.execute("""
            SELECT a.ap_id AS id, a.kind, a.message, a.created_at AS time, a.status, a.decision_note,
                   a.reviewed_at, a.needs_second_reviewer, a.reviewer_type,
                   u.name AS appellant_name, u.role AS appellant_role, u.u_id AS appellant_u_id,
                   w.name AS workshop_name, w.rejection_reason, w.w_id,
                   du.name AS decided_by_name, rv.name AS reviewed_by_name
            FROM appeal a
            JOIN users u ON u.u_id = a.u_id
            LEFT JOIN workshop w ON w.w_id = a.w_id
            LEFT JOIN users du ON du.u_id = a.decided_by_admin
            LEFT JOIN users rv ON rv.u_id = a.reviewed_by
            WHERE a.reviewer_type = %s
            ORDER BY (a.status <> 'open'), a.created_at DESC LIMIT 50
        """, (admin_type,))
        appeals_list = [dict(r) for r in cur.fetchall()]
        for a in appeals_list:
            a['can_review'] = appeals.can_review(admin_type, a['reviewer_type'], a['status'])

    users_list = []
    if is_main_admin:
        cur.execute("SELECT u_id, name, email, role FROM users ORDER BY name")
        users_list = cur.fetchall()

    unread_count = _unread_mail_count(cur, user_id, role)
    # every notice the viewer can see is deletable (broadcasts are hidden per viewer)
    deletable_count = len(msg_items)

    # Per-section unread counts for the sidebar indicators. Only sections with
    # a per-viewer read state get one: notices (mail), join/leave cards, and
    # (for admins) contact-form feedback.
    joins_list = [i for i in items if i.get('type') == 'join_request'] if role in ('owner', 'mechanic') else []
    leaves_list = [i for i in items if i.get('type') == 'leave_request'] if role == 'owner' else []
    updates_list = [i for i in items if i.get('type') in ('booking', 'job')]
    panel_unread = {
        'notices': sum(1 for m in msg_items if not m.get('is_read')),
        'updates': sum(1 for i in updates_list if not i.get('is_read')),
        'joins': sum(1 for i in joins_list if not i.get('is_read')),
        'leaves': sum(1 for i in leaves_list if not i.get('is_read')),
        'reports': (sum(1 for f in items if not f.get('is_read')) if role == 'admin' else 0)
                   + sum(1 for r in report_mail if not r['is_read'])
                   + sum(1 for a in appeals_list if a['status'] == 'open'),
    }

    cur.close()
    conn.close()
    return render_template('inbox.html', items=items, msg_items=msg_items, role=role,
                           is_main_admin=is_main_admin, users_list=users_list,
                           reports=reports, account_reports=account_reports,
                           reported_accounts=reported_accounts,
                           workshop_reports=workshop_reports, report_mail=report_mail,
                           unread_count=unread_count, deletable_count=deletable_count,
                           panel_unread=panel_unread, mechanics=mechanics, appeals_list=appeals_list,
                           notice_categories=inbox_ui.admin_categories())


# message kinds that are reports filed *to the admins* (shared, admin-only)
_REPORT_KINDS = ('report', 'account_report', 'workshop_report')


def _unread_mail_count(cur, user_id, role):
    """Unread mail that "Mark all read" can clear: direct/broadcast messages, plus
    -- for admins -- unread contact-form feedback and unread user reports."""
    cur.execute(f"""
        SELECT COUNT(*) AS n FROM messages m
        {_NOTICE_STATE_JOIN}
        WHERE NOT {_NOTICE_READ_SQL}
          AND {_NOTICE_VISIBLE_SQL}
    """, (user_id, user_id, role))
    n = int(cur.fetchone()['n'])
    # report mail (acknowledgements, outcomes, notices about the user)
    cur.execute("""
        SELECT COUNT(*) AS n FROM messages
        WHERE recipient_u_id = %s AND target_role = ANY(%s) AND COALESCE(is_read, FALSE) = FALSE
    """, (user_id, list(REPORT_MAIL_KINDS)))
    n += int(cur.fetchone()['n'])
    if role == 'admin':
        cur.execute("SELECT COUNT(*) AS n FROM feedback WHERE is_read = FALSE")
        n += int(cur.fetchone()['n'])
        cur.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE is_read = FALSE AND target_role = ANY(%s)",
            (list(_REPORT_KINDS),),
        )
        n += int(cur.fetchone()['n'])
        # open appeals assigned to this admin's type wait for an answer
        cur.execute("SELECT COUNT(*) AS n FROM appeal WHERE status = 'open' AND reviewer_type = %s",
                    (session.get('admin_type'),))
        n += int(cur.fetchone()['n'])
    return n


def _inbox_unread_count(cur, user_id, role):
    """Everything that should light the navbar's red mail dot: unread mail plus
    requests still waiting on the user -- for owners pending bookings, mechanic
    join requests and leave requests; for mechanics newly assigned jobs. Shared by
    the navbar (context processor + JSON endpoint) so they cannot drift."""
    n = _unread_mail_count(cur, user_id, role)
    if role == 'owner':
        cur.execute("""
            SELECT
              (SELECT COUNT(*) FROM join_request jr
                 JOIN workshop w ON jr.w_id = w.w_id
                 JOIN owner o ON w.o_id = o.o_id
                WHERE o.u_id = %s AND jr.status = 'pending')
            + (SELECT COUNT(*) FROM mechanic m2
                 JOIN workshop w2 ON m2.w_id = w2.w_id
                 JOIN owner o2 ON w2.o_id = o2.o_id
                WHERE o2.u_id = %s AND m2.leave_requested_at IS NOT NULL)
            + (SELECT COUNT(*) FROM booking b
                 JOIN workshop w3 ON b.w_id = w3.w_id
                 JOIN owner o3 ON w3.o_id = o3.o_id
                WHERE o3.u_id = %s AND (b.status = 'pending'
                       OR (b.cancel_request_status = 'requested'
                           AND b.status IN ('confirmed', 'in_progress')))) AS n
        """, (user_id, user_id, user_id))
        n += int(cur.fetchone()['n'])
    elif role == 'mechanic':
        cur.execute("""
            SELECT COUNT(*) AS n FROM booking b
            JOIN mechanic m ON b.assigned_m_id = m.m_id
            WHERE m.u_id = %s AND b.status = 'confirmed'
        """, (user_id,))
        n += int(cur.fetchone()['n'])
    return n


@main_bp.route('/inbox/unread-count')
def inbox_unread_count():
    """JSON unread count for the navbar badge (refreshed on window focus)."""
    if not session.get('user_id'):
        return jsonify(ok=False, count=0), 401

    user_id = session['user_id']
    role = session.get('role') or ''

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            n = _inbox_unread_count(cur, user_id, role)
        conn.close()
        return jsonify(ok=True, count=n)
    except Exception:
        logging.exception('Could not fetch unread count')
        return jsonify(ok=False, count=0), 500


@main_bp.route('/inbox/mark-read', methods=['POST'])
def inbox_mark_read():
    """Mark notices as read.

    With an JSON/form `id` (+ optional `kind`), marks that single item:
      - kind 'message'  -> one direct mail (owner or main admin)
      - kind 'feedback'  -> one contact-form submission (main admin only)
    Without an id, marks everything visible to the signed-in user (bulk).
    """
    if not session.get('user_id'):
        return jsonify(ok=False), 401

    user_id = session['user_id']
    role = session.get('role') or ''

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        payload = request.get_json(silent=True) or request.form
        item_id = payload.get('id')
        if item_id is not None:
            try:
                item_id = int(item_id)
            except (TypeError, ValueError):
                return jsonify(ok=False), 400
            kind = payload.get('kind', 'message')
            if kind == 'feedback':
                if role != 'admin':
                    return jsonify(ok=False), 403
                cur.execute("UPDATE feedback SET is_read = TRUE WHERE f_id = %s", (item_id,))
            elif kind == 'message':
                cur.execute("SELECT recipient_u_id, target_role FROM messages WHERE msg_id = %s",
                            (item_id,))
                msg = cur.fetchone()
                target = (msg['target_role'] or '') if msg else ''
                if msg is None or target == 'account_report':
                    conn.rollback()
                    return jsonify(ok=False), 404
                if msg['recipient_u_id'] == user_id:
                    # direct mail: the flag on the row is this recipient's own
                    cur.execute("UPDATE messages SET is_read = TRUE WHERE msg_id = %s", (item_id,))
                elif msg['recipient_u_id'] is None and target in ('all', role):
                    # broadcast: shared row, so the read marker is per viewer
                    _mark_broadcast_read(cur, user_id, item_id)
                elif target in _REPORT_KINDS and role == 'admin':
                    # reports filed to the admins are shared among admins
                    cur.execute("UPDATE messages SET is_read = TRUE WHERE msg_id = %s", (item_id,))
                else:
                    conn.rollback()
                    return jsonify(ok=False), 404
            elif kind == 'booking':
                # the booking's customer, workshop owner or assigned mechanic (same scope as the list)
                scope = _BOOKING_SCOPE.get(role)
                cur.execute(f"SELECT 1 {scope} AND b.b_id = %s" if scope else "SELECT NULL WHERE FALSE",
                            (user_id, item_id) if scope else ())
                if cur.fetchone() is None:
                    conn.rollback()
                    return jsonify(ok=False), 404
                cur.execute("""
                    INSERT INTO inbox_read_state (u_id, item_type, item_id)
                    VALUES (%s, 'booking', %s)
                    ON CONFLICT (u_id, item_type, item_id) DO NOTHING
                """, (user_id, item_id))
            elif kind == 'join_request':
                # the mechanic who filed the request or the workshop's owner may
                # mark it read for themselves (same visibility as the card)
                cur.execute("""
                    SELECT 1 FROM join_request jr
                    LEFT JOIN mechanic m ON jr.m_id = m.m_id
                    LEFT JOIN workshop w ON jr.w_id = w.w_id
                    LEFT JOIN owner o ON w.o_id = o.o_id
                    WHERE jr.jr_id = %s
                      AND (m.u_id = %s OR o.u_id = %s)
                """, (item_id, user_id, user_id))
                if cur.fetchone() is None:
                    conn.rollback()
                    return jsonify(ok=False), 404
                cur.execute("""
                    INSERT INTO inbox_read_state (u_id, item_type, item_id)
                    VALUES (%s, 'join_request', %s)
                    ON CONFLICT (u_id, item_type, item_id) DO NOTHING
                """, (user_id, item_id))
            elif kind == 'leave_request':
                # only the workshop owner sees leave cards, so only they may mark
                cur.execute("""
                    SELECT 1 FROM mechanic m
                    JOIN workshop w ON m.w_id = w.w_id
                    JOIN owner o ON w.o_id = o.o_id
                    WHERE m.m_id = %s AND o.u_id = %s
                """, (item_id, user_id))
                if cur.fetchone() is None:
                    conn.rollback()
                    return jsonify(ok=False), 404
                cur.execute("""
                    INSERT INTO inbox_read_state (u_id, item_type, item_id)
                    VALUES (%s, 'leave_request', %s)
                    ON CONFLICT (u_id, item_type, item_id) DO NOTHING
                """, (user_id, item_id))
            else:
                return jsonify(ok=False), 400
            if kind in ('message', 'feedback') and cur.rowcount == 0:
                # join/leave kinds use INSERT ... ON CONFLICT DO NOTHING, whose
                # rowcount is 0 when the card was already marked read — that is
                # success, not a missing item.
                conn.rollback()
                return jsonify(ok=False), 404
            conn.commit()
            return jsonify(ok=True)

        section = payload.get('section')
        if section:
            # the bottom bar: only the section being viewed
            marked = _mark_section_read(cur, user_id, role, section)
            if marked is None:
                conn.rollback()
                return jsonify(ok=False), 400
            conn.commit()
            return jsonify(ok=True, marked=marked)

        # direct mail: the flag on the row is this recipient's own
        cur.execute("""
            UPDATE messages SET is_read = TRUE
            WHERE is_read = FALSE AND recipient_u_id = %s
              AND COALESCE(target_role, '') <> 'account_report'
        """, (user_id,))
        # broadcasts: shared rows, so mark them read for this viewer only
        cur.execute("""
            INSERT INTO inbox_message_state (u_id, msg_id, read_at)
            SELECT %s, m.msg_id, NOW() FROM messages m
            WHERE m.recipient_u_id IS NULL AND m.target_role IN ('all', %s)
            ON CONFLICT (u_id, msg_id)
            DO UPDATE SET read_at = COALESCE(inbox_message_state.read_at, NOW())
        """, (user_id, role))
        if role == 'admin':
            cur.execute("UPDATE feedback SET is_read = TRUE WHERE is_read = FALSE")
            cur.execute(
                "UPDATE messages SET is_read = TRUE WHERE is_read = FALSE AND target_role = ANY(%s)",
                (list(_REPORT_KINDS),),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception('Could not mark inbox messages read')
        return jsonify(ok=False), 500
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True)


@main_bp.route('/inbox/report', methods=['POST'])
def inbox_report():
    """File an account-attached report (stored in messages with target_role='report').

    Inboxes are read-only for everyone except the main admin, who is the only
    account allowed to put new content into the mailbox system.
    """
    if not session.get('user_id'):
        flash('Please log in to file a report.', 'error')
        return redirect(url_for('main.index'))

    if session.get('admin_type') != 'main':
        flash('Only the main admin can send in the inbox.', 'error')
        return redirect(url_for('main.inbox'))

    subject = request.form.get('subject', '').strip()[:150]
    body = request.form.get('body', '').strip()[:2000]

    if not subject or not body:
        flash('Please provide both a subject and a description.', 'error')
        return redirect(url_for('main.inbox'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO messages (sender_u_id, target_role, subject, body)
            VALUES (%s, 'report', %s, %s)
        """, (session['user_id'], subject, body))
        conn.commit()
        flash('Report filed — thanks for letting us know!', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not file report')
        flash('Failed to file the report.', 'error')
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('main.inbox'))


@main_bp.route('/report-account', methods=['POST'])
@limiter.limit("10 per hour", methods=["POST"])
def report_account():
    """Report another account to the admins.

    The report is stored as a message with target_role='account_report' where the
    sender is the reporter and the recipient is the reported user. Admins review
    these in the inbox and can suspend (ban) the reported account from there.

    This route is intentionally *not* main-admin-only like the rest of the inbox
    sending: reporting an account is the one action regular users are supposed to
    be able to do — it is the input side of the moderation flow.
    """
    if not session.get('user_id'):
        return jsonify(ok=False), 401

    try:
        reported_u_id = int(request.form.get('reported_u_id', ''))
    except (TypeError, ValueError):
        flash('That account could not be reported.', 'error')
        return _back_to_inbox()

    if reported_u_id == session['user_id']:
        flash('You cannot report your own account.', 'error')
        return _back_to_inbox()

    reasons = [r for r in request.form.getlist('reason') if r in REPORT_CATEGORIES]
    if not reasons:
        flash('Please choose at least one reason.', 'error')
        return _back_to_inbox()

    details = ' '.join(request.form.get('details', '').split())[:2000]
    if len(details) < 10:
        flash('Please describe the issue in a bit more detail.', 'error')
        return _back_to_inbox()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT u_id FROM users WHERE u_id = %s", (reported_u_id,))
        if not cur.fetchone():
            flash('That account does not exist.', 'error')
            return _back_to_inbox()

        # one OPEN report per reporter + account; once it is resolved they may report again
        cur.execute("""
            SELECT m.msg_id FROM messages m
            WHERE m.sender_u_id = %s AND m.recipient_u_id = %s AND m.target_role = 'account_report'
              AND NOT EXISTS (SELECT 1 FROM report_resolution rr WHERE rr.msg_id = m.msg_id)
            LIMIT 1
        """, (session['user_id'], reported_u_id))
        if cur.fetchone():
            flash("You've already reported this account — we're still reviewing it.", 'error')
            return _back_to_inbox()

        cur.execute("""
            INSERT INTO messages (sender_u_id, recipient_u_id, target_role, subject, body)
            VALUES (%s, %s, 'account_report', %s, %s) RETURNING msg_id
        """, (session['user_id'], reported_u_id, _report_subject(reasons, REPORT_CATEGORIES), details))
        report_id = cur.fetchone()['msg_id']
        cur.execute("SELECT name FROM users WHERE u_id = %s", (reported_u_id,))
        _notify(cur, session['user_id'], 'report_update', f'Report #{report_id} received',
                f"Thanks for letting us know. We received your report about {cur.fetchone()['name']} "
                "and our team will review it. We'll post the outcome here.")
        conn.commit()
        flash('Report sent — thanks for helping keep Getwheelz safe.', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not file account report')
        flash('Failed to send the report.', 'error')
    finally:
        cur.close()
        conn.close()
    return _back_to_inbox()


@main_bp.route('/report-workshop', methods=['POST'])
@limiter.limit("10 per hour", methods=["POST"])
def report_workshop():
    """Report a workshop listing to the admins.

    Stored as a message with target_role='workshop_report' where the sender is the
    reporter and there is no recipient (report target is the workshop, referenced
    by id in the JSON body). No recipient therefore also means the row can never
    leak into anyone's notices feed or be deleted by a regular user.

    The subject holds the comma-joined checked reason labels; the body is
    JSON: {"w_id": <id>, "details": "<description>"} (see _parse_workshop_report).
    """
    if not session.get('user_id'):
        return jsonify(ok=False), 401

    try:
        w_id = int(request.form.get('w_id', ''))
    except (TypeError, ValueError):
        flash('That workshop could not be reported.', 'error')
        return _back_to_inbox()

    reasons = [r for r in request.form.getlist('reason') if r in WORKSHOP_REPORT_CATEGORIES]
    if not reasons:
        flash('Please choose at least one reason.', 'error')
        return _back_to_inbox()

    details = ' '.join(request.form.get('details', '').split())[:2000]
    if len(details) < 10:
        flash('Please describe the issue in a bit more detail.', 'error')
        return _back_to_inbox()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM workshop WHERE w_id = %s", (w_id,))
        if not cur.fetchone():
            flash('That workshop does not exist.', 'error')
            return _back_to_inbox()

        # one open report per reporter + workshop (exact numeric match against the
        # JSON body; a LIKE prefix would false-positive on ids like 12 vs 123)
        # (once that report is resolved the reporter may file a new one)
        cur.execute("""
            SELECT m.msg_id FROM messages m
            WHERE m.sender_u_id = %s AND m.target_role = 'workshop_report'
              AND (m.body::jsonb ->> 'w_id')::bigint = %s
              AND NOT EXISTS (SELECT 1 FROM report_resolution rr WHERE rr.msg_id = m.msg_id)
            LIMIT 1
        """, (session['user_id'], w_id))
        if cur.fetchone():
            flash("You've already reported this workshop — we're still reviewing it.", 'error')
            return _back_to_inbox()

        cur.execute("""
            INSERT INTO messages (sender_u_id, recipient_u_id, target_role, subject, body)
            VALUES (%s, NULL, 'workshop_report', %s, %s) RETURNING msg_id
        """, (session['user_id'], _report_subject(reasons, WORKSHOP_REPORT_CATEGORIES),
              json.dumps({'w_id': w_id, 'details': details})))
        report_id = cur.fetchone()['msg_id']
        cur.execute("SELECT name FROM workshop WHERE w_id = %s", (w_id,))
        _notify(cur, session['user_id'], 'report_update', f'Report #{report_id} received',
                f"Thanks for letting us know. We received your report about {cur.fetchone()['name']} "
                "and our team will review it. We'll post the outcome here.")
        conn.commit()
        flash('Report sent — thanks for helping keep Getwheelz safe.', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not file workshop report')
        flash('Failed to send the report.', 'error')
    finally:
        cur.close()
        conn.close()
    return _back_to_inbox()


# ---------------------------------------------------------------------------
# Report verification (Phase 6, spec section 9). The rules live in app/report_rules.py:
#   open -> [ask the reported person to respond (72h) | skip, with a reason] -> verified
#        -> warn / suspend (locked until verified)  |  dismiss (always available)
# ---------------------------------------------------------------------------
def _report_target(cur, rep, manager_type):
    """Who a report is about and whether this admin may act on it.

    Returns ``(info, error)``; ``info`` has target_uid (who may respond / be sanctioned), target_name,
    target_role, subject_kind ('account' | 'workshop'), allowed (this admin's domain) and can_suspend.
    """
    if rep['target_role'] == 'account_report':
        cur.execute("SELECT u_id, name, role FROM users WHERE u_id = %s", (rep['recipient_u_id'],))
        target = cur.fetchone()
        if target is None:
            return None, 'The reported account no longer exists.'
        return {
            'target_uid': target['u_id'], 'target_name': target['name'], 'target_role': target['role'],
            'subject_kind': 'account',
            'allowed': manager_type == 'main' or ADMIN_DOMAIN_ROLE.get(manager_type) == target['role'],
            'can_suspend': target['role'] in ('customer', 'owner', 'mechanic'),
        }, None
    w_id, _details = _parse_workshop_report(rep['body'])
    cur.execute("""
        SELECT w.name, o.u_id AS owner_uid
        FROM workshop w JOIN owner o ON w.o_id = o.o_id
        WHERE w.w_id = %s
    """, (w_id,))
    ws = cur.fetchone()
    if ws is None:
        return None, 'The reported workshop no longer exists.'
    return {
        'target_uid': ws['owner_uid'], 'target_name': ws['name'], 'target_role': 'owner',
        'subject_kind': 'workshop',
        'allowed': manager_type in ('main', 'owner_workshop_manager'),
        'can_suspend': False,  # a workshop report warns the owner; accounts are suspended from their own report
    }, None


def _review_view(row, now):
    """What the admin popup (and the reported person's form) needs to know about a report's review
    stage. ``row`` is a report_review row or None."""
    row = dict(row) if row else {}
    state = report_rules.response_state(
        row.get('response_mode'), row.get('response_requested_at'), row.get('responded_at'), now
    )
    requested_at = row.get('response_requested_at')
    return {
        'mode': row.get('response_mode'),
        'state': state,
        'state_label': report_rules.STATE_LABELS[state],
        'requested_at': requested_at,
        'deadline': report_rules.deadline(requested_at) if requested_at else None,
        'hours_left': report_rules.hours_left(requested_at, now) if requested_at and state == report_rules.WAITING else None,
        'response_text': row.get('response_text'),
        'responded_at': row.get('responded_at'),
        'skip_reason': row.get('skip_reason'),
        'verified': row.get('verified_at') is not None,
        'verified_at': row.get('verified_at'),
        'can_verify': report_rules.can_verify(state) and row.get('verified_at') is None,
        'can_respond': report_rules.can_respond(state),
    }


def _load_reviews(cur, ids):
    if not ids:
        return {}
    cur.execute("SELECT * FROM report_review WHERE msg_id = ANY(%s)", (list(ids),))
    return {r['msg_id']: dict(r) for r in cur.fetchall()}


def _evidence(cur, report_id, reporter_uid, reported_uid):
    """The admin's evidence panel: bookings between the two people, and earlier reports / warnings on the
    reported account. Only called for admins (the queries read other people's rows)."""
    ev = {'bookings': [], 'past_reports': [], 'warnings': 0}
    if reporter_uid and reported_uid:
        cur.execute("""
            SELECT b.b_id, b.requested_time, b.status, w.name AS workshop, sc.s_name
            FROM booking b
            JOIN customer c ON c.c_id = b.c_id
            JOIN workshop w ON w.w_id = b.w_id
            JOIN owner o ON o.o_id = w.o_id
            LEFT JOIN mechanic m ON m.m_id = b.assigned_m_id
            JOIN service s ON s.s_id = b.s_id
            JOIN service_catalog sc ON sc.sc_id = s.sc_id
            WHERE (c.u_id = %s AND (o.u_id = %s OR m.u_id = %s))
               OR (c.u_id = %s AND (o.u_id = %s OR m.u_id = %s))
            ORDER BY b.requested_time DESC LIMIT 10
        """, (reporter_uid, reported_uid, reported_uid, reported_uid, reporter_uid, reporter_uid))
        ev['bookings'] = [dict(r) for r in cur.fetchall()]
    if reported_uid:
        cur.execute("""
            SELECT m.msg_id AS id, m.subject, m.sent_at AS time, m.target_role AS kind, m.body,
                   rr.status, rr.outcome
            FROM messages m LEFT JOIN report_resolution rr ON rr.msg_id = m.msg_id
            WHERE m.msg_id <> %s AND m.target_role IN ('account_report', 'workshop_report')
              AND (m.recipient_u_id = %s OR m.target_role = 'workshop_report')
            ORDER BY m.sent_at DESC LIMIT 200
        """, (report_id, reported_uid))
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("""
            SELECT w.w_id FROM workshop w JOIN owner o ON o.o_id = w.o_id WHERE o.u_id = %s
        """, (reported_uid,))
        own_workshops = {r['w_id'] for r in cur.fetchall()}
        past = []
        for r in rows:
            if r['kind'] == 'workshop_report':
                w_id, _ = _parse_workshop_report(r['body'])
                if w_id not in own_workshops:
                    continue
            r.pop('body', None)
            past.append(r)
        ev['past_reports'] = past[:10]
        ev['warnings'] = sum(1 for r in past if r.get('outcome') == 'warn')
    return ev


def _admin_target(msg_id):
    """Shared start of the admin report routes: the report, who it is about, and this admin's rights.
    Returns ``(conn, cur, rep, info, error_flash)``; the caller closes the connection."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT msg_id, sender_u_id, recipient_u_id, target_role, subject, body
        FROM messages WHERE msg_id = %s AND target_role IN ('account_report', 'workshop_report')
    """, (msg_id,))
    rep = cur.fetchone()
    if rep is None:
        return conn, cur, None, None, 'That report no longer exists.'
    cur.execute("SELECT 1 FROM report_resolution WHERE msg_id = %s", (msg_id,))
    if cur.fetchone():
        return conn, cur, rep, None, 'That report has already been resolved.'
    info, error = _report_target(cur, rep, session.get('admin_type'))
    if error:
        return conn, cur, rep, None, error
    if not info['allowed']:
        return conn, cur, rep, None, "You can't act on reports in this area."
    return conn, cur, rep, info, None


@main_bp.route('/inbox/report/<sealed(message):msg_id>/response', methods=['POST'])
@admin_access_required()
def inbox_report_response(msg_id):
    """Decide, once per report, whether to ask the reported person to respond (72 hours) or to skip
    that step (urgent safety cases; a reason is required and recorded on the report)."""
    mode = request.form.get('mode', '')
    if mode not in ('request', 'skip'):
        flash('Please choose whether to ask for a response.', 'error')
        return _back_to_inbox()
    reason = None
    if mode == 'skip':
        reason, error = report_rules.clean_skip_reason(request.form.get('reason'))
        if error:
            flash(error, 'error')
            return _back_to_inbox()

    conn, cur, rep, info, error = _admin_target(msg_id)
    try:
        if error:
            flash(error, 'error')
            return _back_to_inbox()
        now = rules.now()
        cur.execute("""
            INSERT INTO report_review (msg_id, reported_u_id) VALUES (%s, %s)
            ON CONFLICT (msg_id) DO NOTHING
        """, (msg_id, info['target_uid']))
        if mode == 'request':
            cur.execute("""
                UPDATE report_review
                SET response_mode = 'requested', response_requested_at = %s, response_decided_by = %s
                WHERE msg_id = %s AND response_mode IS NULL
            """, (now, session['user_id'], msg_id))
        else:
            cur.execute("""
                UPDATE report_review
                SET response_mode = 'skipped', skip_reason = %s, response_decided_by = %s
                WHERE msg_id = %s AND response_mode IS NULL
            """, (reason, session['user_id'], msg_id))
        if cur.rowcount == 0:
            conn.rollback()
            flash('You already decided about a response for this report.', 'error')
            return _back_to_inbox()
        if mode == 'request':
            # the reported person is told a report exists, never who filed it
            what = f"your workshop {info['target_name']}" if info['subject_kind'] == 'workshop' else 'your account'
            _notify(cur, info['target_uid'], 'report_notice', 'A report was filed about your account',
                    f"A report about {what} was filed and is being reviewed.\n\nReason given: {rep['subject']}\n\n"
                    f"You have {int(report_rules.RESPONSE_WINDOW.total_seconds() // 3600)} hours, until "
                    f"{report_rules.deadline(now).strftime('%d %b %Y, %I:%M %p')}, to give your side. "
                    "Open this message and use the response form. You will not be told who filed the report. "
                    "If you do not respond, the review team will decide without your response.",
                    ref=('report_response', msg_id))
        conn.commit()
        flash('The reported person was asked to respond within 72 hours.' if mode == 'request'
              else 'Response request skipped. The reason is recorded on the report.', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not record the response decision for report %s', msg_id)
        flash('Could not save that. Please try again.', 'error')
    finally:
        cur.close()
        conn.close()
    return _back_to_inbox()


@main_bp.route('/inbox/report/<sealed(message):msg_id>/respond', methods=['POST'])
def inbox_report_respond(msg_id):
    """The reported person's one response, from their Reports section, inside the 72-hour window."""
    if not session.get('user_id'):
        return jsonify(ok=False), 401
    text, error = report_rules.clean_response(request.form.get('response'))
    if error:
        flash(error, 'error')
        return _back_to_inbox()
    now = rules.now()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # only the person the report is about, only while asked, only once, only inside the window
        cur.execute("""
            UPDATE report_review
            SET response_text = %s, responded_at = %s
            WHERE msg_id = %s AND reported_u_id = %s AND response_mode = 'requested'
              AND responded_at IS NULL AND response_requested_at + %s > %s
            RETURNING response_decided_by
        """, (text, now, msg_id, session['user_id'], report_rules.RESPONSE_WINDOW, now))
        done = cur.fetchone()
        if done and done['response_decided_by']:
            _notify(cur, done['response_decided_by'], 'report_update', f'Response received on report #{msg_id}',
                    'The reported person responded. Open the report in your Reports section to read it.')
        conn.commit()
        if done:
            flash('Your response was sent to the review team.', 'success')
        else:
            flash('That response can no longer be sent: the window has closed, or you already responded.', 'error')
    except Exception:
        conn.rollback()
        logging.exception('Could not save the response to report %s', msg_id)
        flash('Could not send your response. Please try again.', 'error')
    finally:
        cur.close()
        conn.close()
    return _back_to_inbox()


@main_bp.route('/inbox/report/<sealed(message):msg_id>/verify', methods=['POST'])
@admin_access_required()
def inbox_report_verify(msg_id):
    """Mark a report Verified, which unlocks Warn and Suspend. Needs the response step settled."""
    conn, cur, rep, info, error = _admin_target(msg_id)
    try:
        if error:
            flash(error, 'error')
            return _back_to_inbox()
        now = rules.now()
        cur.execute("SELECT * FROM report_review WHERE msg_id = %s", (msg_id,))
        view = _review_view(cur.fetchone(), now)
        if view['verified']:
            flash('That report is already verified.', 'error')
        elif not view['can_verify']:
            flash('Decide about a response first, then wait for it or for the 72 hours to pass '
                  '(or skip the request with a reason). Dismiss is always available.', 'error')
        else:
            cur.execute("""
                UPDATE report_review SET verified_at = %s, verified_by = %s
                WHERE msg_id = %s AND verified_at IS NULL
            """, (now, session['user_id'], msg_id))
            conn.commit()
            flash('Report verified. Warn and Suspend are now unlocked.', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not verify report %s', msg_id)
        flash('Could not verify the report. Please try again.', 'error')
    finally:
        cur.close()
        conn.close()
    return _back_to_inbox()


@main_bp.route('/inbox/report/<sealed(message):msg_id>/resolve', methods=['POST'])
@admin_access_required()
def inbox_report_resolve(msg_id):
    """Close an account / workshop report with a decision (spec section 9).

    outcome=dismiss  -> no violation found; ALWAYS available; only the reporter is told
    outcome=warn     -> needs the report VERIFIED first; the reported person gets a warning notice
    outcome=suspend  -> needs the report VERIFIED first; the account is suspended (accounts only) and
                        the person is notified, with a pointer to the appeal button

    The reporter always gets an outcome update (without any sanction details). Each report can be
    resolved once. The same domain rule as banning applies: the main admin may resolve anything, a
    manager only reports about their own role.
    """
    outcome = request.form.get('outcome', '')
    note = ' '.join(request.form.get('note', '').split())[:500]
    if outcome not in REPORT_OUTCOMES:
        flash('Please choose how to resolve this report.', 'error')
        return _back_to_inbox()

    admin_uid = session['user_id']
    conn, cur, rep, info, error = _admin_target(msg_id)
    try:
        if error:
            flash(error.replace("act on", "resolve"), 'error')
            return _back_to_inbox()

        cur.execute("SELECT * FROM report_review WHERE msg_id = %s", (msg_id,))
        review = _review_view(cur.fetchone(), rules.now())
        allowed, why = report_rules.outcome_allowed(outcome, review['verified'], info['can_suspend'])
        if not allowed:
            flash(why, 'error')
            return _back_to_inbox()

        target_uid, target_name = info['target_uid'], info['target_name']
        subject_kind = info['subject_kind']

        if outcome == 'suspend':
            # who suspended and when is kept: an appeal goes to another admin if the main admin did it
            cur.execute(
                "UPDATE users SET is_suspended = TRUE, suspended_by = %s, suspended_at = %s WHERE u_id = %s",
                (admin_uid, rules.now(), target_uid),
            )

        status = 'dismissed' if outcome == 'dismiss' else 'verified'
        cur.execute("""
            INSERT INTO report_resolution (msg_id, status, outcome, note, handled_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (msg_id, status, outcome, note or None, admin_uid))

        what = f"the workshop {target_name}" if subject_kind == 'workshop' else target_name
        note_line = f"\n\nNote from the review team: {note}" if note else ''

        # 1) the reporter always hears the outcome (no sanction details)
        if rep['sender_u_id']:
            if status == 'verified':
                body = (f"We reviewed your report about {what} and confirmed a violation of our rules. "
                        f"We've taken action. Thank you for helping keep Getwheelz safe.{note_line}")
            else:
                body = (f"We reviewed your report about {what} and did not find a violation of our rules, "
                        f"so no action was taken. If you have new information you can file another report."
                        f"{note_line}")
            _notify(cur, rep['sender_u_id'], 'report_update',
                    f"Report #{msg_id}: {'action taken' if status == 'verified' else 'no violation found'}",
                    body)

        # 2) the reported person is told only when the report was verified, with the reason and action
        if status == 'verified' and target_uid:
            subject_of = f"your workshop {target_name}" if subject_kind == 'workshop' else 'your account'
            if outcome == 'suspend':
                action = ("Your account has been suspended. If you believe this is a mistake, use the "
                          "Appeal button on the suspension screen when you try to log in.")
            else:
                action = ("This is a warning. Further violations may lead to your "
                          "account being suspended.")
            _notify(cur, target_uid, 'report_notice', 'Notice about a report on your account',
                    f"A report about {subject_of} was reviewed and verified.\n\n"
                    f"Reason: {rep['subject']}\n{action}{note_line}")

        conn.commit()
        flash({'warn': 'Report verified — a warning was sent to the user.',
               'suspend': 'Report verified — the account was suspended and the user notified.',
               'dismiss': 'Report dismissed — the reporter was notified.'}[outcome], 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not resolve report %s', msg_id)
        flash('Could not resolve the report. Please try again.', 'error')
    finally:
        cur.close()
        conn.close()
    return _back_to_inbox()


@main_bp.route('/inbox/delete', methods=['POST'])
def inbox_delete():
    """Delete a notice or a report mail.

    Direct mail is removed for good. A broadcast is one shared row, so deleting
    it only hides it for the viewer who deleted it -- nobody else loses it. The
    main admin may additionally delete any other message and any feedback report.
    """
    if not session.get('user_id'):
        return jsonify(ok=False), 401

    payload = request.get_json(silent=True) or request.form
    kind = payload.get('kind', 'message')
    try:
        item_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return jsonify(ok=False), 400

    # Deleting anything is an admin-moderation action: only the main admin may
    # remove rows other users' can touch. Everyone else may only delete their own
    # direct mail and the reports they themselves filed.
    is_admin = session.get('admin_type') == 'main'

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if kind == 'feedback':
            if not is_admin:
                return jsonify(ok=False), 403
            cur.execute("DELETE FROM feedback WHERE f_id = %s", (item_id,))
        elif kind == 'message':
            user_id = session['user_id']
            role = session.get('role') or ''
            cur.execute("SELECT recipient_u_id, target_role FROM messages WHERE msg_id = %s",
                        (item_id,))
            msg = cur.fetchone()
            target = (msg['target_role'] or '') if msg else ''
            if msg is None:
                conn.rollback()
                return jsonify(ok=False), 404
            if not is_admin and target == 'account_report':
                # never deletable by a regular user: the report is the admin's evidence
                conn.rollback()
                return jsonify(ok=False), 404
            if msg['recipient_u_id'] == user_id:
                cur.execute("DELETE FROM messages WHERE msg_id = %s", (item_id,))
            elif msg['recipient_u_id'] is None and target in ('all', role):
                _hide_broadcast(cur, user_id, item_id)
            elif is_admin:
                # moderation: the main admin may remove any other message
                cur.execute("DELETE FROM messages WHERE msg_id = %s", (item_id,))
            else:
                conn.rollback()
                return jsonify(ok=False), 404
        elif kind == 'report':
            if is_admin:
                cur.execute("""
                    DELETE FROM messages
                    WHERE msg_id = %s AND target_role IN ('report', 'account_report', 'workshop_report')
                """, (item_id,))
            else:
                # a report under review is evidence: the reporter can only clear it
                # once it has been resolved (plain 'report' mail has no review step)
                cur.execute("""
                    DELETE FROM messages m
                    WHERE m.msg_id = %s AND m.sender_u_id = %s
                      AND (m.target_role = 'report'
                           OR (m.target_role IN ('account_report', 'workshop_report')
                               AND EXISTS (SELECT 1 FROM report_resolution rr WHERE rr.msg_id = m.msg_id)))
                """, (item_id, session['user_id']))
        else:
            return jsonify(ok=False), 400

        if cur.rowcount == 0:
            conn.rollback()
            return jsonify(ok=False), 404

        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception('Could not delete inbox mail')
        return jsonify(ok=False), 500
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True)


@main_bp.route('/inbox/delete-all', methods=['POST'])
def inbox_delete_all():
    """Delete everything deletable in ONE inbox section (``section`` = notices, updates, joins,
    leaves or reports; no section means notices, as before).

    Direct mail is removed for good; broadcasts are shared rows, so they are only hidden for this
    viewer; booking and request cards are hidden for this viewer only and never touch the booking or
    request; anything still waiting on the viewer, and the reports admins need as evidence, stay.
    """
    if not session.get('user_id'):
        return jsonify(ok=False), 401

    payload = request.get_json(silent=True) or request.form
    section = payload.get('section') or 'notices'
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        deleted = _delete_section(cur, session['user_id'], session.get('role') or '', section)
        if deleted is None:
            conn.rollback()
            return jsonify(ok=False), 400
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception('Could not delete all inbox mail')
        return jsonify(ok=False), 500
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True, deleted=deleted)


@main_bp.route('/inbox/dismiss', methods=['POST'])
def inbox_dismiss():
    """Hide a resolved join/leave request card from THIS viewer's inbox.

    Dismissal is a soft hide: it writes a row to inbox_dismissal and never
    touches the underlying booking/request record. Only the workshop owner (for
    join and leave requests) or the mechanic themselves (for join requests) may
    dismiss a card.
    """
    if not session.get('user_id'):
        return jsonify(ok=False), 401

    payload = request.get_json(silent=True) or request.form
    kind = payload.get('kind')
    if kind not in ('join_request', 'leave_request', 'booking'):
        return jsonify(ok=False), 400
    try:
        item_id = int(payload.get('id'))
    except (TypeError, ValueError):
        return jsonify(ok=False), 400

    user_id = session['user_id']

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if kind == 'booking':
            # a RESOLVED booking/job (completed or cancelled) of this viewer; ones still waiting on
            # somebody stay in the inbox
            scope = _BOOKING_SCOPE.get(session.get('role') or '')
            if not scope:
                return jsonify(ok=False), 404
            cur.execute(f"SELECT 1 {scope} AND b.b_id = %s {_BOOKING_RESOLVED} LIMIT 1",
                        (user_id, item_id))
        elif kind == 'join_request':
            # the workshop's owner or the requesting mechanic may dismiss a
            # RESOLVED request; pending ones stay actionable in the inbox
            cur.execute("""
                SELECT 1 FROM join_request jr
                LEFT JOIN mechanic m ON jr.m_id = m.m_id
                LEFT JOIN workshop w ON jr.w_id = w.w_id
                LEFT JOIN owner o ON w.o_id = o.o_id
                WHERE jr.jr_id = %s AND jr.status <> 'pending'
                  AND (o.u_id = %s OR m.u_id = %s)
                LIMIT 1
            """, (item_id, user_id, user_id))
        else:  # leave_request
            # only the owner of the mechanic's workshop may dismiss a leave card,
            # and only a declined one (approved leaves clear out on their own)
            cur.execute("""
                SELECT 1 FROM mechanic m
                JOIN workshop w ON m.w_id = w.w_id
                JOIN owner o ON w.o_id = o.o_id
                WHERE m.m_id = %s AND m.leave_rejected_at IS NOT NULL
                  AND o.u_id = %s
                LIMIT 1
            """, (item_id, user_id))
        if not cur.fetchone():
            return jsonify(ok=False), 404

        cur.execute("""
            INSERT INTO inbox_dismissal (u_id, item_type, item_id)
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (user_id, kind, item_id))
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception('Could not dismiss inbox card')
        return jsonify(ok=False), 500
    finally:
        cur.close()
        conn.close()
    return jsonify(ok=True)
