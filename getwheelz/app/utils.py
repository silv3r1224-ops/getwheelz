from functools import wraps
from flask import session, redirect, url_for,abort

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
            print("DEBUG — session role:", session.get('role'), "| allowed:", allowed_roles)
            if session.get('role') not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator