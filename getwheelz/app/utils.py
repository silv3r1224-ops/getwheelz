from functools import wraps
from flask import session, redirect, url_for, abort, current_app, flash
import hashlib
from itsdangerous import URLSafeSerializer, URLSafeTimedSerializer, BadSignature, SignatureExpired

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to continue.', 'error')
                return redirect(url_for('main.index'))
            if session.get('role') not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def _wid_serializer():
    return URLSafeSerializer(current_app.secret_key, salt='workshop-preview')


def encode_wid(w_id):
    """workshop id -> signed token for use in URLs"""
    return _wid_serializer().dumps(int(w_id))


def decode_wid(token):
    """signed token -> workshop id, or None if the token was edited or is invalid"""
    try:
        return int(_wid_serializer().loads(token))
    except (BadSignature, ValueError, TypeError):
        return None



def encode_uid(u_id):
    """user id -> signed token for profile URLs"""
    return URLSafeSerializer(current_app.secret_key, salt='user-profile').dumps(int(u_id))


def decode_uid(token):
    try:
        return int(URLSafeSerializer(current_app.secret_key, salt='user-profile').loads(token))
    except (BadSignature, ValueError, TypeError):
        return None

def admin_access_required(*allowed_types, main_only=False):
    """Authorize an admin using the database record, not only client session data."""
    from app.db import get_db_connection

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('main.index'))
            if session.get('role') != 'admin':
                abort(403)

            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT admin_type, is_active FROM admin WHERE u_id = %s",
                        (session['user_id'],)
                    )
                    admin_row = cur.fetchone()
            finally:
                conn.close()

            if not admin_row or not admin_row['is_active']:
                session.clear()
                abort(403)

            # Refresh authorization details on every protected request so deactivation
            # and permission changes take effect immediately.
            session['admin_type'] = admin_row['admin_type']
            session['is_main_admin'] = admin_row['admin_type'] == 'main'

            if main_only and admin_row['admin_type'] != 'main':
                abort(403)
            if allowed_types and admin_row['admin_type'] != 'main' and admin_row['admin_type'] not in allowed_types:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ---------- password reset links ----------
def _password_fingerprint(password_hash):
    """Short fingerprint of the current password hash: once the password changes, old reset links stop working."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def make_reset_token(user_id, password_hash):
    """Signed, time-limited token for the 'forgot password' link."""
    s = URLSafeTimedSerializer(current_app.secret_key, salt='password-reset')
    return s.dumps({'u': int(user_id), 'f': _password_fingerprint(password_hash)})


def read_reset_token(token, max_age_seconds):
    """-> (user_id, fingerprint), or None if the token is edited, invalid or expired."""
    s = URLSafeTimedSerializer(current_app.secret_key, salt='password-reset')
    try:
        data = s.loads(token, max_age=max_age_seconds)
        return int(data['u']), str(data['f'])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


def reset_fingerprint_matches(password_hash, fingerprint):
    return _password_fingerprint(password_hash) == fingerprint