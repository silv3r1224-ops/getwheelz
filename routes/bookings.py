from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.db import get_db_connection
from app.utils import role_required

bookings_bp = Blueprint('bookings', __name__)

@bookings_bp.route('/new/<int:w_id>', methods=['GET', 'POST'])
@role_required('customer')
def new(w_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT w_id, name, address FROM workshop WHERE w_id = %s", (w_id,))
    workshop = cur.fetchone()

    cur.execute("SELECT s.s_id, sc.s_name, s.price_range, s.duration FROM service s JOIN service_catalog sc ON sc.sc_id = s.sc_id WHERE s.w_id = %s", (w_id,))
    services = cur.fetchall()

    if request.method == 'POST':
        s_id = request.form['s_id']
        requested_time = request.form['requested_time']

        cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session['user_id'],))
        customer = cur.fetchone()

        cur.execute("""
            INSERT INTO booking (c_id, w_id, s_id, requested_time, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING b_id
        """, (customer['c_id'], w_id, s_id, requested_time))
        b_id = cur.fetchone()['b_id']
        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('bookings.confirmation', b_id=b_id))

    cur.close()
    conn.close()

    preselected_service = request.args.get('s_id', type=int)
    return render_template('bookings/new.html', workshop=workshop, services=services, preselected_service=preselected_service)

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
        SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, w.w_id, sc.s_name
        FROM booking b
        JOIN workshop w ON b.w_id = w.w_id
        JOIN service s ON b.s_id = s.s_id
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
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
    cur = conn.cursor()
    cur.execute("UPDATE booking SET status = 'cancelled' WHERE b_id = %s", (b_id,))
    conn.commit()
    cur.close()
    conn.close()

    flash('Booking cancelled.')
    return redirect(url_for('bookings.my_bookings'))