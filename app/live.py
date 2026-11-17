"""Live updates without reloading.

The browser asks /live/version every few seconds. The answer is one number that changes whenever any
row changes in the tables people can see (workshops, services, bookings, reviews, users, ...). When the number
moves, the page quietly fetches its own current version and patches only what changed (static/js/live.js).

Why this way:
* It needs no new tables and no changes in the routes: PostgreSQL already counts inserts, updates and
  deletes per table (pg_stat_user_tables), so every write is noticed, whoever made it and however.
* It works with any number of gunicorn workers or servers, because the counter lives in the database.
* It sends nothing private: the number only says "something changed". Each browser then fetches its OWN page with
  its OWN login, so people only ever see what they are allowed to see.
* Tables that change just because somebody read something (inbox read marks, dismissals, consent logs) are left
  out, so reading a message does not refresh other people's pages.
"""
import logging
import threading
import time

from flask import Blueprint, jsonify

from app.db import get_db_connection

live_bp = Blueprint("live", __name__)
log = logging.getLogger(__name__)

# changes in these tables are noise for everyone else
_QUIET_TABLES = ("inbox_read_state", "inbox_dismissal", "inbox_message_state", "user_consent", "bookmark")

_cache = {"at": 0.0, "v": "0"}
_lock = threading.Lock()
_CACHE_SECONDS = 1.0   # many browsers polling at once cost the database one query a second per worker


def _read_version():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(SUM(n_tup_ins + n_tup_upd + n_tup_del), 0)::bigint "
            "FROM pg_stat_user_tables WHERE relname <> ALL(%s)",
            (list(_QUIET_TABLES),),
        )
        return str(cur.fetchone()[0])


def current_version():
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] < _CACHE_SECONDS:
            return _cache["v"]
    try:
        v = _read_version()
    except Exception:  # database busy or stats not readable: say "unknown", the page just waits
        log.exception("live version unavailable")
        return None
    with _lock:
        _cache["at"], _cache["v"] = now, v
    return v


@live_bp.route("/live/version")
def version():
    v = current_version()
    resp = jsonify(v=v)
    resp.headers["Cache-Control"] = "no-store"
    return resp


# Pages where somebody is in the middle of a one-way flow (signing in, paying, accepting terms): these keep the
# ordinary full-page behaviour and are never refreshed underneath the person.
LIVE_OFF_ENDPOINTS = frozenset({
    "auth.forgot_password", "auth.reset_password", "legal.accept", "bookings.new", "bookings.pay",
    "appeals.suspended", "appeals.suspended_appeal",
})
