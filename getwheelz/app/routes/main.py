from flask import Blueprint, render_template, redirect, url_for, request, flash, session
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
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        subject = request.form.get('subject')
        message = request.form['message']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO feedback (name, email, subject, message) VALUES (%s, %s, %s, %s)",
            (name, email, subject, message)
        )
        conn.commit()
        cur.close()
        conn.close()

        flash('Message sent — thank you for reaching out!', 'success')
        return redirect(url_for('main.contact'))

    return render_template('contact.html')