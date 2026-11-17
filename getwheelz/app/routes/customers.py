from flask import Blueprint, render_template, session
from app.db import get_db_connection
from app.utils import role_required

customer_bp = Blueprint("customer", __name__)


@customer_bp.route("/home")
@role_required("customer")
def home():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # latitude/longitude let the page show how far each workshop is from the visitor
            cur.execute("""
                SELECT w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open,
                array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
                FROM workshop w
                LEFT JOIN service s ON s.w_id = w.w_id
                LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id
                GROUP BY w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open
                ORDER BY w.w_id DESC
                LIMIT 10
            """)
            recommended = cur.fetchall()

            # the customer's soonest upcoming appointment, if any
            cur.execute(
                """
                SELECT b.b_id, b.requested_time, b.status, w.name AS workshop_name, sc.s_name
                FROM booking b
                JOIN customer c ON b.c_id = c.c_id
                JOIN workshop w ON b.w_id = w.w_id
                JOIN service s ON b.s_id = s.s_id
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE c.u_id = %s
                AND b.status IN ('pending', 'confirmed')
                AND b.requested_time >= NOW()
                ORDER BY b.requested_time
                LIMIT 1
            """,
                (session["user_id"],),
            )
            next_booking = cur.fetchone()

            # the three most recent bookings, for the "pick up where you left off" section
            cur.execute(
                """
                SELECT b.b_id, b.requested_time, b.status, w.w_id, w.name AS workshop_name, sc.s_name
                FROM booking b
                JOIN customer c ON b.c_id = c.c_id
                JOIN workshop w ON b.w_id = w.w_id
                JOIN service s ON b.s_id = s.s_id
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE c.u_id = %s
                ORDER BY b.requested_time DESC
                LIMIT 3
            """,
                (session["user_id"],),
            )
            recent_bookings = cur.fetchall()

            # every pinned workshop, for the map section
            cur.execute("""
                SELECT w_id, name, address, latitude, longitude
                FROM workshop
                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY name
                LIMIT 300
            """)
            map_workshops = cur.fetchall()
    finally:
        conn.close()

    return render_template(
        "customer/home.html",
        recommended=recommended,
        next_booking=next_booking,
        recent_bookings=recent_bookings,
        map_workshops=map_workshops,
    )