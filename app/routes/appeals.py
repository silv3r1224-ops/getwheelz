"""Appeals (Phase 6; spec sections 4 and 9).

* a suspended person cannot log in, so the Appeal button lives on the suspension screen, reached right
  after they give their correct password (or sign in with Google); a signed, 30-minute token proves it
  was them, and the database request acts as that person for this one step (like the Google linking step);
* a rejected owner appeals from the rejection notice's popup (or the dashboard banner);
* an admin answers every appeal by upholding or overturning it with a note. Who may answer is decided
  when the appeal is filed (app/appeals.py): the main admin, or the area's sub-admin when the main
  admin made the original decision. Overturning restores the account or the listing and tells
  everyone involved.
"""
import logging

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import appeals, booking_events
from app import booking_rules as rules
from app.catalog import clear_catalog_cache
from app.db import get_db_connection, set_current_user
from app.utils import admin_access_required, role_required

appeals_bp = Blueprint('appeals', __name__)

TOKEN_MAX_AGE = 30 * 60  # seconds: how long the suspension screen stays reachable after a correct password
_SALT = 'suspension-appeal'


# ---------------------------------------------------------------- the suspension-screen token
def make_appeal_token(u_id):
    return URLSafeTimedSerializer(current_app.secret_key, salt=_SALT).dumps({'u': int(u_id)})


def read_appeal_token(token):
    """The user id in a valid, unexpired token, else None."""
    try:
        data = URLSafeTimedSerializer(current_app.secret_key, salt=_SALT).loads(token or '', max_age=TOKEN_MAX_AGE)
        return int(data['u'])
    except (BadSignature, SignatureExpired, KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------- who reviews (needs the admin table)
def _reviewer_for(decided_by_uid, appellant_role):
    """``(reviewer_type, needs_second_reviewer)`` for a new appeal (rule: app/appeals.py).

    Reads the admin table, which the appellant cannot see under row-level security, so this one
    read-only lookup runs on its own short connection with an admin context, like the booking sweep.
    """
    import psycopg2
    import psycopg2.extras

    cfg = current_app.config
    conn = psycopg2.connect(host=cfg['DB_HOST'], port=cfg['DB_PORT'], database=cfg['DB_NAME'],
                            user=cfg['DB_USER'], password=cfg['DB_PASSWORD'],
                            cursor_factory=psycopg2.extras.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.luid', '0', false)")
            cur.execute("SELECT set_config('app.lrole', 'admin', false)")
            cur.execute("SELECT set_config('app.ladmin', 'main', false)")
            decided_by_type = None
            if decided_by_uid:
                cur.execute("SELECT admin_type FROM admin WHERE u_id = %s", (decided_by_uid,))
                row = cur.fetchone()
                decided_by_type = row['admin_type'] if row else None
            area = appeals.area_admin_type(appellant_role)
            cur.execute("SELECT COUNT(*) AS n FROM admin WHERE admin_type = %s AND is_active", (area,))
            active_area_admins = cur.fetchone()['n'] if area else 0
        return appeals.choose_reviewer(decided_by_type, appellant_role, active_area_admins)
    finally:
        conn.close()


def _file_appeal(cur, kind, u_id, role, message, decided_by_uid, w_id=None):
    reviewer_type, needs_second = _reviewer_for(decided_by_uid, role)
    cur.execute("""
        INSERT INTO appeal (kind, u_id, w_id, message, decided_by_admin, reviewer_type,
                            needs_second_reviewer, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (kind, u_id, w_id, message, decided_by_uid, reviewer_type, needs_second, rules.now()))


# ---------------------------------------------------------------- suspension screen
def _suspended_state(cur, u_id):
    cur.execute("SELECT u_id, name, role, is_suspended, suspended_by, suspended_at FROM users WHERE u_id = %s",
                (u_id,))
    user = cur.fetchone()
    if not user or not user['is_suspended'] or user['role'] not in appeals.ADMIN_AREA_FOR_ROLE:
        return user, None
    cur.execute("""
        SELECT status, decision_note, created_at, reviewed_at FROM appeal
        WHERE u_id = %s AND kind = 'suspension' ORDER BY created_at DESC LIMIT 1
    """, (u_id,))
    last = cur.fetchone()
    can = appeals.can_appeal(user['suspended_at'], last['created_at'] if last else None,
                             bool(last and last['status'] == appeals.OPEN))
    return user, {'last': dict(last) if last else None, 'can_appeal': can}


@appeals_bp.route('/account-suspended')
def suspended():
    token = request.args.get('t', '')
    u_id = read_appeal_token(token)
    if u_id is None:
        flash('That link has expired. Log in again to see your account status.', 'error')
        return redirect(url_for('main.index'))
    conn = get_db_connection()
    try:
        set_current_user(u_id, '')
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE u_id = %s", (u_id,))
            row = cur.fetchone()
            if row:
                set_current_user(u_id, row['role'])
            user, state = _suspended_state(cur, u_id)
    finally:
        conn.close()
    if user is None or not user['is_suspended']:
        flash('Your account is not suspended. You can log in.', 'success')
        return redirect(url_for('main.index'))
    return render_template('auth/suspended.html', token=token, user=user, state=state or {'last': None, 'can_appeal': False},
                           suspended_at=user['suspended_at'])


@appeals_bp.route('/account-suspended/appeal', methods=['POST'])
def suspended_appeal():
    token = request.form.get('t', '')
    u_id = read_appeal_token(token)
    if u_id is None:
        flash('That link has expired. Log in again to appeal.', 'error')
        return redirect(url_for('main.index'))
    back = redirect(url_for('appeals.suspended', t=token))
    message, error = appeals.clean_message(request.form.get('message'))
    if error:
        flash(error, 'error')
        return back
    conn = get_db_connection()
    try:
        set_current_user(u_id, '')
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE u_id = %s", (u_id,))
            row = cur.fetchone()
            if not row:
                abort(404)
            set_current_user(u_id, row['role'])  # acts as this person for this one request
            user, state = _suspended_state(cur, u_id)
            if state is None:
                flash('There is nothing to appeal: your account is not suspended.', 'error')
                conn.rollback()
                return back
            if not state['can_appeal']:
                flash('You have already appealed this decision.', 'error')
                conn.rollback()
                return back
            _file_appeal(cur, appeals.KIND_SUSPENSION, u_id, user['role'], message, user['suspended_by'])
        conn.commit()
        flash('Your appeal was sent. An admin will review it and the answer will show on this page.', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not file a suspension appeal for user %s', u_id)
        flash('Could not send your appeal. Please try again.', 'error')
    finally:
        conn.close()
    return back


# ---------------------------------------------------------------- rejected listing
@appeals_bp.route('/appeals/listing', methods=['POST'])
@role_required('owner')
def listing_appeal():
    """A rejected owner appeals the rejection of one of their workshops (once per rejection)."""
    w_id = request.form.get('w_id', type=int)
    message, error = appeals.clean_message(request.form.get('message'))
    back = redirect(request.referrer if (request.referrer or '').startswith(request.host_url)
                    else url_for('main.inbox'))
    if error or w_id is None:
        flash(error or 'Please choose the workshop to appeal for.', 'error')
        return back
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT w.w_id, w.status, w.decided_by, w.decided_at,
                       (SELECT MAX(a.created_at) FROM appeal a WHERE a.u_id = %s AND a.kind = 'listing'
                          AND a.w_id = w.w_id) AS last_appeal_at,
                       EXISTS (SELECT 1 FROM appeal a WHERE a.u_id = %s AND a.kind = 'listing'
                          AND a.w_id = w.w_id AND a.status = 'open') AS has_open
                FROM workshop w JOIN owner o ON o.o_id = w.o_id
                WHERE w.w_id = %s AND o.u_id = %s
            """, (session['user_id'], session['user_id'], w_id, session['user_id']))
            ws = cur.fetchone()
            if not ws or ws['status'] != 'rejected':
                flash('Only a rejected workshop of yours can be appealed.', 'error')
            elif not appeals.can_appeal(ws['decided_at'], ws['last_appeal_at'], ws['has_open']):
                flash('You have already appealed this decision.', 'error')
            else:
                _file_appeal(cur, appeals.KIND_LISTING, session['user_id'], 'owner', message,
                             ws['decided_by'], w_id)
                flash('Your appeal was sent. An admin will review it and tell you the answer in your inbox.',
                      'success')
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception('Could not file a listing appeal')
        flash('Could not send your appeal. Please try again.', 'error')
    finally:
        conn.close()
    return back


# ---------------------------------------------------------------- the admin's answer
@appeals_bp.route('/appeals/<sealed(appeal):ap_id>/decide', methods=['POST'])
@admin_access_required()
def decide(ap_id):
    """Uphold or overturn an appeal assigned to THIS admin's type, with a required note."""
    back = redirect(url_for('main.inbox') + '#panelReports')
    status = appeals.decision_status(request.form.get('decision'))
    note, error = appeals.clean_note(request.form.get('note'))
    if status is None or error:
        flash(error or 'Please choose to uphold or overturn the appeal.', 'error')
        return back
    admin_type = session.get('admin_type')
    admin_uid = session['user_id']
    now = rules.now()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # only an OPEN appeal assigned to this admin's type (the main admin cannot answer a
            # sub-admin's case, nor a sub-admin another's)
            cur.execute("""
                UPDATE appeal SET status = %s, decision_note = %s, reviewed_by = %s, reviewed_at = %s
                WHERE ap_id = %s AND status = 'open' AND reviewer_type = %s
                RETURNING kind, u_id, w_id, decided_by_admin
            """, (status, note, admin_uid, now, ap_id, admin_type))
            a = cur.fetchone()
            if a is None:
                conn.rollback()
                flash('That appeal is not assigned to you, or it was already answered.', 'error')
                return back

            what = 'account suspension' if a['kind'] == appeals.KIND_SUSPENSION else 'workshop rejection'
            if status == appeals.OVERTURNED:
                if a['kind'] == appeals.KIND_SUSPENSION:
                    cur.execute("""
                        UPDATE users SET is_suspended = FALSE, suspended_by = NULL, suspended_at = NULL
                        WHERE u_id = %s AND is_suspended
                    """, (a['u_id'],))
                else:
                    cur.execute("""
                        UPDATE workshop SET status = 'approved', rejection_reason = NULL,
                                            decided_by = %s, decided_at = %s
                        WHERE w_id = %s AND status = 'rejected'
                    """, (admin_uid, now, a['w_id']))
                if cur.rowcount == 0:
                    conn.rollback()
                    flash('That decision has already changed (the account is no longer suspended, or the '
                          'workshop is no longer rejected), so there is nothing to overturn.', 'error')
                    return back

            # tell everyone involved, in the same transaction
            result = 'overturned' if status == appeals.OVERTURNED else 'upheld'
            restored = (' Your account has been restored: you can log in again.'
                        if status == appeals.OVERTURNED and a['kind'] == appeals.KIND_SUSPENSION else
                        ' Your workshop is approved and visible to customers again.'
                        if status == appeals.OVERTURNED else '')
            booking_events.send_notice(
                cur, a['u_id'], f'Your appeal was {result}',
                f"An admin reviewed your appeal against the {what} and {result} it.{restored}\n\nNote from the "
                f"reviewer: {note}", now)
            if a['decided_by_admin'] and a['decided_by_admin'] != admin_uid:
                booking_events.send_notice(
                    cur, a['decided_by_admin'], f'An appeal against your decision was {result}',
                    f"The appeal against the {what} you decided (appeal #{ap_id}) was {result} by another "
                    f"admin.\n\nTheir note: {note}", now)
        conn.commit()
        if status == appeals.OVERTURNED:
            clear_catalog_cache()
        flash('Appeal overturned: the decision was reversed and everyone involved was told.'
              if status == appeals.OVERTURNED else 'Appeal upheld: the original decision stands. The person was told.',
              'success')
    except Exception:
        conn.rollback()
        logging.exception('Could not answer appeal %s', ap_id)
        flash('Could not save your answer. Please try again.', 'error')
    finally:
        conn.close()
    return back
