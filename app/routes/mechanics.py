from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import booking_events, contact, vehicles
from app import booking_rules as rules
from app.db import get_db_connection
from app.routes.main import LEAVE_REASON_CATEGORIES
from app.utils import decode_uid, decode_wid, role_required

mechanics_bp = Blueprint('mechanics', __name__)


@mechanics_bp.route('/home')
@role_required('mechanic')
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT m_id, w_id, experience_yrs, active_stat
        FROM mechanic WHERE u_id = %s
    """, (session['user_id'],))
    mechanic = cur.fetchone()

    # assigned: show workshop dashboard
    if mechanic and mechanic['w_id']:
        w_id = mechanic['w_id']

        # owner mapping comes from the postgres-owned SECURITY DEFINER function so this
        # mechanic dashboard keeps working under RLS (owner table is hidden from non-admins)
        cur.execute("""
            SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path, w.capacity,
            ow.u_id AS owner_uid, ow.name AS owner_name,
            ow.profile_picture AS owner_picture, ow.since AS owner_since,
            ow.workshop_count AS owner_workshops
            FROM workshop w
            LEFT JOIN LATERAL public_workshop_owner(w.o_id) AS ow ON true
            WHERE w.w_id = %s
        """, (w_id,))
        workshop = cur.fetchone()

        cur.execute("""
            SELECT b.b_id, b.requested_time, b.status,
                   (SELECT public_booking_customer_name(b.b_id)) AS customer_name, sc.s_name,
            b.assigned_m_id, mu.name AS mechanic_name
            FROM booking b
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            LEFT JOIN mechanic bm ON b.assigned_m_id = bm.m_id
            LEFT JOIN users mu ON bm.u_id = mu.u_id
            WHERE b.w_id = %s
            ORDER BY b.requested_time DESC
        """, (w_id,))
        bookings = [dict(b) for b in cur.fetchall()]   # plain dicts, so the filter fields below can be added

        cur.execute("""
            SELECT m.m_id, u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = %s
            ORDER BY m.experience_yrs DESC NULLS LAST, u.name
        """, (w_id,))
        team = cur.fetchall()

        # my pending leave request, and a recent rejection (shown for 7 days)
        cur.execute("""
            SELECT leave_requested_at AS created_at, leave_reason AS reason
            FROM mechanic
            WHERE m_id = %s AND leave_requested_at IS NOT NULL
        """, (mechanic['m_id'],))
        leave_pending = cur.fetchone()

        cur.execute("""
            SELECT leave_rejected_at AS decided_at
            FROM mechanic
            WHERE m_id = %s AND leave_rejected_at > NOW() - INTERVAL '7 days'
        """, (mechanic['m_id'],))
        leave_rejected = cur.fetchone()

        cur.close()
        conn.close()

        # everything the bookings filter uses is worked out here, once (as on the owner dashboard),
        # so "today" and "this month" follow the server's clock, not the browser's
        today = datetime.now().date()
        this_week = today.isocalendar()[:2]
        booking_counts = dict.fromkeys(('all', 'todo', 'mine', 'pending', 'confirmed', 'history'), 0)
        for b in bookings:
            day = b['requested_time'].date()
            periods = []
            if day == today:
                periods.append('today')
            if day.isocalendar()[:2] == this_week:
                periods.append('week')
            if (day.year, day.month) == (today.year, today.month):
                periods.append('month')
            b['periods'] = ' '.join(periods)
            b['is_today'] = day == today
            b['ts'] = int(b['requested_time'].timestamp())
            assigned_to_me = b['assigned_m_id'] == mechanic['m_id']
            b['is_todo'] = assigned_to_me and b['status'] in rules.ACCEPTED_STATUSES   # still to be done by me
            b['status_label'] = rules.label(b['status'])
            b['is_mine'] = assigned_to_me and b['status'] in ('confirmed', 'in_progress', 'completed')
            booking_counts['all'] += 1
            booking_counts['todo'] += b['is_todo']
            booking_counts['mine'] += b['is_mine']
            if b['status'] == 'pending':
                booking_counts['pending'] += 1
            elif b['status'] in rules.ACCEPTED_STATUSES:
                booking_counts['confirmed'] += 1
            else:
                booking_counts['history'] += 1

        # jobs the owner has assigned to this mechanic (cancelled ones are hidden)
        my_jobs = [b for b in bookings
                   if b['assigned_m_id'] == mechanic['m_id']
                   and b['status'] in ('confirmed', 'in_progress', 'completed')]

        stats = {
            'total': len(bookings),
            'pending': sum(1 for b in bookings if b['status'] == 'pending'),
            'confirmed': sum(1 for b in bookings if b['status'] in rules.ACCEPTED_STATUSES),
            'completed': sum(1 for b in bookings if b['status'] == 'completed'),
            'mine': sum(1 for b in bookings
                        if b['assigned_m_id'] == mechanic['m_id'] and b['status'] in rules.ACCEPTED_STATUSES),
        }
        return render_template('mechanics/mechanic_dashboard.html',
                                workshop=workshop, bookings=bookings, mechanic=mechanic,
                                my_jobs=my_jobs, team=team, stats=stats,
                                leave_pending=leave_pending, leave_rejected=leave_rejected,
                                booking_counts=booking_counts)

    # unassigned: browsable workshop list
    if not mechanic:
        cur.close()
        conn.close()
        abort(403)

    cur.execute("""
        SELECT w.w_id, w.name, w.address, w.photo_path, w.capacity,
        w.latitude, w.longitude,
        (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS total_mechanics,
        w.capacity - (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS open_slots,
        array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
        FROM workshop w
        LEFT JOIN service s ON s.w_id = w.w_id
        LEFT JOIN service_catalog sc ON s.sc_id = sc.sc_id
        WHERE w.status = 'approved'
        GROUP BY w.w_id, w.name, w.address, w.photo_path, w.capacity, w.latitude, w.longitude
        ORDER BY w.w_id DESC
    """)
    workshops = cur.fetchall()

    # workshops this mechanic already has a pending request with
    cur.execute("SELECT w_id FROM join_request WHERE m_id = %s AND status = 'pending'",
                (mechanic['m_id'],))
    requested_ids = {r['w_id'] for r in cur.fetchall()}

    cur.close()
    conn.close()

    # classify for the browse page
    requested = [w for w in workshops if w['w_id'] in requested_ids]
    hiring = sorted((w for w in workshops
                    if w['w_id'] not in requested_ids and w['open_slots'] > 0),
                    key=lambda w: -w['open_slots'])
    full = [w for w in workshops
            if w['w_id'] not in requested_ids and w['open_slots'] <= 0]
    all_services = sorted({s for w in workshops for s in (w['service_names'] or [])})

    return render_template('mechanics/browse.html',
                            workshops=workshops, requested_ids=requested_ids,
                            requested=requested, hiring=hiring, full=full,
                            all_services=all_services)


@mechanics_bp.route('/workshop/<token>')
@role_required('mechanic')
def workshop_preview(token):
    w_id = decode_wid(token)
    if w_id is None:
        abort(404)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT m_id, w_id FROM mechanic WHERE u_id = %s", (session['user_id'],))
    me = cur.fetchone()
    if not me:
        cur.close()
        conn.close()
        abort(403)

    # owner mapping via the SECURITY DEFINER function (owner table is hidden under RLS)
    cur.execute("""
        SELECT w.w_id, w.name, w.address, w.contact_no, w.whatsapp_no, w.status, w.photo_path,
        w.latitude, w.longitude, w.capacity, w.serves_cars, w.serves_two_wheelers,
        ow.u_id AS owner_uid, ow.name AS owner_name,
        ow.profile_picture AS owner_picture, ow.since AS owner_since,
        ow.workshop_count AS owner_workshops
        FROM workshop w
        LEFT JOIN LATERAL public_workshop_owner(w.o_id) AS ow ON true
        WHERE w.w_id = %s
    """, (w_id,))
    workshop = cur.fetchone()
    if not workshop or workshop["status"] != "approved":
        cur.close()
        conn.close()
        abort(404)

    cur.execute("""
        SELECT sc.s_name, s.price_range, s.duration
        FROM service s
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        WHERE s.w_id = %s
        ORDER BY sc.s_name
    """, (w_id,))
    services = cur.fetchall()

    # team: only public-facing details (no email or contact info)
    cur.execute("""
        SELECT m.m_id, u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat
        FROM mechanic m
        JOIN users u ON m.u_id = u.u_id
        WHERE m.w_id = %s
        ORDER BY m.experience_yrs DESC NULLS LAST, u.name
    """, (w_id,))
    team = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*) AS total,
        COUNT(*) FILTER (WHERE status = 'completed') AS completed
        FROM booking WHERE w_id = %s
    """, (w_id,))
    jobs = cur.fetchone()

    cur.execute("SELECT 1 FROM join_request WHERE m_id = %s AND w_id = %s AND status = 'pending'",
                (me['m_id'], w_id))
    pending = cur.fetchone() is not None

    cur.close()
    conn.close()

    # a signed-in mechanic may use the Call / WhatsApp buttons (app/contact.py decides)
    contact_buttons = contact.buttons_for('mechanic', workshop['contact_no'], workshop['whatsapp_no'])
    served_types = vehicles.workshop_types(workshop['serves_cars'], workshop['serves_two_wheelers'])
    return render_template('mechanics/workshop_preview.html', contact_buttons=contact_buttons,
                            workshop=workshop, services=services, team=team, jobs=jobs,
                            my_m_id=me['m_id'], my_workshop=me['w_id'], pending=pending,
                            open_slots=workshop['capacity'] - len(team),
                            served_types=served_types)

@mechanics_bp.route('/profile/<token>')
@role_required('mechanic')
def user_profile(token):
    """Read-only profile of a workshop owner or a working mechanic."""
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT u_id, name, role, profile_picture, created_at
        FROM users WHERE u_id = %s AND role IN ('owner', 'mechanic')
    """, (u_id,))
    person = cur.fetchone()
    if not person:
        cur.close()
        conn.close()
        abort(404)

    workshops, mech, jobs = [], None, None

    if person['role'] == 'owner':
        # o_ids via the SECURITY DEFINER mapping (owner table is hidden under RLS)
        cur.execute("SELECT public_owner_workshops(%s) AS o_id", (u_id,))
        o_ids = [r["o_id"] for r in cur.fetchall()]
        if o_ids:
            cur.execute("""
                SELECT w.w_id, w.name, w.address, w.photo_path, w.capacity,
                (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size
                FROM workshop w
                WHERE w.o_id = ANY(%s) AND w.status = 'approved'
                ORDER BY w.name
            """, (o_ids,))
            workshops = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE b.status = 'completed') AS completed
                FROM booking b
                JOIN workshop w ON b.w_id = w.w_id
                WHERE w.o_id = ANY(%s)
            """, (o_ids,))
            jobs = cur.fetchone()['completed']
    else:
        cur.execute("""
            SELECT m.experience_yrs, m.active_stat, w.w_id, w.name AS workshop_name,
            w.address, w.photo_path
            FROM mechanic m JOIN workshop w ON m.w_id = w.w_id
            WHERE m.u_id = %s
        """, (u_id,))
        mech = cur.fetchone()
        if not mech:          # mechanics without a workshop are not publicly viewable
            cur.close()
            conn.close()
            abort(404)

    cur.close()
    conn.close()

    return render_template('mechanics/user_profile.html',
                            person=person, workshops=workshops, mech=mech, jobs=jobs)

@mechanics_bp.route('/join_request/<sealed(workshop):w_id>', methods=['POST'])
@role_required('mechanic')
def send_join_request(w_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT m_id, w_id FROM mechanic WHERE u_id = %s", (session['user_id'],))
    mechanic = cur.fetchone()

    if mechanic['w_id']:
        flash('You already belong to a workshop.', 'error')
    else:
        cur.execute("SELECT 1 FROM workshop WHERE w_id = %s AND status = 'approved'", (w_id,))
        if not cur.fetchone():
            flash('Workshop not found.', 'error')
        else:
            cur.execute("""
                INSERT INTO join_request (m_id, w_id)
                VALUES (%s, %s)
                ON CONFLICT (m_id, w_id) WHERE status = 'pending' DO NOTHING
            """, (mechanic['m_id'], w_id))
            conn.commit()
            flash('Join request sent. Waiting for the owner to respond.', 'success')

    cur.close()
    conn.close()
    return redirect(url_for('mechanics.home'))


@mechanics_bp.route('/cancel_request/<sealed(workshop):w_id>', methods=['POST'])
@role_required('mechanic')
def cancel_join_request(w_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM join_request
        WHERE w_id = %s AND status = 'pending'
        AND m_id = (SELECT m_id FROM mechanic WHERE u_id = %s)
    """, (w_id, session['user_id']))
    conn.commit()
    cur.close()
    conn.close()

    flash('Request cancelled.', 'success')
    return redirect(url_for('mechanics.home'))


@mechanics_bp.route('/leave_request', methods=['POST'])
@role_required('mechanic')
def request_leave():
    """A mechanic asks to leave; the owner decides."""
    reasons = request.form.getlist('reason')
    details = (request.form.get('details') or '').strip()[:400]
    chosen = [LEAVE_REASON_CATEGORIES[r] for r in reasons if r in LEAVE_REASON_CATEGORIES]
    parts = chosen + ([details] if details else [])
    reason = ', '.join(parts)[:300] or None

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE mechanic
        SET leave_requested_at = NOW(), leave_reason = %s, leave_rejected_at = NULL
        WHERE u_id = %s AND w_id IS NOT NULL AND leave_requested_at IS NULL
    """, (reason, session['user_id']))
    sent = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    flash('Leave request sent. You stay in the workshop until the owner approves it.'
        if sent else 'You already have a pending leave request.', 'success' if sent else 'error')
    return redirect(url_for('mechanics.home'))


@mechanics_bp.route('/status', methods=['POST'])
@role_required('mechanic')
def set_status():
    """A mechanic marks themselves 'active' (active for work now) or 'inactive' (absent)."""
    status = request.form.get('status')
    if status not in ('active', 'inactive'):
        abort(400)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE mechanic SET active_stat = %s WHERE u_id = %s",
                        (status, session['user_id']))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    flash('You are now shown as active for work.' if status == 'active'
          else 'You are now shown as absent / inactive.', 'success')
    return redirect(url_for('mechanics.home'))


def _job_step(booking_id, action):
    """Move a job the owner assigned to THIS mechanic one step on (start, then complete).

    One atomic statement: the booking must be in the right status, assigned to this mechanic, and
    the mechanic must still work in the booking's workshop. The customer and the owner are told in
    the same transaction. Returns True if the job moved.
    """
    new_status, allowed_from = rules.MECHANIC_ACTIONS[action]
    event = {'start': 'started', 'complete': 'completed'}[action]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            changed = booking_events.change_status(
                cur, booking_id, new_status, allowed_from,
                scope_sql="""AND assigned_m_id = (
                                 SELECT m.m_id FROM mechanic m
                                 WHERE m.u_id = %s AND m.w_id = booking.w_id)""",
                scope_params=(session['user_id'],),
            )
            if changed:
                booking_events.announce(cur, booking_id, event, actor_u_id=session['user_id'])
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@mechanics_bp.route('/booking/<sealed(booking):booking_id>/start', methods=['POST'])
@role_required('mechanic')
def start_job(booking_id):
    """A mechanic starts an accepted job that the owner assigned to them (accepted -> in progress)."""
    if _job_step(booking_id, 'start'):
        flash('Job started. The customer has been told.', 'success')
    else:
        flash('You can only start accepted jobs that are assigned to you.', 'error')
    return redirect(url_for('mechanics.home') + '#mMyJobs')


@mechanics_bp.route('/booking/<sealed(booking):booking_id>/complete', methods=['POST'])
@role_required('mechanic')
def complete_job(booking_id):
    """A mechanic completes a job that is in progress and assigned to them."""
    if _job_step(booking_id, 'complete'):
        flash('Job marked as completed. The customer can now pay.', 'success')
    else:
        flash('You can only complete jobs that are in progress and assigned to you.', 'error')
    return redirect(url_for('mechanics.home') + '#mMyJobs')


@mechanics_bp.route('/leave_request/cancel', methods=['POST'])
@role_required('mechanic')
def cancel_leave_request():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE mechanic SET leave_requested_at = NULL, leave_reason = NULL
        WHERE u_id = %s
    """, (session['user_id'],))
    conn.commit()
    cur.close()
    conn.close()

    flash('Leave request cancelled.', 'success')
    return redirect(url_for('mechanics.home'))