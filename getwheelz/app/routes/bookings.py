from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, abort
from app.db import get_db_connection
from app.utils import role_required

bookings_bp = Blueprint('bookings', __name__)

@bookings_bp.route('/new/<int:w_id>', methods=['GET', 'POST'])
@role_required('customer')
def new(w_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT w_id, name, address FROM workshop WHERE w_id = %s", (w_id,))
            workshop = cur.fetchone()
            if workshop is None:
                abort(404)

            cur.execute("""
                SELECT s.s_id, sc.s_name, s.price_range, s.duration
                FROM service s
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE s.w_id = %s
            """, (w_id,))
            services = cur.fetchall()

            selected_service = request.args.get('s_id', type=int)
            time_value = ''

            if request.method == 'POST':
                selected_service = request.form.get('s_id', type=int)
                time_value = request.form.get('requested_time', '').strip()

                valid_ids = {s['s_id'] for s in services}
                error = None
                requested_time = None

                if selected_service not in valid_ids:
                    error = 'Please choose a valid service for this workshop.'
                else:
                    try:
                        requested_time = datetime.fromisoformat(time_value)
                    except ValueError:
                        error = 'Please enter a valid date and time.'

                if not error:
                    now = datetime.now()
                    if requested_time <= now:
                        error = 'Please choose a time in the future.'
                    elif requested_time > now + timedelta(days=365):
                        error = 'Bookings can be made up to one year ahead.'

                if not error:
                    cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session['user_id'],))
                    customer = cur.fetchone()
                    if customer is None:
                        error = 'Customer account not found.'

                if error:
                    flash(error, 'error')
                else:
                    cur.execute("""
                        INSERT INTO booking (c_id, w_id, s_id, requested_time, status)
                        VALUES (%s, %s, %s, %s, 'pending')
                        RETURNING b_id
                    """, (customer['c_id'], w_id, selected_service, requested_time))
                    b_id = cur.fetchone()['b_id']
                    conn.commit()
                    flash('Booking request sent.', 'success')
                    return redirect(url_for('bookings.confirmation', b_id=b_id))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return render_template(
        'bookings/new.html',
        workshop=workshop,
        services=services,
        preselected_service=selected_service,
        time_value=time_value,
        min_time=datetime.now().strftime('%Y-%m-%dT%H:%M'),
    )
@bookings_bp.route('/confirmation/<int:b_id>')
@role_required('customer')
def confirmation(b_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, w.address, sc.s_name
        FROM booking b
        JOIN workshop w ON b.w_id = w.w_id
        JOIN service s ON b.s_id = s.s_id
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        JOIN customer c ON b.c_id = c.c_id
        WHERE b.b_id = %s AND c.u_id = %s
    """, (b_id, session['user_id']))
    booking = cur.fetchone()
    cur.close()
    conn.close()

    return render_template('bookings/confirmation.html', booking=booking)

@bookings_bp.route('/my-bookings')
@role_required('customer')
def my_bookings():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session['user_id'],))
    customer = cur.fetchone()

    cur.execute("""
        SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, w.w_id, sc.s_name,
               mu.name AS mechanic_name
        FROM booking b
        JOIN workshop w ON b.w_id = w.w_id
        JOIN service s ON b.s_id = s.s_id
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        LEFT JOIN mechanic bm ON b.assigned_m_id = bm.m_id
        LEFT JOIN users mu ON bm.u_id = mu.u_id
        WHERE b.c_id = %s
        ORDER BY b.requested_time DESC
    """, (customer['c_id'],))
    bookings = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('bookings/my_bookings.html', bookings=bookings)

@bookings_bp.route('/cancel/<int:b_id>', methods=['POST'])
@role_required('customer')
def cancel(b_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE booking SET status = 'cancelled'
                WHERE b_id = %s
                AND status IN ('pending', 'confirmed')
                AND c_id = (SELECT c_id FROM customer WHERE u_id = %s)
            """, (b_id, session['user_id']))
            changed = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if changed:
        flash('Booking cancelled.', 'success')
    else:
        flash('Booking not found or can no longer be cancelled.', 'error')
    return redirect(url_for('bookings.my_bookings'))