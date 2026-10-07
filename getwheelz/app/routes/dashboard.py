from flask import Blueprint, render_template, request, session,abort,flash,redirect,url_for
import os
from werkzeug.utils import secure_filename
from app.db import get_db_connection
from app.utils import login_required, role_required

dashboard_bp = Blueprint("dashboard", __name__)


# =================================================ADMIN DASHBOARD=================================================#
@dashboard_bp.route("/admin")
@role_required("admin")
def admin():
    conn = get_db_connection()
    cur = conn.cursor()

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
        workshops=workshops,
        feedback_list=feedback_list,
        result=result,
        role=role,
        searched_email=email,
        searched = searched
    )
#Terminate
@dashboard_bp.route('/admin/terminate/<role>/<int:u_id>')
@role_required('admin')
def admin_terminate(role,u_id):
    if role not in ('customer', 'owner', 'mechanic'):
        abort(404)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE u_id=%s",(u_id,))

    conn.commit()
    cur.close()
    conn.close()

    flash("account terminated!")
    return redirect(url_for('dashboard.admin'))

#feedback
@dashboard_bp.route('/admin/feedback/<int:f_id>/read', methods=['POST'])
@role_required('admin')
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
@role_required('admin')
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
@role_required('admin')
def delete_catalog_service(sc_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM service_catalog WHERE sc_id = %s", (sc_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Service removed from catalog.')
    return redirect(url_for('dashboard.admin_services'))

# =================================================OWNER DASHBOARD=================================================#
@dashboard_bp.route('/owner')
@role_required('owner')
def owner():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT o_id FROM owner WHERE u_id = %s", (session['user_id'],))
    owner_row = cur.fetchone()

    cur.execute("SELECT w_id, name, address, contact_no, photo_path FROM workshop WHERE o_id = %s", (owner_row['o_id'],))
    workshop = cur.fetchone()

    bookings = []
    services = []
    mechanics = []
    pending_requests = []
    stats = {'total_bookings': 0, 'pending_bookings': 0, 'total_services': 0, 'total_mechanics': 0}
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
            SELECT s.s_id, sc.s_name, s.price_range, s.duration
            FROM service s
            JOIN service_catalog sc ON s.sc_id = sc.sc_id
            WHERE s.w_id = %s
        """, (workshop['w_id'],))
        services = cur.fetchall()

        cur.execute("""
            SELECT m.m_id, u.name, u.email, m.experience_yrs, m.active_stat
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = %s
        """, (workshop['w_id'],))
        mechanics = cur.fetchall()

        stats['total_bookings'] = len(bookings)
        stats['pending_bookings'] = len([b for b in bookings if b['status'] == 'pending'])
        stats['total_services'] = len(services)
        stats['total_mechanics'] = len(mechanics)

    cur.close()
    conn.close()

    return render_template('dashboard/owner.html',
        workshop=workshop,
        bookings=bookings,
        services=services,
        mechanics=mechanics,
        stats=stats,
        service_catalog=service_catalog,
    )

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

#=============================================================PROFILE========================================================#
@dashboard_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT u_id, name, email, role, created_at FROM users WHERE u_id = %s", (session['user_id'],))
    user = cur.fetchone()

    role_info = {}
    if user['role'] == 'customer':
        cur.execute("SELECT phone_no FROM customer WHERE u_id = %s", (session['user_id'],))
        role_info = cur.fetchone()
    elif user['role'] == 'mechanic':
        cur.execute("""
            SELECT m.experience_yrs, m.availability_status, w.name AS workshop_name
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

UPLOAD_FOLDER = os.path.join('app', 'static', 'uploads', 'workshops')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS