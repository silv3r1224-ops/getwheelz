import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, session, abort, flash, redirect, url_for
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db_connection
from app.utils import login_required, role_required, admin_access_required, decode_uid, decode_wid

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
                SELECT c.c_id AS record_id, u.u_id, u.name, u.email, u.created_at, u.profile_picture,
                       c.phone_no,
                       (SELECT COUNT(*) FROM booking b WHERE b.c_id = c.c_id) AS booking_count
                FROM customer c JOIN users u ON c.u_id = u.u_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
        elif manager_type == 'owner_workshop_manager':
            cur.execute("""
                SELECT o.o_id AS record_id, u.u_id, u.name, u.email, u.created_at, u.profile_picture,
                (SELECT COUNT(*) FROM workshop w WHERE w.o_id = o.o_id) AS workshop_count
                FROM owner o JOIN users u ON o.u_id = u.u_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
            cur.execute("""
                SELECT w.w_id, w.name AS workshop_name, w.address, u.name AS owner_name, u.email AS owner_email,
                       (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size, w.capacity
                FROM workshop w JOIN owner o ON w.o_id = o.o_id
                JOIN users u ON o.u_id = u.u_id
                ORDER BY w.name
            """)
            managed_workshops = cur.fetchall()
        elif manager_type == 'mechanic_manager':
            cur.execute("""
                SELECT m.m_id AS record_id, u.u_id, u.name, u.email, u.created_at, u.profile_picture,
                m.experience_yrs, m.active_stat, w.name AS workshop_name
                FROM mechanic m JOIN users u ON m.u_id = u.u_id
                LEFT JOIN workshop w ON m.w_id = w.w_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
        cur.close()
        conn.close()

        # numbers for the summary cards
        cutoff = datetime.now() - timedelta(days=30)
        stats = {
            'total': len(records),
            'new_30d': sum(1 for r in records if r['created_at'] and r['created_at'] >= cutoff),
        }
        if manager_type == 'owner_workshop_manager':
            stats['workshops'] = len(managed_workshops)
            stats['no_workshop'] = sum(1 for r in records if r['workshop_count'] == 0)
        elif manager_type == 'mechanic_manager':
            stats['assigned'] = sum(1 for r in records if r['workshop_name'])
            stats['unassigned'] = len(records) - stats['assigned']
        elif manager_type == 'customer_manager':
            stats['with_bookings'] = sum(1 for r in records if r['booking_count'] > 0)

        return render_template('dashboard/subadmin.html', manager_type=manager_type, records=records,
                               managed_workshops=managed_workshops, stats=stats)

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
        SELECT c.c_id, u.u_id, u.name, u.email, u.created_at
        FROM customer c JOIN users u ON c.u_id = u.u_id
        ORDER BY u.created_at DESC
    """)
    customers = cur.fetchall()

    # All owner records
    cur.execute("""
        SELECT o.o_id, u.u_id, u.name, u.email, u.created_at
        FROM owner o JOIN users u ON o.u_id = u.u_id
        ORDER BY u.created_at DESC
    """)
    owners = cur.fetchall()

    # All mechanic records
    cur.execute("""
        SELECT m.m_id, u.u_id, u.name, u.email, u.created_at
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

    email = request.args.get("email", "").strip().lower()
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
# =================================================ADMIN: VIEW A USER'S PROFILE=================================================#
@dashboard_bp.route('/admin/profile/<token>')
@admin_access_required()
def admin_user_profile(token):
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u_id, name, email, role, profile_picture, created_at
                FROM users
                WHERE u_id = %s AND role IN ('customer', 'owner', 'mechanic')
            """, (u_id,))
            person = cur.fetchone()
            if not person:
                abort(404)

            # Sub-admins may only view accounts inside their own domain.
            manager_type = session.get('admin_type')
            allowed_roles = {
                'customer_manager': 'customer',
                'owner_workshop_manager': 'owner',
                'mechanic_manager': 'mechanic',
            }
            if manager_type != 'main' and allowed_roles.get(manager_type) != person['role']:
                abort(403)

            details, workshops, bookings, jobs = None, [], [], 0

            if person['role'] == 'customer':
                cur.execute("""
                    SELECT c.c_id, c.phone_no FROM customer c WHERE c.u_id = %s
                """, (u_id,))
                details = cur.fetchone()
                if details:
                    cur.execute("""
                        SELECT b.b_id, b.requested_time, b.status,
                               w.name AS workshop_name, sc.s_name
                        FROM booking b
                        JOIN workshop w ON b.w_id = w.w_id
                        JOIN service s ON b.s_id = s.s_id
                        JOIN service_catalog sc ON sc.sc_id = s.sc_id
                        WHERE b.c_id = %s
                        ORDER BY b.requested_time DESC
                        LIMIT 15
                    """, (details['c_id'],))
                    bookings = cur.fetchall()
                    cur.execute("""
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                               COUNT(*) FILTER (WHERE status = 'completed') AS completed
                        FROM booking WHERE c_id = %s
                    """, (details['c_id'],))
                    jobs = cur.fetchone()

            elif person['role'] == 'owner':
                cur.execute("""
                    SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path, w.capacity,
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

            else:  # mechanic (may not have joined a workshop yet)
                cur.execute("""
                    SELECT m.experience_yrs, m.active_stat, w.w_id, w.name AS workshop_name,
                           w.address, w.photo_path
                    FROM mechanic m LEFT JOIN workshop w ON m.w_id = w.w_id
                    WHERE m.u_id = %s
                """, (u_id,))
                details = cur.fetchone()
    finally:
        conn.close()

    return render_template('dashboard/admin_user_profile.html',
                           person=person, details=details, workshops=workshops,
                           bookings=bookings, jobs=jobs)

# =================================================ADMIN: VIEW A WORKSHOP=================================================#
@dashboard_bp.route('/admin/workshop/<token>')
@admin_access_required()
def admin_workshop_preview(token):
    w_id = decode_wid(token)
    if w_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path,
                       w.latitude, w.longitude, w.capacity,
                       u.name AS owner_name, u.u_id AS owner_uid,
                       u.email AS owner_email, u.profile_picture AS owner_picture,
                       u.created_at AS owner_since
                FROM workshop w
                JOIN owner o ON w.o_id = o.o_id
                JOIN users u ON o.u_id = u.u_id
                WHERE w.w_id = %s
            """, (w_id,))
            workshop = cur.fetchone()
            if not workshop:
                abort(404)

            cur.execute("""
                SELECT sc.s_name, s.price_range, s.duration
                FROM service s
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE s.w_id = %s
                ORDER BY sc.s_name
            """, (w_id,))
            services = cur.fetchall()

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
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                       COUNT(*) FILTER (WHERE status = 'completed') AS completed
                FROM booking WHERE w_id = %s
            """, (w_id,))
            jobs = cur.fetchone()
    finally:
        conn.close()

    # which profiles this admin is allowed to open from the workshop page
    admin_type = session.get('admin_type')
    can_view_owner = admin_type in ('main', 'owner_workshop_manager')
    can_view_mechanics = admin_type in ('main', 'mechanic_manager')

    return render_template('dashboard/admin_workshop_preview.html',
                           workshop=workshop, services=services, team=team, jobs=jobs,
                           open_slots=workshop['capacity'] - len(team),
                           can_view_owner=can_view_owner,
                           can_view_mechanics=can_view_mechanics)

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

    flash("Account terminated.", 'success')
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

# =================================================SERVICE CATALOG=================================================#
def _clean_service_name(raw):
    """Collapse extra spaces so ' Brake   Repair ' becomes 'Brake Repair'."""
    return ' '.join((raw or '').split())


@dashboard_bp.route('/admin/services', methods=['GET', 'POST'])
@admin_access_required(main_only=True)
def admin_services():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if request.method == 'POST':
                s_name = _clean_service_name(request.form.get('s_name'))
                if not s_name:
                    flash('Please enter a service name.', 'error')
                elif len(s_name) > 100:
                    flash('Service names can be at most 100 characters.', 'error')
                else:
                    # the UNIQUE constraint is case-sensitive, so check "tires" vs "Tires" ourselves
                    cur.execute("SELECT 1 FROM service_catalog WHERE LOWER(s_name) = LOWER(%s)", (s_name,))
                    if cur.fetchone():
                        flash('That service already exists.', 'error')
                    else:
                        try:
                            cur.execute("INSERT INTO service_catalog (s_name) VALUES (%s)", (s_name,))
                            conn.commit()
                            flash(f'"{s_name}" added to the service catalog.', 'success')
                        except Exception:
                            conn.rollback()
                            logging.exception('Could not add catalog service')
                            flash('Could not add that service.', 'error')
                return redirect(url_for('dashboard.admin_services'))

            cur.execute("""
                SELECT sc.sc_id, sc.s_name,
                       COUNT(DISTINCT s.s_id) AS workshop_count,
                       COUNT(b.b_id)          AS booking_count
                FROM service_catalog sc
                LEFT JOIN service s ON s.sc_id = sc.sc_id
                LEFT JOIN booking b ON b.s_id = s.s_id
                GROUP BY sc.sc_id, sc.s_name
                ORDER BY sc.s_name
            """)
            catalog = cur.fetchall()
    finally:
        conn.close()

    in_use = sum(1 for c in catalog if c['workshop_count'] > 0)
    stats = {'total': len(catalog), 'in_use': in_use, 'unused': len(catalog) - in_use}
    return render_template('dashboard/admin_service.html', catalog=catalog, stats=stats)


@dashboard_bp.route('/admin/services/<int:sc_id>/rename', methods=['POST'])
@admin_access_required(main_only=True)
def rename_catalog_service(sc_id):
    new_name = _clean_service_name(request.form.get('s_name'))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT s_name FROM service_catalog WHERE sc_id = %s", (sc_id,))
            row = cur.fetchone()
            if not row:
                abort(404)

            if not new_name:
                flash('Please enter a service name.', 'error')
            elif len(new_name) > 100:
                flash('Service names can be at most 100 characters.', 'error')
            elif new_name == row['s_name']:
                pass  # nothing changed
            else:
                cur.execute(
                    "SELECT 1 FROM service_catalog WHERE LOWER(s_name) = LOWER(%s) AND sc_id <> %s",
                    (new_name, sc_id))
                if cur.fetchone():
                    flash('Another service already has that name.', 'error')
                else:
                    try:
                        cur.execute("UPDATE service_catalog SET s_name = %s WHERE sc_id = %s", (new_name, sc_id))
                        conn.commit()
                        flash(f'Renamed to "{new_name}".', 'success')
                    except Exception:
                        conn.rollback()
                        logging.exception('Could not rename catalog service')
                        flash('Could not rename that service.', 'error')
    finally:
        conn.close()
    return redirect(url_for('dashboard.admin_services'))


@dashboard_bp.route('/admin/services/<int:sc_id>/delete', methods=['POST'])
@admin_access_required(main_only=True)
def delete_catalog_service(sc_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s_name,
                       (SELECT COUNT(*) FROM service WHERE sc_id = %s) AS in_use
                FROM service_catalog WHERE sc_id = %s
            """, (sc_id, sc_id))
            row = cur.fetchone()
            if not row:
                flash('That service no longer exists.', 'error')
            elif row['in_use']:
                n = row['in_use']
                flash(f'"{row["s_name"]}" is offered by {n} workshop{"" if n == 1 else "s"}, so it can\'t be removed.', 'error')
            else:
                try:
                    cur.execute("DELETE FROM service_catalog WHERE sc_id = %s", (sc_id,))
                    conn.commit()
                    flash(f'"{row["s_name"]}" removed from the catalog.', 'success')
                except Exception:
                    conn.rollback()
                    logging.exception('Could not delete catalog service')
                    flash('Could not remove that service.', 'error')
    finally:
        conn.close()
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
                    flash('Enter a name, email, and password of at least 8 characters.', 'error')
                elif password != confirm_password:
                    flash('Passwords do not match.', 'error')
                elif admin_type not in valid_types:
                    flash('Choose a valid sub-admin type.', 'error')
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
                        flash('Sub-admin created successfully.', 'success')
                        return redirect(url_for('dashboard.admin_subadmins'))
                    except Exception:
                        conn.rollback()
                        logging.exception('Could not create sub-admin')
                        flash('Could not create account. Check whether the email is already registered.', 'error')

            cur.execute("""
                SELECT a.a_id, a.u_id, a.admin_type, a.is_active,
                u.name, u.email, u.created_at, u.profile_picture
                FROM admin a JOIN users u ON a.u_id = u.u_id
                ORDER BY (a.admin_type = 'main') DESC, u.created_at DESC
            """)
            subadmins = cur.fetchall()
    finally:
        conn.close()
    return render_template('dashboard/subadmins.html', subadmins=subadmins)


@dashboard_bp.route('/admin/subadmins/profile/<token>')
@admin_access_required(main_only=True)
def admin_team_profile(token):
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.a_id, a.admin_type, a.is_active,
                       u.u_id, u.name, u.email, u.profile_picture, u.created_at
                FROM admin a JOIN users u ON a.u_id = u.u_id
                WHERE u.u_id = %s
            """, (u_id,))
            member = cur.fetchone()
            if not member:
                abort(404)

            # size of the area this admin looks after
            cur.execute("""
                SELECT (SELECT COUNT(*) FROM customer) AS customers,
                       (SELECT COUNT(*) FROM owner)    AS owners,
                       (SELECT COUNT(*) FROM mechanic) AS mechanics,
                       (SELECT COUNT(*) FROM workshop) AS workshops
            """)
            scope = cur.fetchone()
    finally:
        conn.close()

    return render_template('dashboard/admin_team_profile.html', member=member, scope=scope)


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
                flash('The main admin account cannot be deactivated here.', 'error')
            else:
                cur.execute("UPDATE admin SET is_active = NOT is_active WHERE a_id = %s", (a_id,))
                conn.commit()
                flash('Sub-admin status updated.', 'success')
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
        flash('Service not found.', 'error')
    else:
        # never delete a service that customers have booked: it would wipe their booking history
        cur.execute("SELECT 1 FROM booking WHERE s_id = %s LIMIT 1", (s_id,))
        if cur.fetchone():
            flash("This service has bookings, so it can't be removed.", 'error')
        else:
            try:
                cur.execute("DELETE FROM service WHERE s_id = %s", (s_id,))
                conn.commit()
                flash('Service removed.', 'success')
            except Exception:
                conn.rollback()
                flash('Could not remove this service.', 'error')

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
        flash('Leave request not found.', 'error')
    elif action == 'reject':
        cur.execute("""
            UPDATE mechanic
            SET leave_requested_at = NULL, leave_reason = NULL, leave_rejected_at = NOW()
            WHERE m_id = %s
        """, (lr_id,))
        conn.commit()
        flash('Leave request declined. The mechanic stays in your workshop.', 'success')
    else:
        cur.execute("""
            UPDATE mechanic
            SET w_id = NULL, leave_requested_at = NULL, leave_reason = NULL, leave_rejected_at = NULL
            WHERE m_id = %s
        """, (lr_id,))
        conn.commit()
        flash('Leave approved. The mechanic has been released from your workshop.', 'success')

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
        flash('Request not found.', 'error')
    elif action == 'reject':
        cur.execute("UPDATE join_request SET status = 'rejected' WHERE jr_id = %s", (jr_id,))
        conn.commit()
        flash('Request rejected.', 'success')
    else:  # action == 'accept'
        cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (ws['w_id'],))
        current = cur.fetchone()['n']

        if current >= ws['capacity']:
            flash('Your workshop is full. Increase capacity to accept more mechanics.', 'error')
        else:
            cur.execute("UPDATE mechanic SET w_id = %s WHERE m_id = %s AND w_id IS NULL",
                        (ws['w_id'], req['m_id']))
            if cur.rowcount:
                cur.execute("UPDATE join_request SET status = 'accepted' WHERE jr_id = %s", (jr_id,))
                cur.execute("""
                    UPDATE join_request SET status = 'rejected'
                    WHERE m_id = %s AND status = 'pending'
                """, (req['m_id'],))
                flash('Mechanic added to your workshop.', 'success')
            else:
                cur.execute("UPDATE join_request SET status = 'rejected' WHERE jr_id = %s", (jr_id,))
                flash('That mechanic already joined another workshop.', 'error')
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

    flash(f'Booking {new_status}.' if changed else 'Booking not found or cannot be changed.', 'success' if changed else 'error')
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
        flash('Service added.', 'success')
    except Exception:
        conn.rollback()
        flash('You already offer this service.', 'error')

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

    flash('Workshop created!', 'success')
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
        flash('Create your workshop first.', 'error')
        return redirect(url_for('dashboard.owner'))

    photo = request.files.get('photo')
    if photo and photo.filename and allowed_file(photo.filename):
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = secure_filename(f"workshop_{workshop['w_id']}_{photo.filename}")
        photo.save(os.path.join(UPLOAD_FOLDER, filename))
        photo_path = f"uploads/workshops/{filename}"

        cur.execute("UPDATE workshop SET photo_path = %s WHERE w_id = %s", (photo_path, workshop['w_id']))
        conn.commit()
        flash('Workshop photo updated.', 'success')
    else:
        flash('Please upload a valid image (png, jpg, jpeg, webp).', 'error')

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
            flash('You do not have a workshop to delete.', 'error')
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
            flash('Workshop deleted. Its mechanics are now unassigned.', 'success')
    except Exception:
        conn.rollback()
        logging.exception('Failed to delete workshop for user_id=%s', session.get('user_id'))
        flash('Could not delete the workshop. No changes were saved.', 'error')
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
        flash('Capacity must be a number.', 'error')
        return redirect(url_for('dashboard.owner'))

    if capacity < 1 or capacity > 100:
        flash('Capacity must be between 1 and 100.', 'error')
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
        flash(f'You already have {current} mechanics, so capacity can\'t be lower than that.', 'error')
    else:
        cur.execute("UPDATE workshop SET capacity = %s WHERE w_id = %s", (capacity, ws['w_id']))
        conn.commit()
        flash('Capacity updated.', 'success')

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
        flash('Profile updated.', 'success')
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
        flash('Please fill in all password fields.', 'error')
        return redirect(url_for('dashboard.profile'))

    if new_password != confirm_password:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('dashboard.profile'))

    if len(new_password) < 8:
        flash('New password must be at least 8 characters long.', 'error')
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
            flash('User account not found.', 'error')
            return redirect(url_for('dashboard.profile'))

        # Check current password
        if not check_password_hash(user['password'], current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('dashboard.profile'))

        # Prevent using the same password
        if check_password_hash(user['password'], new_password):
            flash('New password must be different from your current password.', 'error')
            return redirect(url_for('dashboard.profile'))

        # Hash the new password using the same method as signup
        new_password_hash = generate_password_hash(new_password)

        cur.execute(
            "UPDATE users SET password = %s WHERE u_id = %s",
            (new_password_hash, session['user_id'])
        )

        conn.commit()

        flash('Password changed successfully.', 'success')

    except Exception:
        conn.rollback()
        logging.exception("Error changing password")
        flash('Something went wrong while changing your password.', 'error')

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
        flash('Profile picture updated.', 'success')
    else:
        flash('Please upload a valid image (png, jpg, jpeg, webp).', 'error')

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
        flash('Profile picture removed.', 'success')

    cur.close()
    conn.close()

    return redirect(url_for('dashboard.profile'))

UPLOAD_FOLDER = os.path.join('app', 'static', 'uploads', 'workshops')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS