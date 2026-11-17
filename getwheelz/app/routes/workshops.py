import math
from flask import Blueprint, render_template, request, jsonify, abort, session
from app.db import get_db_connection
from app.utils import decode_uid

workshops_bp = Blueprint("workshops", __name__)


def _distance_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in kilometres (same formula the /nearby query uses)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_lng = math.radians(lng2 - lng1)
    cos_angle = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(
        d_lng
    )
    return 6371 * math.acos(max(-1.0, min(1.0, cos_angle)))


def _distance_label(km):
    """450 m, 3.2 km, 27 km (kept identical to GW.formatDistance in distance.js)."""
    if km < 1:
        return f"{max(10, round(km * 100) * 10)} m"
    if km < 10:
        return f"{km:.1f} km"
    return f"{round(km)} km"


def _like(term):
    """Turn user text into a safe ILIKE pattern (so '%' and '_' typed by the user are literal)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@workshops_bp.route("/search")
def search():
    service = request.args.get("service", "").strip()
    picked = [s.strip() for s in request.args.getlist("services") if s.strip()]
    terms = ([service] if service else []) + [
        s for s in picked if s.lower() != service.lower()
    ]

    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None

    where, params = "", []
    if terms:
        likes = " OR ".join(["sc2.s_name ILIKE %s"] * len(terms))
        where = f"""WHERE EXISTS (
            SELECT 1 FROM service s2 JOIN service_catalog sc2 ON sc2.sc_id = s2.sc_id
            WHERE s2.w_id = w.w_id AND ({likes}))"""
        params = [_like(t) for t in terms]

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT w.w_id, w.name, w.address, w.latitude, w.longitude, w.photo_path, w.is_open,
                       array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names
                FROM workshop w
                LEFT JOIN service s ON s.w_id = w.w_id
                LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id
                {where}
                GROUP BY w.w_id, w.name, w.address, w.latitude, w.longitude, w.photo_path, w.is_open
            """,
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    workshops = []
    for r in rows:
        w = dict(r)
        w["distance_km"] = w["distance_label"] = None
        if lat is not None and w["latitude"] is not None and w["longitude"] is not None:
            km = _distance_km(lat, lng, w["latitude"], w["longitude"])
            w["distance_km"] = round(km, 3)
            w["distance_label"] = _distance_label(km)
        workshops.append(w)

    # nearest first when we know where the visitor is, otherwise A to Z
    if lat is not None:
        workshops.sort(
            key=lambda w: (
                w["distance_km"] is None,
                w["distance_km"] or 0,
                w["name"].lower(),
            )
        )
    else:
        workshops.sort(key=lambda w: w["name"].lower())

    return render_template(
        "workshops/search.html",
        workshops=workshops,
        service=service,
        terms=terms,
        user_lat=lat,
        user_lng=lng,
    )


@workshops_bp.route("/nearby")
def nearby():
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
        radius = min(float(request.args.get("radius", 25)), 200)
    except (KeyError, ValueError):
        return jsonify(error="Invalid location"), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM (
            SELECT w.w_id, w.name, w.address, w.photo_path, w.is_open,
                   6371 * acos(LEAST(1, GREATEST(-1,
                       cos(radians(%s)) * cos(radians(w.latitude))
                       * cos(radians(w.longitude) - radians(%s))
                       + sin(radians(%s)) * sin(radians(w.latitude))
                   ))) AS distance_km
            FROM workshop w
            WHERE w.latitude IS NOT NULL AND w.longitude IS NOT NULL
        ) t
        WHERE distance_km <= %s
        ORDER BY distance_km
        LIMIT 12
    """,
        (lat, lng, lat, radius),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(
        [
            {
                "w_id": r["w_id"],
                "name": r["name"],
                "address": r["address"],
                "photo_url": r["photo_path"],
                "is_open": r["is_open"],
                "distance_km": round(r["distance_km"], 1),
            }
            for r in rows
        ]
    )


@workshops_bp.route("/<int:w_id>")
def selected(w_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM workshop WHERE w_id = %s", (w_id,))
    workshop = cur.fetchone()
    if not workshop:
        cur.close()
        conn.close()
        abort(404)

    cur.execute(
        """
        SELECT s.s_id, sc.s_name, s.price_range, s.duration
        FROM service s
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        WHERE s.w_id = %s
        ORDER BY sc.s_name
    """,
        (w_id,),
    )
    services = cur.fetchall()

    # who runs it and who works there: public-facing details only (no email, no phone)
    cur.execute(
        """
        SELECT u.u_id, u.name, u.profile_picture, u.created_at AS since,
        (SELECT COUNT(*) FROM workshop w2 WHERE w2.o_id = o.o_id) AS workshop_count
        FROM owner o JOIN users u ON o.u_id = u.u_id
        WHERE o.o_id = %s
    """,
        (workshop["o_id"],),
    )
    owner = cur.fetchone()

    cur.execute(
        """
        SELECT u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat
        FROM mechanic m JOIN users u ON m.u_id = u.u_id
        WHERE m.w_id = %s
        ORDER BY m.experience_yrs DESC NULLS LAST, u.name
    """,
        (w_id,),
    )
    team = cur.fetchall()

    cur.execute(
        "SELECT COUNT(*) AS n FROM booking WHERE w_id = %s AND status = 'completed'",
        (w_id,),
    )
    completed_jobs = cur.fetchone()["n"]

    # extra context when a mechanic is previewing the workshop
    mech = None
    if session.get("role") == "mechanic":
        cur.execute(
            "SELECT m_id, w_id FROM mechanic WHERE u_id = %s", (session["user_id"],)
        )
        m = cur.fetchone()
        if m:
            cur.execute("SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (w_id,))
            total = cur.fetchone()["n"]
            cur.execute(
                "SELECT 1 FROM join_request WHERE m_id = %s AND w_id = %s AND status = 'pending'",
                (m["m_id"], w_id),
            )
            mech = {
                "my_workshop": m["w_id"],
                "pending": cur.fetchone() is not None,
                "total": total,
                "capacity": workshop["capacity"],
                "open_slots": workshop["capacity"] - total,
            }

    cur.close()
    conn.close()

    return render_template(
        "workshops/selected.html",
        workshop=workshop,
        services=services,
        mech=mech,
        owner=owner,
        team=team,
        completed_jobs=completed_jobs,
    )


@workshops_bp.route("/profile/<token>")
def person(token):
    """Public, read-only profile of a workshop owner or a mechanic who works at a workshop.

    Open to visitors who are not logged in and to customers. Only name, picture, join date and
    work details are shown, never an email address or phone number.
    """
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT u_id, name, role, profile_picture, created_at
        FROM users WHERE u_id = %s AND role IN ('owner', 'mechanic')
    """,
        (u_id,),
    )
    person = cur.fetchone()
    if not person:
        cur.close()
        conn.close()
        abort(404)

    workshops, mech, jobs, team, boss = [], None, None, [], None

    if person["role"] == "owner":
        cur.execute(
            """
            SELECT w.w_id, w.name, w.address, w.photo_path, w.capacity, w.is_open,
            (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size
            FROM workshop w JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            ORDER BY w.name
        """,
            (u_id,),
        )
        workshops = [dict(r) for r in cur.fetchall()]

        # what each workshop offers (names only), to show as tags on its card
        cur.execute(
            """
            SELECT s.w_id, sc.s_name
            FROM service s
            JOIN service_catalog sc ON sc.sc_id = s.sc_id
            JOIN workshop w ON w.w_id = s.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            ORDER BY sc.s_name
        """,
            (u_id,),
        )
        by_workshop = {}
        for r in cur.fetchall():
            by_workshop.setdefault(r["w_id"], []).append(r["s_name"])
        for w in workshops:
            w["service_names"] = by_workshop.get(w["w_id"], [])

        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE b.status = 'completed') AS completed
            FROM booking b
            JOIN workshop w ON b.w_id = w.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
        """,
            (u_id,),
        )
        jobs = cur.fetchone()["completed"]

        # everyone who works for this owner
        cur.execute(
            """
            SELECT u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat, w.name AS workshop_name
            FROM mechanic m
            JOIN users u ON m.u_id = u.u_id
            JOIN workshop w ON m.w_id = w.w_id
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
            ORDER BY m.experience_yrs DESC NULLS LAST, u.name
        """,
            (u_id,),
        )
        team = cur.fetchall()
    else:
        cur.execute(
            """
            SELECT m.experience_yrs, m.active_stat, w.w_id, w.name AS workshop_name,
            w.address, w.photo_path, w.is_open, w.contact_no
            FROM mechanic m JOIN workshop w ON m.w_id = w.w_id
            WHERE m.u_id = %s
        """,
            (u_id,),
        )
        row = cur.fetchone()
        if not row:  # mechanics without a workshop are not publicly viewable
            cur.close()
            conn.close()
            abort(404)
        mech = dict(row)

        cur.execute(
            """
            SELECT sc.s_name
            FROM service s JOIN service_catalog sc ON sc.sc_id = s.sc_id
            WHERE s.w_id = %s
            ORDER BY sc.s_name
        """,
            (mech["w_id"],),
        )
        mech["service_names"] = [r["s_name"] for r in cur.fetchall()]

        cur.execute(
            """
            SELECT u.u_id, u.name, u.profile_picture
            FROM workshop w JOIN owner o ON w.o_id = o.o_id JOIN users u ON o.u_id = u.u_id
            WHERE w.w_id = %s
        """,
            (mech["w_id"],),
        )
        boss = cur.fetchone()

        # the rest of the crew
        cur.execute(
            """
            SELECT u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = %s AND u.u_id <> %s
            ORDER BY m.experience_yrs DESC NULLS LAST, u.name
        """,
            (mech["w_id"], u_id),
        )
        team = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "workshops/person.html",
        person=person,
        workshops=workshops,
        mech=mech,
        jobs=jobs,
        team=team,
        boss=boss,
    )
