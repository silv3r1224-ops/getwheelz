from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app, jsonify
import logging
from app import limiter
from app.db import get_db_connection

main_bp = Blueprint('main', __name__)

# where each kind of account lands after login (same targets as the login route)
ROLE_HOME = {
    'admin': 'dashboard.admin',
    'customer': 'customer.home',
    'owner': 'dashboard.owner',
    'mechanic': 'mechanics.home',
}


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


    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT w_id, name, address, latitude, longitude
        FROM workshop
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY w_id DESC
        LIMIT 50
    """)
    workshops = cur.fetchall()

    cur.execute("""
        SELECT (SELECT COUNT(*) FROM workshop) AS workshops,
            (SELECT COUNT(*) FROM mechanic WHERE w_id IS NOT NULL) AS mechanics,
            (SELECT COUNT(*) FROM service) AS services,
            (SELECT COUNT(*) FROM booking WHERE status = 'completed') AS jobs
    """)
    stats = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('index.html', workshops=workshops, stats=stats)

@main_bp.route('/about')
def about():
    return render_template('about.html')

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
    return render_template(
        'contact.html',
        prefill=prefill,
        contact_email=cfg.get('CONTACT_EMAIL'),
        contact_phone=cfg.get('CONTACT_PHONE'),
        contact_location=cfg.get('CONTACT_LOCATION'),
    )


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