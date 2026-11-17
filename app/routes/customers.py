from flask import Blueprint, jsonify, render_template, request, session

from app import vehicles
from app.db import get_db_connection
from app.utils import role_required
from app.workshop_hours import fetch_map, open_now

customer_bp = Blueprint("customer", __name__)


@customer_bp.route("/home")
@role_required("customer")
def home():
    # the vehicle type picked first (cars / two-wheelers); recommendations and the map follow it
    vehicle = vehicles.chosen_vehicle(remember=True)
    serves_filter = {
        vehicles.CAR: "AND serves_cars",
        vehicles.TWO_WHEELER: "AND serves_two_wheelers",
    }.get(vehicle, "")
    # the same filter for the query that aliases workshop as w, and the service-name join
    serves_filter_w = serves_filter.replace("serves_", "w.serves_")
    catalog_join_extra = "AND sc.vehicle_type = %s" if vehicle else ""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # latitude/longitude let the page show how far each workshop is from the visitor
            cur.execute(f"""
                SELECT w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open,
                w.serves_cars, w.serves_two_wheelers,
                array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
                FROM workshop w
                LEFT JOIN service s ON s.w_id = w.w_id
                LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id
                {catalog_join_extra}
                WHERE w.status = 'approved' {serves_filter_w}
                GROUP BY w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open, w.serves_cars, w.serves_two_wheelers
                ORDER BY w.w_id DESC
                LIMIT 10
            """, (vehicle,) if vehicle else None)
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
                AND b.status IN ('pending', 'confirmed', 'in_progress')
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
            cur.execute(f"""
                SELECT w_id, name, address, latitude, longitude
                FROM workshop
                WHERE status = 'approved' {serves_filter}
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                ORDER BY name
                LIMIT 300
            """)
            map_workshops = cur.fetchall()

            # the customer's saved workshops (full card data) and their id set,
            # so the page can render the shelf and pre-fill the bookmark buttons
            saved = []
            bookmarked_ids = []
            cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
            c_row = cur.fetchone()
            if c_row:
                cur.execute("""
                    SELECT w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open,
                    w.serves_cars, w.serves_two_wheelers,
                    array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
                    FROM bookmark b
                    JOIN workshop w ON w.w_id = b.w_id
                    LEFT JOIN service s ON s.w_id = w.w_id
                    LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id
                    WHERE b.c_id = %s AND w.status = 'approved'
                    GROUP BY w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open, w.serves_cars, w.serves_two_wheelers
                    ORDER BY MAX(b.created_at) DESC NULLS LAST
                """, (c_row["c_id"],))
                saved = cur.fetchall()
                bookmarked_ids = [r["w_id"] for r in saved]

            # effective "open now" for the recommendation and saved cards
            recommended = [dict(r) for r in recommended]
            saved = [dict(r) for r in saved]
            hours_map = {}
            if recommended:
                hours_map.update(fetch_map(cur, [r["w_id"] for r in recommended]))
            if saved:
                hours_map.update(fetch_map(cur, [r["w_id"] for r in saved]))
            for r in recommended:
                r["is_open"] = open_now(r["is_open"], hours_map.get(r["w_id"], {}))
            for r in saved:
                r["is_open"] = open_now(r["is_open"], hours_map.get(r["w_id"], {}))
    finally:
        conn.close()

    return render_template(
        "customer/home.html",
        recommended=recommended,
        next_booking=next_booking,
        recent_bookings=recent_bookings,
        map_workshops=map_workshops,
        saved=saved,
        bookmarked_ids=bookmarked_ids,
    )


@customer_bp.route("/bookmarks")
@role_required("customer")
def bookmarks():
    """Dedicated page listing the customer's saved workshops."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
            c_row = cur.fetchone()
            saved = []
            bookmarked_ids = []
            if c_row:
                cur.execute("""
                    SELECT w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open,
                    w.serves_cars, w.serves_two_wheelers,
                    array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
                    FROM bookmark b
                    JOIN workshop w ON w.w_id = b.w_id
                    LEFT JOIN service s ON s.w_id = w.w_id
                    LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id
                    WHERE b.c_id = %s AND w.status = 'approved'
                    GROUP BY w.w_id, w.name, w.address, w.photo_path, w.latitude, w.longitude, w.is_open, w.serves_cars, w.serves_two_wheelers
                    ORDER BY MAX(b.created_at) DESC NULLS LAST
                """, (c_row["c_id"],))
                saved = cur.fetchall()
                bookmarked_ids = [r["w_id"] for r in saved]

                # effective "open now" for the saved cards
                saved = [dict(r) for r in saved]
                hours_map = fetch_map(cur, [r["w_id"] for r in saved]) if saved else {}
                for r in saved:
                    r["is_open"] = open_now(r["is_open"], hours_map.get(r["w_id"], {}))
    finally:
        conn.close()

    return render_template(
        "customer/bookmarks.html",
        saved=saved,
        bookmarked_ids=bookmarked_ids,
    )


@customer_bp.route("/bookmarks/toggle", methods=["POST"])
@role_required("customer")
def toggle_bookmark():
    """Save / unsave a workshop for the signed-in customer. Returns the new state."""
    data = request.get_json(silent=True) or {}
    try:
        w_id = int(data.get("w_id"))
    except (TypeError, ValueError):
        return jsonify(error="Invalid workshop"), 400

    conn = get_db_connection()
    saved = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
            c_row = cur.fetchone()
            if not c_row:
                return jsonify(error="No customer profile"), 403

            cur.execute("SELECT 1 FROM workshop WHERE w_id = %s AND status = 'approved'", (w_id,))
            if not cur.fetchone():
                return jsonify(error="Workshop not found"), 404

            cur.execute(
                """
                INSERT INTO bookmark (c_id, w_id) VALUES (%s, %s)
                ON CONFLICT (c_id, w_id) DO NOTHING
                RETURNING c_id
                """,
                (c_row["c_id"], w_id),
            )
            saved = cur.fetchone() is not None
            if not saved:
                cur.execute(
                    "DELETE FROM bookmark WHERE c_id = %s AND w_id = %s",
                    (c_row["c_id"], w_id),
                )
        conn.commit()
    finally:
        conn.close()

    return jsonify(saved=saved)