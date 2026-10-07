from flask import Blueprint, render_template
from app.db import get_db_connection
from app.utils import role_required

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/home')
@role_required('customer')
def home():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT w.w_id, w.name, w.address, w.photo_path,
        array_agg(DISTINCT s.s_name) FILTER (WHERE s.s_name IS NOT NULL) AS service_names
        FROM workshop w
        LEFT JOIN service s ON s.w_id = w.w_id
        GROUP BY w.w_id, w.name, w.address, w.photo_path
        ORDER BY w.w_id DESC
        LIMIT 10
    """)
    recommended = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('customer/home.html', recommended=recommended)