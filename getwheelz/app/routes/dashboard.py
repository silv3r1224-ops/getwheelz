import logging
from flask import Blueprint, render_template, request, session, abort, flash, redirect, url_for
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db_connection
from app.utils import login_required, role_required, admin_access_required

dashboard_bp = Blueprint("dashboard", __name__)


# =================================================ADMIN DASHBOARD=================================================#
@dashboard_bp.route("/admin")
@admin_access_required()
def admin():
    conn = get_db_connection()
    cur = conn.cursor()

    # Sub-admins get a purpose-built dashboard containing only their assigned domain.
    cur.execute("SELECT admin_type FROM admin WHERE u_id = %s", (session['user_id'],))
    admin_profile = cur.fetchone()
    if not admin_profile:
        cur.close()
        conn.close()
        abort(403)

    if admin_profile['admin_type'] != 'main':
        manager_type = admin_profile['admin_type']
        records = []
        managed_workshops = []
        if manager_type == 'customer_manager':
            cur.execute("""
                SELECT c.c_id AS record_id, u.u_id, u.name, u.email, u.created_at
                FROM customer c JOIN users u ON c.u_id = u.u_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
        elif manager_type == 'owner_workshop_manager':
            cur.execute("""
                SELECT o.o_id AS record_id, u.u_id, u.name, u.email, u.created_at,
                (SELECT COUNT(*) FROM workshop w WHERE w.o_id = o.o_id) AS workshop_count
                FROM owner o JOIN users u ON o.u_id = u.u_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
            cur.execute("""
                SELECT w.w_id, w.name AS workshop_name, w.address, u.name AS owner_name, u.email AS owner_email
                FROM workshop w JOIN owner o ON w.o_id = o.o_id
                JOIN users u ON o.u_id = u.u_id
                ORDER BY w.name
            """)
            managed_workshops = cur.fetchall()
        elif manager_type == 'mechanic_manager':
            cur.execute("""
                SELECT m.m_id AS record_id, u.u_id, u.name, u.email, u.created_at,
                m.experience_yrs, m.active_stat, w.name AS workshop_name
                FROM mechanic m JOIN users u ON m.u_id = u.u_id
                LEFT JOIN workshop w ON m.w_id = w.w_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
        cur.close()
        conn.close()
        return render_template('dashboard/subadmin.html', manager_type=manager_type, records=records, managed_workshops=managed_workshops)

    # Stats
    cur.execute("SELECT COUNT(*) AS count FROM customer")
    total_customers = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM owner")
    total_owners = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM mechanic")
    total_mechanics = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM workshop")
    total_workshops = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM booking")
    total_bookings = cur.fetchone()["count"]

    # All customer records
    cur.execute("""
        SELECT c.c_id, u.name, u.email, u.created_at
        FROM customer c JOIN users u ON c.u_id = u.u_id
        ORDER BY u.created_at DESC
    """)
    customers = cur.fetchall()

    # All owner records
    cur.execute("""
        SELECT o.o_id, u.name, u.email, u.created_at
        FROM owner o JOIN users u ON o.u_id = u.u_id
        ORDER BY u.created_at DESC
    """)
    owners = cur.fetchall()

    # All mechanic records
    cur.execute("""
        SELECT m.m_id, u.name, u.email, u.created_at
        FROM mechanic m JOIN users u ON m.u_id = u.u_id
        ORDER BY u.created_at DESC
    """)
    mechanics = cur.fetchall()

    # All workshop records
    cur.execute("""
        SELECT w.w_id, w.name, w.address, u.name AS owner_name
        FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        JOIN users u ON o.u_id = u.u_id
        ORDER BY w.name
    """)
    workshops = cur.fetchall()

    # All feedback records
    cur.execute("SELECT * FROM feedback ORDER BY submitted_at DESC")
    feedback_list = cur.fetchall()

    email = request.args.get("email", "").strip()
    role = request.args.get("role", "")
    result = None
    searched = False

    if email and role in ("customer", "owner", "mechanic"):
        searched = True
        conn = get_db_connection()
        cur = conn.cursor()

        if role == "customer":
            cur.execute(
                """
                SELECT c.c_id, u.u_id, u.name, u.email, u.created_at
                    FROM customer c JOIN users u ON c.u_id = u.u_id
                    WHERE u.email = %s
                """,
                (email,),
            )
        elif role == "owner":
            cur.execute(
                """
                    SELECT o.o_id, u.u_id, u.name, u.email, u.created_at
                    FROM owner o JOIN users u ON o.u_id = u.u_id
                    WHERE u.email = %s
                """,
                (email,),
            )
        elif role == "mechanic":
            cur.execute(
                """
                    SELECT m.m_id, u.u_id, u.name, u.email, u.created_at
                    FROM mechanic m JOIN users u ON m.u_id = u.u_id
                    WHERE u.email = %s
                """,
                (email,),
            )

        result = cur.fetchone()

        cur.close()
        conn.close()

    return render_template(
        "dashboard/admin.html",
        total_customers=total_customers,
        total_owners=total_owners,
        total_mechanics=total_mechanics,
        total_workshops=total_workshops,
        total_bookings=total_bookings,
        customers=customers,
        owners=owners,
        mechanics=mechanics,
        workshops=workshops,
        feedback_list=feedback_list,
        result=result,
        role=role,
        searched_email=email,
        searched = searched
    )
#Terminate
@dashboard_bp.route('/admin/terminate/<role>/<int:u_id>', methods=['POST'])
@admin_access_required('customer_manager', 'owner_workshop_manager', 'mechanic_manager')
def admin_terminate(role, u_id):
    if role not in ('customer', 'owner', 'mechanic'):
        abort(404)

    # Managers may only remove accounts inside their assigned domain.
    manager_type = session.get('admin_type')
    allowed_roles = {
        'customer_manager': ('customer',),
        'owner_workshop_manager': ('owner',),
        'mechanic_manager': ('mechanic',),
    }
    if manager_type != 'main' and role not in allowed_roles.get(manager_type, ()):
        abort(403)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE u_id = %s", (u_id,))
            target = cur.fetchone()
            if not target or target['role'] != role:
                abort(404)
            cur.execute("DELETE FROM users WHERE u_id = %s", (u_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    flash("Account terminated.")
    return redirect(url_for('dashboard.admin'))

#feedback
@dashboard_bp.route('/admin/feedback/<int:f_id>/read', methods=['POST'])
@admin_access_required(main_only=True)
def mark_feedback_read(f_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE feedback SET is_read = TRUE WHERE f_id = %s", (f_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('dashboard.admin'))

#add service
@dashboard_bp.route('/admin/services', methods=['GET', 'POST'])
@admin_access_required(main_only=True)
def admin_services():
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        s_name = request.form['s_name'].strip()
        if s_name:
            try:
                cur.execute("INSERT INTO service_catalog (s_name) VALUES (%s)", (s_name,))
                conn.commit()
                flash(f'"{s_name}" added to the service catalog.')
            except Exception:
                conn.rollback()
                flash('That service already exists.')
        return redirect(url_for('dashboard.admin_services'))

    cur.execute("SELECT * FROM service_catalog ORDER BY s_name")
    catalog = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('dashboard/admin_service.html', catalog=catalog)

#delete service
@dashboard_bp.route('/admin/services/<int:sc_id>/delete', methods=['POST'])
@admin_access_required(main_only=True)
def delete_catalog_service(sc_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM service_catalog WHERE sc_id = %s", (sc_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Service removed from catalog.')
    return redirect(url_for('dashboard.admin_services'))

# =================================================SUB-ADMIN MANAGEMENT=================================================#
@dashboard_bp.route('/admin/subadmins', methods=['GET', 'POST'])
@admin_access_required(main_only=True)
def admin_subadmins():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if request.method == 'POST':
                name = request.form.get('name', '').strip()
                email = request.form.get('email', '').strip().lower()
                password = request.form.get('password', '')
                confirm_password = request.form.get('confirm_password', '')
                admin_type = request.form.get('admin_type', '')
                valid_types = ('customer_manager', 'owner_workshop_manager', 'mechanic_manager')

                if not name or not email or len(password) < 8:
                    flash('Enter a name, email, and password of at least 8 characters.')
                elif password != confirm_password:
                    flash('Passwords do not match.')
                elif admin_type not in valid_types:
                    flash('Choose a valid sub-admin type.')
                else:
                    try:
                        cur.execute(
                            "INSERT INTO users (name, email, password, role, created_at) VALUES (%s, %s, %s, 'admin', NOW()) RETURNING u_id",
                            (name, email, generate_password_hash(password))
                        )
                        new_uid = cur.fetchone()['u_id']
                        cur.execute(
                            "INSERT INTO admin (u_id, admin_type, is_active) VALUES (%s, %s, TRUE)",
                            (new_uid, admin_type)
                        )
                        conn.commit()
                        flash('Sub-admin created successfully.')
                        return redirect(url_for('dashboard.admin_subadmins'))
                    except Exception:
                        conn.rollback()
                        logging.exception('Could not create sub-admin')
                        flash('Could not create account. Check whether the email is already registered.')

            cur.execute("""
                SELECT a.a_id, a.u_id, a.admin_type, a.is_active,
                u.name, u.email, u.created_at
                FROM admin a JOIN users u ON a.u_id = u.u_id
                ORDER BY (a.admin_type = 'main') DESC, u.created_at DESC
            """)
            subadmins = cur.fetchall()
    finally:
        conn.close()
    return render_template('dashboard/subadmins.html', subadmins=subadmins)


@dashboard_bp.route('/admin/subadmins/<int:a_id>/toggle', methods=['POST'])
@admin_access_required(main_only=True)
def toggle_subadmin(a_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT u_id, admin_type, is_active FROM admin WHERE a_id = %s", (a_id,))
            target = cur.fetchone()
            if not target:
                abort(404)
            if target['admin_type'] == 'main' or target['u_id'] == session['user_id']:
                flash('The main admin account cannot be deactivated here.')
            else:
                cur.execute("UPDATE admin SET is_active = NOT is_active WHERE a_id = %s", (a_id,))
                conn.commit()
                flash('Sub-admin status updated.')
    finally:
        conn.close()
    return redirect(url_for('dashboard.admin_subadmins'))


# =================================================OWNER DASHBOARD=================================================#
@dashboard_bp.route('/owner')
@role_required('owner')
def owner():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session['user_id'],))
    owner_row = cur.fetchone()
    if not owner_row:
        cur.close()
        conn.close()
        abort(403)

    cur.execute("SELECT w_id, name, address, contact_no, photo_path, capacity FROM workshop WHERE o_id = %s",
            (owner_row['o_id'],))
    workshop = cur.fetchone()

    bookings = []
    services = []
    mechanics = []
    pending_requests = []
    leave_requests = []
    stats = {'total_bookings': 0, 'pending_bookings': 0, 'total_services': 0, 'total_mechanics': 0, 'capacity': 0}
    service_catalog = []

    cur.execute("SELECT sc_id, s_name FROM service_catalog ORDER BY s_name")
    service_catalog = cur.fetchall()

    if workshop:
        cur.execute("""
            SELECT b.b_id, b.requested_time, b.status, u.name AS customer_name, sc.s_name
            FROM booking b
            JOIN customer c ON b.c_id = c.c_id
            JOIN users u ON c.u_id = u.u_id
            JOIN service s ON b.s_id = s.s_id
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE b.w_id = %s
            ORDER BY b.requested_time DESC
        """, (workshop['w_id'],))
        bookings = cur.fetchall()

        cur.execute("""
            SELECT s.s_id, sc.s_name, s.price_range, s.duration,
            (SELECT COUNT(*) FROM booking b WHERE b.s_id = s.s_id) AS booking_count
            FROM service s
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE s.w_id = %s
            ORDER BY sc.s_name
        """, (workshop['w_id'],))
        services = cur.fetchall()

        cur.execute("""
            SELECT m.m_id, u.name, u.email, m.experience_yrs, m.active_stat,
            (m.leave_requested_at IS NOT NULL) AS leave_pending
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = %s
        """, (workshop['w_id'],))
        mechanics = cur.fetchall()

        cur.execute("""
            SELECT m.m_id AS lr_id, u.name, u.email, m.experience_yrs,
            m.leave_reason AS reason, m.leave_requested_at AS created_at
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = %s AND m.leave_requested_at IS NOT NULL
            ORDER BY m.leave_requested_at
        """, (workshop['w_id'],))
        leave_requests = cur.fetchall()

        cur.execute("""
            SELECT jr.jr_id, m.m_id, u.name, u.email, m.experience_yrs
            FROM join_request jr
            JOIN mechanic m ON jr.m_id = m.m_id
            JOIN users u ON m.u_id = u.u_id
            WHERE jr.w_id = %s AND jr.status = 'pending' AND m.w_id IS NULL
            ORDER BY jr.created_at
            """, (workshop['w_id'],))
        pending_requests = cur.fetchall()

        stats['total_bookings'] = len(bookings)
        stats['pending_bookings'] = len([b for b in bookings if b['status'] == 'pending'])
        stats['total_services'] = len(services)
        stats['total_mechanics'] = len(mechanics)
        stats['capacity'] = workshop['capacity']

    cur.close()
    conn.close()

    return render_template('dashboard/owner.html',
        workshop=workshop,
        bookings=bookings,
        services=services,
        mechanics=mechanics,
        stats=stats,
        service_catalog=service_catalog,
        pending_requests=pending_requests,
        leave_requests=leave_requests
    )

@dashboard_bp.route('/owner/service/<int:s_id>/remove', methods=['POST'])
@role_required('owner')
def remove_service(s_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # the service must belong to THIS owner's workshop
    cur.execute("""
        SELECT s.s_id FROM service s
        JOIN workshop w ON s.w_id = w.w_id
        JOIN owner o ON w.o_id = o.o_id
        WHERE s.s_id = %s AND o.u_id = %s
    """, (s_id, session['user_id']))

    if not cur.fetchone():
        flash('Service not found.')
    else:
        # never delete a service that customers have booked: it would wipe their booking history
        cur.execute("SELECT 1 FROM booking WHERE s_id = %s LIMIT 1", (s_id,))
        if cur.fetchone():
            flash("This service has bookings, so it can't be removed.")
        else:
            try:
                cur.execute("DELETE FROM service WHERE s_id = %s", (s_id,))
                conn.commit()
                flash('Service removed.')
            except Exception:
                conn.rollback()
                flash('Could not remove this service.')

    cur.close()
    conn.close()
    return redirect(url_for('dashboard.owner'))


@dashboard_bp.route('/owner/leave/<int:lr_id>/<action>', methods=['POST'])
@role_required('owner')
def review_leave(lr_id, action):
    if action not in ('approve', 'reject'):
        abort(400)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT w.w_id FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """, (session['user_id'],))
    ws = cur.fetchone()
    if not ws:
        cur.close()
        conn.close()
        abort(403)

    # the mechanic must work in THIS owner's workshop and have a pending request
    cur.execute("""
        SELECT m_id FROM mechanic
        WHERE m_id = %s AND w_id = %s AND leave_requested_at IS NOT NULL
    """, (lr_id, ws['w_id']))
    req = cur.fetchone()

    if not req:
        flash('Leave request not found.')
    elif action == 'reject':
        cur.execute("""
            UPDATE mechanic
            SET leave_requested_at = NULL, leave_reason = NULL, leave_rejected_at = NOW()
            WHERE m_id = %s
        """, (lr_id,))
        conn.commit()
        flash('Leave request declined. The mechanic stays in your workshop.')
    else:
        cur.execute("""
            UPDATE mechanic
            SET w_id = NULL, leave_requested_at = NULL, leave_reason = NULL, leave_rejected_at = NULL
            WHERE m_id = %s
        """, (lr_id,))
        conn.commit()
        flash('Leave approved. The mechanic has been released from your workshop.')

    cur.close()
    conn.close()
    return redirect(url_for('dashboard.owner'))


@dashboard_bp.route('/owner/request/<int:jr_id>/<action>', methods=['POST'])
@role_required('owner')
def review_mechanic(jr_id, action):
    if action not in ('accept', 'reject'):
        abort(400)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT w.w_id, w.capacity FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """, (session['user_id'],))
    ws = cur.fetchone()
    if not ws:
        cur.close()
        conn.close()
        abort(403)

    # request must belong to THIS owner's workshop and still be pending
    cur.execute("""
        SELECT m_id FROM join_request
        WHERE jr_id = %s AND w_id = %s AND status = 'pending'
    """, (jr_id, ws['w_id']))
    req = cur.fetchone()

    if not req:
        flash('Request not found.')
    elif action == 'reject':
        cur.execute("UPDATE join_request SET status = 'rejected' WHERE jr_id = %s", (jr_id,))
        conn.commit()
        flash('Request rejected.')
    else:  # action == 'accept'
        cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (ws['w_id'],))
        current = cur.fetchone()['n']

        if current >= ws['capacity']:
            flash('Your workshop is full. Increase capacity to accept more mechanics.')
        else:
            cur.execute("UPDATE mechanic SET w_id = %s WHERE m_id = %s AND w_id IS NULL",
                        (ws['w_id'], req['m_id']))
            if cur.rowcount:
                cur.execute("UPDATE join_request SET status = 'accepted' WHERE jr_id = %s", (jr_id,))
                cur.execute("""
                    UPDATE join_request SET status = 'rejected'
                    WHERE m_id = %s AND status = 'pending'
                """, (req['m_id'],))
                flash('Mechanic added to your workshop.')
            else:
                cur.execute("UPDATE join_request SET status = 'rejected' WHERE jr_id = %s", (jr_id,))
                flash('That mechanic already joined another workshop.')
            conn.commit()

    cur.close()
    conn.close()
    return redirect(url_for('dashboard.owner'))


@dashboard_bp.route('/owner/booking/<int:booking_id>/<action>', methods=['POST'])
@role_required('owner')
def update_booking_status(booking_id, action):
    transitions = {
        'confirm':  ('confirmed', ('pending',)),
        'cancel':   ('cancelled', ('pending', 'confirmed')),
        'complete': ('completed', ('confirmed',)),
    }
    if action not in transitions:
        abort(400)
    new_status, allowed_from = transitions[action]

    conn = get_db_connection()
    cur = conn.cursor()
    # only bookings that belong to THIS owner's workshop, and only valid transitions
    cur.execute("""
        UPDATE booking SET status = %s
        WHERE b_id = %s AND status = ANY(%s)
        AND w_id = (SELECT w.w_id FROM workshop w
        JOIN owner o ON w.o_id = o.o_id WHERE o.u_id = %s)
    """, (new_status, booking_id, list(allowed_from), session['user_id']))
    changed = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    flash(f'Booking {new_status}.' if changed else 'Booking not found or cannot be changed.')
    return redirect(url_for('dashboard.owner'))

#add service for owner
@dashboard_bp.route('/owner/add-service', methods=['POST'])
@role_required('owner')
def add_service():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session['user_id'],))
    owner_row = cur.fetchone()
    cur.execute("SELECT w_id FROM workshop WHERE o_id = %s", (owner_row['o_id'],))
    workshop = cur.fetchone()

    if not workshop:
        cur.close()
        conn.close()
        return redirect(url_for('dashboard.owner'))

    sc_id = request.form['sc_id']
    price_range = request.form.get('price_range')
    duration = request.form.get('duration')

    try:
        cur.execute(
            "INSERT INTO service (w_id, sc_id, price_range, duration) VALUES (%s, %s, %s, %s)",
            (workshop['w_id'], sc_id, price_range, duration)
        )
        conn.commit()
        flash('Service added.')
    except Exception:
        conn.rollback()
        flash('You already offer this service.')

    cur.close()
    conn.close()
    return redirect(url_for('dashboard.owner'))

#create workshop for owner
@dashboard_bp.route('/owner/create-workshop', methods=['POST'])
@role_required('owner')
def create_workshop():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session['user_id'],))
    owner_row = cur.fetchone()

    cur.execute("SELECT w_id FROM workshop WHERE o_id = %s", (owner_row['o_id'],))
    if cur.fetchone():
        cur.close()
        conn.close()
        return redirect(url_for('dashboard.owner'))

    name = request.form['name']
    address = request.form['address']
    contact_no = request.form.get('contact_no')
    latitude = request.form.get('latitude') or None
    longitude = request.form.get('longitude') or None

    cur.execute(
        "INSERT INTO workshop (o_id, name, address, contact_no, latitude, longitude) VALUES (%s, %s, %s, %s, %s, %s)",
        (owner_row['o_id'], name, address, contact_no, latitude, longitude)
    )
    conn.commit()
    cur.close()
    conn.close()

    flash('Workshop created!')
    return redirect(url_for('dashboard.owner'))

#upload workshop photo for owner
@dashboard_bp.route('/owner/upload-photo', methods=['POST'])
@role_required('owner')
def upload_workshop_photo():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session['user_id'],))
    owner_row = cur.fetchone()
    cur.execute("SELECT w_id FROM workshop WHERE o_id = %s", (owner_row['o_id'],))
    workshop = cur.fetchone()

    if not workshop:
        cur.close()
        conn.close()
        flash('Create your workshop first.')
        return redirect(url_for('dashboard.owner'))

    photo = request.files.get('photo')
    if photo and photo.filename and allowed_file(photo.filename):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = secure_filename(f"workshop_{workshop['w_id']}_{photo.filename}")
        photo.save(os.path.join(UPLOAD_FOLDER, filename))
        photo_path = f"uploads/workshops/{filename}"

        cur.execute("UPDATE workshop SET photo_path = %s WHERE w_id = %s", (photo_path, workshop['w_id']))
        conn.commit()
        flash('Workshop photo updated.')
    else:
        flash('Please upload a valid image (png, jpg, jpeg, webp).')

    cur.close()
    conn.close()
    return redirect(url_for('dashboard.owner'))

@dashboard_bp.route('/owner/delete-workshop', methods=['POST'])
@role_required('owner')
def delete_workshop():
    """Delete the current owner's workshop after cleaning up dependent records."""
    conn = get_db_connection()
    cur = conn.cursor()
    photo_path = None

    try:
        # Only ever select a workshop owned by the signed-in user.
        cur.execute("""
            SELECT w.w_id, w.name, w.photo_path
            FROM workshop w
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            FOR UPDATE OF w
        """, (session['user_id'],))
        workshop = cur.fetchone()

        if not workshop:
            flash('You do not have a workshop to delete.')
        else:
            workshop_id = workshop['w_id']
            photo_path = workshop['photo_path']

            # Remove requests first in case their foreign key does not cascade.
            cur.execute("DELETE FROM join_request WHERE w_id = %s", (workshop_id,))

            # Keep mechanic accounts; simply make them available to apply elsewhere.
            cur.execute("""
                UPDATE mechanic
                SET w_id = NULL,
                    leave_requested_at = NULL,
                    leave_reason = NULL
                WHERE w_id = %s
            """, (workshop_id,))

            # The workshop foreign keys in the project schema cascade to bookings
            # and service records when the workshop is removed.
            cur.execute("DELETE FROM workshop WHERE w_id = %s", (workshop_id,))
            conn.commit()
            flash('Workshop deleted. Its mechanics are now unassigned.')
    except Exception:
        conn.rollback()
        logging.exception('Failed to delete workshop for user_id=%s', session.get('user_id'))
        flash('Could not delete the workshop. No changes were saved.')
        photo_path = None
    finally:
        cur.close()
        conn.close()

    # Remove only the image file from the workshop upload directory, after commit.
    if photo_path:
        try:
            filename = os.path.basename(photo_path)
            image_file = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(image_file):
                os.remove(image_file)
        except OSError:
            logging.exception('Workshop deleted, but its image file could not be removed.')

    return redirect(url_for('dashboard.owner'))

@dashboard_bp.route('/owner/capacity', methods=['POST'])
@role_required('owner')
def update_capacity():
    try:
        capacity = int(request.form.get('capacity', ''))
    except ValueError:
        flash('Capacity must be a number.')
        return redirect(url_for('dashboard.owner'))

    if capacity < 1 or capacity > 100:
        flash('Capacity must be between 1 and 100.')
        return redirect(url_for('dashboard.owner'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT w.w_id FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """, (session['user_id'],))
    ws = cur.fetchone()
    if not ws:
        cur.close()
        conn.close()
        abort(403)

    # can't set capacity below the number of mechanics already working here
    cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (ws['w_id'],))
    current = cur.fetchone()['n']

    if capacity < current:
        flash(f'You already have {current} mechanics, so capacity can\'t be lower than that.')
    else:
        cur.execute("UPDATE workshop SET capacity = %s WHERE w_id = %s", (capacity, ws['w_id']))
        conn.commit()
        flash('Capacity updated.')

    cur.close()
    conn.close()
    return redirect(url_for('dashboard.owner'))

#=============================================================PROFILE========================================================#
@dashboard_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT u_id, name, email, role, created_at, profile_picture
        FROM users WHERE u_id = %s
        """, (session['user_id'],))
    user = cur.fetchone()

    role_info = {}
    if user['role'] == 'customer':
        cur.execute("SELECT phone_no FROM customer WHERE u_id = %s", (session['user_id'],))
        role_info = cur.fetchone()
    elif user['role'] == 'mechanic':
        cur.execute("""
            SELECT m.experience_yrs, w.name AS workshop_name
            FROM mechanic m LEFT JOIN workshop w ON m.w_id = w.w_id
            WHERE m.u_id = %s
        """, (session['user_id'],))
        role_info = cur.fetchone()
    elif user['role'] == 'owner':
        cur.execute("SELECT name FROM workshop WHERE o_id = (SELECT o_id FROM owner WHERE u_id = %s)", (session['user_id'],))
        role_info = cur.fetchone()

    if request.method == 'POST':
        name = request.form['name']
        cur.execute("UPDATE users SET name = %s WHERE u_id = %s", (name, session['user_id']))

        if user['role'] == 'customer':
            phone_number = request.form.get('phone_no')
            cur.execute("UPDATE customer SET phone_no = %s WHERE u_id = %s", (phone_number, session['user_id']))

        conn.commit()
        session['user_name'] = name
        flash('Profile updated.')
        cur.close()
        conn.close()
        return redirect(url_for('dashboard.profile'))

    cur.close()
    conn.close()

    return render_template('dashboard/profile.html', user=user, role_info=role_info)

@dashboard_bp.route('/profile/change-password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('old_pass', '')
    new_password = request.form.get('new_pass', '')
    confirm_password = request.form.get('confirm_pass', '')

    # Basic validation
    if not current_password or not new_password or not confirm_password:
        flash('Please fill in all password fields.')
        return redirect(url_for('dashboard.profile'))

    if new_password != confirm_password:
        flash('New passwords do not match.')
        return redirect(url_for('dashboard.profile'))

    if len(new_password) < 8:
        flash('New password must be at least 8 characters long.')
        return redirect(url_for('dashboard.profile'))

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Get the current password hash
        cur.execute(
            "SELECT password FROM users WHERE u_id = %s",
            (session['user_id'],)
        )
        user = cur.fetchone()

        if not user:
            flash('User account not found.')
            return redirect(url_for('dashboard.profile'))

        # Check current password
        if not check_password_hash(user['password'], current_password):
            flash('Current password is incorrect.')
            return redirect(url_for('dashboard.profile'))

        # Prevent using the same password
        if check_password_hash(user['password'], new_password):
            flash('New password must be different from your current password.')
            return redirect(url_for('dashboard.profile'))

        # Hash the new password using the same method as signup
        new_password_hash = generate_password_hash(new_password)

        cur.execute(
            "UPDATE users SET password = %s WHERE u_id = %s",
            (new_password_hash, session['user_id'])
        )

        conn.commit()

        flash('Password changed successfully.')

    except Exception:
        conn.rollback()
        logging.exception("Error changing password")
        flash('Something went wrong while changing your password.')

    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard.profile'))

# upload profile picture
@dashboard_bp.route('/profile/upload-picture', methods=['POST'])
@login_required
def upload_profile_picture():
    conn = get_db_connection()
    cur = conn.cursor()

    photo = request.files.get('photo')

    if photo and photo.filename and allowed_file(photo.filename):
        profile_upload_folder = os.path.join('app', 'static', 'uploads', 'profiles')
        os.makedirs(profile_upload_folder, exist_ok=True)

        filename = secure_filename(
            f"profile_{session['user_id']}_{photo.filename}"
        )

        photo.save(os.path.join(profile_upload_folder, filename))

        profile_picture_path = f"uploads/profiles/{filename}"

        cur.execute(
            "UPDATE users SET profile_picture = %s WHERE u_id = %s",
            (profile_picture_path, session['user_id'])
        )

        conn.commit()
        flash('Profile picture updated.')
    else:
        flash('Please upload a valid image (png, jpg, jpeg, webp).')

    cur.close()
    conn.close()

    return redirect(url_for('dashboard.profile'))

# remove profile picture
@dashboard_bp.route('/profile/remove-picture', methods=['POST'])
@login_required
def remove_profile_picture():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT profile_picture FROM users WHERE u_id = %s",
        (session['user_id'],)
    )
    user = cur.fetchone()

    if user and user['profile_picture']:
        # Build the actual file path
        file_path = os.path.join(
            'app',
            'static',
            user['profile_picture']
        )

        # Delete the physical image if it exists
        if os.path.exists(file_path):
            os.remove(file_path)

        # Remove the path from database
        cur.execute(
            "UPDATE users SET profile_picture = NULL WHERE u_id = %s",
            (session['user_id'],)
        )

        conn.commit()
        flash('Profile picture removed.')

    cur.close()
    conn.close()

    return redirect(url_for('dashboard.profile'))

UPLOAD_FOLDER = os.path.join('app', 'static', 'uploads', 'workshops')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS