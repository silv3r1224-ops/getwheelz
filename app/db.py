import psycopg2
import psycopg2.extras
from flask import current_app, g, has_request_context, session


def _apply_session_context(conn):
    """Tell PostgreSQL who this request acts as (used by the row-level-security policies).

    Values live on the session, so they survive commit/rollback inside a request; the
    connection itself is per-request (created here, closed at teardown), so nothing leaks
    into other requests. When no one is signed in the values are empty, which the policies
    treat as "no access" (except the few explicitly public operations).
    """
    if has_request_context():
        user_id = session.get("user_id") or 0
        role = session.get("role") or ""
        admin_type = session.get("admin_type") or ""
    else:
        user_id, role, admin_type = 0, "", ""
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.luid', %s, false)", (str(user_id),))
        cur.execute("SELECT set_config('app.lrole', %s, false)", (role,))
        cur.execute("SELECT set_config('app.ladmin', %s, false)", (admin_type,))


def get_db_connection():
    conn = psycopg2.connect(
        host=current_app.config['DB_HOST'],
        port=current_app.config['DB_PORT'],
        database=current_app.config['DB_NAME'],
        user=current_app.config['DB_USER'],
        password=current_app.config['DB_PASSWORD'],
        cursor_factory=psycopg2.extras.DictCursor
    )
    _apply_session_context(conn)
    g.setdefault('_db_conns', []).append(conn)
    return conn


def set_current_user(user_id, role="", admin_type=""):
    """Act as `user_id` on the connections of this request.

    Used by flows that must perform a sensitive write BEFORE the session exists:
    the Google account-linking UPDATE and the password-reset UPDATE (both are
    authorized by something else — Google's verified email / the signed reset token).
    """
    for conn in g.get("_db_conns", []):
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.luid', %s, false)", (str(user_id),))
            cur.execute("SELECT set_config('app.lrole', %s, false)", (role,))
            cur.execute("SELECT set_config('app.ladmin', %s, false)", (admin_type,))


def close_db_connections(exc=None):
    for conn in g.pop('_db_conns', []):
        try:
            conn.close()
        except Exception:
            pass
