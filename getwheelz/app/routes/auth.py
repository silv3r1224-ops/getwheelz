from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db_connection
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from app import limiter
from app.utils import make_reset_token, read_reset_token, reset_fingerprint_matches

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
SIGNUP_ROLES = ('customer', 'owner', 'mechanic')

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

def _begin_session(cur, user):
    """Log `user` in (admin accounts must be active). Returns (landing_url, error_message)."""
    admin_row = None
    if user['role'] == 'admin':
        cur.execute(
            "SELECT admin_type, is_active FROM admin WHERE u_id = %s",
            (user['u_id'],)
        )
        admin_row = cur.fetchone()
        if not admin_row or not admin_row['is_active']:
            return None, 'This admin account is inactive or not configured.'

    session.clear()
    session.permanent = True  # keep the login across browser restarts (see PERMANENT_SESSION_LIFETIME)
    session['user_id'] = user['u_id']
    session['user_name'] = user['name']
    session['role'] = user['role']
    if admin_row:
        session['admin_type'] = admin_row['admin_type']
        session['is_main_admin'] = admin_row['admin_type'] == 'main'

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
    return target, None


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

                target, error = _begin_session(cur, user)
                if error:
                    return _fail(error, 403)

                flash(f"Welcome back, {user['name']}!", 'success')

                if _wants_json():
                    return jsonify(ok=True, redirect=target)
                return redirect(target)
        finally:
            conn.close()
    return redirect(url_for('main.index'))
    

# ------------------------------------------------------------------------------------------
# Continue with Google (OAuth 2.0 authorization-code flow)
#   /auth/google?mode=login|signup&role=customer|owner|mechanic  -> sends the person to Google
#   /auth/google/callback                                       -> Google sends them back here
# ------------------------------------------------------------------------------------------
def _google_redirect_uri():
    return current_app.config.get('GOOGLE_REDIRECT_URI') or url_for('auth.google_callback', _external=True)


def _google_post(url, data):
    """POST form data to Google and return the decoded JSON (raises on network / HTTP errors)."""
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method='POST')
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _google_get(url, access_token):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access_token}'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


@auth_bp.route('/google')
@limiter.limit("20 per minute")
def google_login():
    if not (current_app.config.get('GOOGLE_CLIENT_ID') and current_app.config.get('GOOGLE_CLIENT_SECRET')):
        flash('Google sign-in is not set up yet. Please use your email and password.', 'error')
        return redirect(url_for('main.index'))

    mode = 'signup' if request.args.get('mode') == 'signup' else 'login'
    role = request.args.get('role', 'customer')
    if role not in SIGNUP_ROLES:
        role = 'customer'

    state = secrets.token_urlsafe(32)
    session['google_oauth'] = {'state': state, 'mode': mode, 'role': role}

    params = {
        'client_id': current_app.config['GOOGLE_CLIENT_ID'],
        'redirect_uri': _google_redirect_uri(),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}")


@auth_bp.route('/google/callback')
@limiter.limit("20 per minute")
def google_callback():
    saved = session.pop('google_oauth', None)

    if request.args.get('error'):
        flash('Google sign-in was cancelled.', 'error')
        return redirect(url_for('main.index'))

    # the "state" we sent must come back unchanged, otherwise this request did not start here
    given_state = request.args.get('state', '')
    if not saved or not hmac.compare_digest(saved['state'], given_state) or not request.args.get('code'):
        flash('Google sign-in could not be verified. Please try again.', 'error')
        return redirect(url_for('main.index'))

    try:
        token = _google_post(GOOGLE_TOKEN_URL, {
            'code': request.args['code'],
            'client_id': current_app.config['GOOGLE_CLIENT_ID'],
            'client_secret': current_app.config['GOOGLE_CLIENT_SECRET'],
            'redirect_uri': _google_redirect_uri(),
            'grant_type': 'authorization_code',
        })
        profile = _google_get(GOOGLE_USERINFO_URL, token['access_token'])
    except (urllib.error.URLError, KeyError, ValueError):
        logging.exception('Google sign-in failed while talking to Google')
        flash('Could not reach Google. Please try again.', 'error')
        return redirect(url_for('main.index'))

    google_id = str(profile.get('sub') or '')
    email = (profile.get('email') or '').strip().lower()
    if not google_id or not email or not profile.get('email_verified'):
        flash('Your Google account needs a verified email address.', 'error')
        return redirect(url_for('main.index'))

    name = (profile.get('name') or email.split('@')[0]).strip()[:100]

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT u_id, name, role, google_id FROM users WHERE google_id = %s", (google_id,))
            user = cur.fetchone()

            if user is None:
                cur.execute("SELECT u_id, name, role, google_id FROM users WHERE email = %s", (email,))
                user = cur.fetchone()
                if user is not None:
                    if user['google_id'] and user['google_id'] != google_id:
                        flash('That email is already linked to a different Google account.', 'error')
                        return redirect(url_for('main.index'))
                    # first Google sign-in for an existing account: link it
                    cur.execute("UPDATE users SET google_id = %s WHERE u_id = %s", (google_id, user['u_id']))

            created = False
            if user is None:
                if saved['mode'] != 'signup':
                    flash('No account found for that Google email. Please sign up first.', 'error')
                    return redirect(url_for('main.index'))

                role = saved['role']
                # Google users have no password: store a random one nobody knows
                cur.execute(
                    "INSERT INTO users (name, email, password, role, google_id, password_set, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, FALSE, NOW()) RETURNING u_id",
                    (name, email, generate_password_hash(secrets.token_urlsafe(32)), role, google_id)
                )
                user = {'u_id': cur.fetchone()['u_id'], 'name': name, 'role': role}
                cur.execute(f"INSERT INTO {role} (u_id) VALUES (%s)", (user['u_id'],))
                created = True

            target, error = _begin_session(cur, user)
            if error:
                conn.rollback()
                flash(error, 'error')
                return redirect(url_for('main.index'))
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception('Google sign-in failed')
        flash('Something went wrong with Google sign-in. Please try again.', 'error')
        return redirect(url_for('main.index'))
    finally:
        conn.close()

    flash(f"Welcome, {user['name']}!" if created else f"Welcome back, {user['name']}!", 'success')
    return redirect(target)


# ------------------------------------------------------------------------------------------
# Forgot password: email a time-limited link, then let the person choose a new password
# ------------------------------------------------------------------------------------------
def _reset_minutes():
    return current_app.config.get('PASSWORD_RESET_MINUTES', 60)


def _send_reset_email(name, email, link):
    # Email sending is not set up. The reset link is printed in the Flask console (terminal) instead.
    # To send real emails later, replace this body with your email-sending code.
    logging.warning('Password reset link for %s: %s', email, link)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        if email:
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT u_id, name, password FROM users WHERE email = %s", (email,))
                    user = cur.fetchone()
            finally:
                conn.close()

            if user:
                token = make_reset_token(user['u_id'], user['password'])
                base = (current_app.config.get('APP_BASE_URL') or request.host_url).rstrip('/')
                link = base + url_for('auth.reset_password', token=token)
                _send_reset_email(user['name'], email, link)

        # same answer whether or not the email has an account
        flash('If an account exists for that email, a password reset link is on its way. '
              f'It expires in {_reset_minutes()} minutes.', 'success')
        return redirect(url_for('auth.forgot_password'))

    return render_template('auth/forgot_password.html')


def _user_for_reset_token(cur, token):
    """The user a reset link belongs to, or None if the link is invalid, expired or already used."""
    data = read_reset_token(token, _reset_minutes() * 60)
    if not data:
        return None
    user_id, fingerprint = data
    cur.execute("SELECT u_id, name, email, password FROM users WHERE u_id = %s", (user_id,))
    user = cur.fetchone()
    if not user or not reset_fingerprint_matches(user['password'], fingerprint):
        return None
    return user


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def reset_password(token):
    invalid = 'That reset link is invalid or has expired. Please request a new one.'
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            user = _user_for_reset_token(cur, token)
            if user is None:
                flash(invalid, 'error')
                return redirect(url_for('auth.forgot_password'))

            if request.method == 'POST':
                new_password = request.form.get('new_pass', '')
                confirm_password = request.form.get('confirm_pass', '')

                if len(new_password) < 8:
                    flash('Password must be at least 8 characters.', 'error')
                    return redirect(url_for('auth.reset_password', token=token))
                if new_password != confirm_password:
                    flash('Passwords do not match.', 'error')
                    return redirect(url_for('auth.reset_password', token=token))

                # password_set = TRUE also covers accounts that signed up with Google and never had one
                cur.execute(
                    "UPDATE users SET password = %s, password_set = TRUE WHERE u_id = %s",
                    (generate_password_hash(new_password), user['u_id'])
                )
                conn.commit()
                flash('Your password has been reset. Please log in with your new password.', 'success')
                return redirect(url_for('main.index'))
    except Exception:
        conn.rollback()
        logging.exception('Password reset failed')
        flash('Something went wrong. Please try again.', 'error')
        return redirect(url_for('auth.forgot_password'))
    finally:
        conn.close()

    return render_template('auth/reset_password.html', token=token, minutes=_reset_minutes())


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.index'))