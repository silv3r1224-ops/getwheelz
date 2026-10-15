from flask import abort, Blueprint, render_template, redirect, url_for, session, flash, request
from app.db import get_db_connection
from app.utils import role_required, decode_wid, decode_uid

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

        cur.execute("""
            SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path, w.capacity,
            u.name AS owner_name, u.u_id AS owner_uid
            FROM workshop w
            JOIN owner o ON w.o_id = o.o_id
            JOIN users u ON o.u_id = u.u_id
            WHERE w.w_id = %s
        """, (w_id,))
        workshop = cur.fetchone()

        cur.execute("""
            SELECT b.b_id, b.requested_time, b.status, u.name AS customer_name, sc.s_name
            FROM booking b
            JOIN customer c ON b.c_id = c.c_id
            JOIN users u ON c.u_id = u.u_id
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE b.w_id = %s
            ORDER BY b.requested_time DESC
        """, (w_id,))
        bookings = cur.fetchall()

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

        stats = {
            'total': len(bookings),
            'pending': sum(1 for b in bookings if b['status'] == 'pending'),
            'confirmed': sum(1 for b in bookings if b['status'] == 'confirmed'),
            'completed': sum(1 for b in bookings if b['status'] == 'completed'),
        }
        return render_template('mechanics/mechanic_dashboard.html',
                                workshop=workshop, bookings=bookings, mechanic=mechanic,
                                team=team, stats=stats,
                                leave_pending=leave_pending, leave_rejected=leave_rejected)

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

    cur.execute("""
        SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path,
        w.latitude, w.longitude, w.capacity, u.name AS owner_name, u.u_id AS owner_uid,
        u.profile_picture AS owner_picture, u.created_at AS owner_since,
        (SELECT COUNT(*) FROM workshop w2 WHERE w2.o_id = w.o_id) AS owner_workshops
        FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        JOIN users u ON o.u_id = u.u_id
        WHERE w.w_id = %s
    """, (w_id,))
    workshop = cur.fetchone()
    if not workshop:
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

    return render_template('mechanics/workshop_preview.html',
                            workshop=workshop, services=services, team=team, jobs=jobs,
                            my_m_id=me['m_id'], my_workshop=me['w_id'], pending=pending,
                            open_slots=workshop['capacity'] - len(team))

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
        cur.execute("""
            SELECT w.w_id, w.name, w.address, w.photo_path, w.capacity,
            (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size
            FROM workshop w JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            ORDER BY w.name
        """, (u_id,))
        workshops = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE b.status = 'completed') AS completed
            FROM booking b
            JOIN workshop w ON b.w_id = w.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
        """, (u_id,))
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

@mechanics_bp.route('/join_request/<int:w_id>', methods=['POST'])
@role_required('mechanic')
def send_join_request(w_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT m_id, w_id FROM mechanic WHERE u_id = %s", (session['user_id'],))
    mechanic = cur.fetchone()

    if mechanic['w_id']:
        flash('You already belong to a workshop.', 'error')
    else:
        cur.execute("SELECT 1 FROM workshop WHERE w_id = %s", (w_id,))
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


@mechanics_bp.route('/cancel_request/<int:w_id>', methods=['POST'])
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
    reason = (request.form.get('reason') or '').strip()[:300] or None

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