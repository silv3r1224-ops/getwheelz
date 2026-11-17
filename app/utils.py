import hashlib
import os
import secrets
from functools import wraps

from flask import abort, current_app, flash, redirect, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import crypto

UPLOAD_FOLDER = os.path.join("app", "static", "uploads", "workshops")


def sniff_image(head):
    """File type from the first bytes of the file itself (never from its name): 'png', 'jpg', 'webp' or None."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def save_upload_image(file, folder, prefix):
    """Save an uploaded picture under a random name and return that name, or None if it is not a real image.

    The type is checked from the file's contents, the person's file name is never used (no path tricks, no
    guessable names, no double extensions like photo.php.jpg), and the extension is the one the content proves."""
    if not file or not file.filename:
        return None
    head = file.stream.read(16)
    file.stream.seek(0)
    ext = sniff_image(head)
    if ext is None:
        return None
    os.makedirs(folder, exist_ok=True)
    name = f"{prefix}_{secrets.token_hex(12)}.{ext}"
    file.save(os.path.join(folder, name))
    return name


def safe_back(default):
    """Where to send the person back to: the page they came from if it is on this site, else `default`."""
    ref = request.referrer or ""
    if ref.startswith(request.host_url):
        return ref
    return default


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

def encode_wid(w_id):
    """workshop id -> encrypted token for use in URLs (see app/crypto.py)"""
    return crypto.seal("workshop-preview", w_id)


def decode_wid(token):
    """encrypted token -> workshop id, or None if the token was edited or is invalid"""
    return crypto.open_("workshop-preview", token)


def encode_uid(u_id):
    """user id -> encrypted token for profile URLs"""
    return crypto.seal("user-profile", u_id)


def decode_uid(token):
    return crypto.open_("user-profile", token)


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