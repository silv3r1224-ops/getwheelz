from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db_connection
import logging
from app import limiter

auth_bp = Blueprint('auth', __name__)


def _wants_json():
    """The pop-up forms submit in the background (header.js) and ask for JSON, so the pop-up can stay open."""
    return request.headers.get('X-Requested-With') == 'fetch'


def _fail(message, status, fallback_endpoint='main.index'):
    """Report a problem: as JSON for the pop-ups, as a flash + redirect for a plain form post."""
    if _wants_json():
        return jsonify(ok=False, error=message), status
    flash(message, 'error')
    return redirect(url_for(fallback_endpoint))

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        role = request.form.get('role', 'customer')

        allowed_roles = ('customer', 'owner', 'mechanic')
        if role not in allowed_roles:
            return _fail('Invalid role selected', 400)

        if password != confirm_password:
            return _fail('Passwords do not match', 400)

        if len(password) < 8:
            return _fail('Password must be at least 8 characters.', 400)

        password_hash = generate_password_hash(password)

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:
                cur.execute(
                        "INSERT INTO users (name, email, password, role,created_at) VALUES (%s, %s, %s, %s, NOW()) RETURNING u_id",
                        (name, email, password_hash, role)
                )
                user_id = cur.fetchone()['u_id']

                role_table = {
                    'customer': 'customer',
                    'owner': 'owner',
                    'mechanic': 'mechanic',
                    'admin': 'admin'
                }

                cur.execute(
                    f"INSERT INTO {role_table[role]} (u_id) VALUES (%s)",
                    (user_id,)
                )
            conn.commit()
            if _wants_json():
                # the pop-up switches to the login form itself, so no flash message is queued
                return jsonify(ok=True, message='Account created successfully. Please log in.')
            flash('Account created successfully. Please log in.', 'success')
            return redirect(url_for('main.index'))

        except Exception:
            conn.rollback()
            logging.exception("Error creating user account")
            return _fail('Something went wrong - that email may already be registered.', 400)
        finally:
            conn.close()

    return redirect(url_for('main.index'))


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT u_id, name, password, role FROM users WHERE email = %s", (email,))
                user = cur.fetchone()

                if user is None or not check_password_hash(user['password'], password):
                    return _fail('Invalid email or password', 401)

                admin_row = None
                if user['role'] == 'admin':
                    cur.execute(
                        "SELECT admin_type, is_active FROM admin WHERE u_id = %s",
                        (user['u_id'],)
                    )
                    admin_row = cur.fetchone()
                    if not admin_row or not admin_row['is_active']:
                        return _fail('This admin account is inactive or not configured.', 403)

                session.clear()
                session.permanent = True  # keep the login across browser restarts (see PERMANENT_SESSION_LIFETIME)
                session['user_id'] = user['u_id']
                session['user_name'] = user['name']
                session['role'] = user['role']
                if admin_row:
                    session['admin_type'] = admin_row['admin_type']
                    session['is_main_admin'] = admin_row['admin_type'] == 'main'

                flash(f"Welcome back, {user['name']}!", 'success') 

                if user['role'] == 'admin':
                    target = url_for('dashboard.admin')
                elif user['role'] == 'customer':
                    target = url_for('customer.home')
                elif user['role'] == 'owner':
                    target = url_for('dashboard.owner')
                elif user['role'] == 'mechanic':
                    target = url_for('mechanics.home')
                else:
                    target = url_for('main.index')

                if _wants_json():
                    return jsonify(ok=True, redirect=target)
                return redirect(target)
        finally:
            conn.close()
    return redirect(url_for('main.index'))
    

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.index'))