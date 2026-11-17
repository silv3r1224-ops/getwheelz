import math
import re

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from app import booking_events, contact, ranking, review_rules, vehicles
from app import booking_rules as rules
from app.db import get_db_connection
from app.utils import decode_uid, role_required, safe_back
from app.workshop_hours import fetch_map, open_now

workshops_bp = Blueprint("workshops", __name__)

# The workshop column that says "serves this vehicle type". Only ever filled from these two
# fixed strings (the vehicle type is validated first), never from user text.
_SERVES_COLUMN = {
    vehicles.CAR: "w.serves_cars",
    vehicles.TWO_WHEELER: "w.serves_two_wheelers",
}


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
    # "brake oil" / "brake,oil" becomes two search terms so a workshop offering
    # either matches (OR across terms); a single term still works as before.
    service_terms = [t for t in re.split(r"[\s,]+", service) if t] if service else []
    terms = service_terms + [
        s for s in picked if s.lower() not in (t.lower() for t in service_terms)
    ]

    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    if lat is None or lng is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        lat = lng = None

    # Step one is the vehicle type (spec section 5): until the visitor picks cars or two-wheelers
    # the page only asks that question, and nothing is searched.
    vehicle = vehicles.chosen_vehicle(remember=True)
    if vehicle is None:
        return render_template(
            "workshops/search.html",
            needs_vehicle=True,
            workshops=[],
            service=service,
            terms=terms,
            user_lat=lat,
            user_lng=lng,
            bookmarked_ids=[],
        )

    # Only workshops that serve the chosen type, and only that type's services. A workshop that
    # serves both shows up for either choice, listing just the matching services.
    where, where_params = f"WHERE w.status = 'approved' AND {_SERVES_COLUMN[vehicle]}", []
    if terms:
        likes = " OR ".join(["sc2.s_name ILIKE %s"] * len(terms))
        where += f""" AND EXISTS (
            SELECT 1 FROM service s2 JOIN service_catalog sc2 ON sc2.sc_id = s2.sc_id
            WHERE s2.w_id = w.w_id AND sc2.vehicle_type = %s AND ({likes}))"""
        where_params = [vehicle] + [_like(t) for t in terms]
    params = [vehicle] + where_params  # the first %s is the service_catalog join below

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT w.w_id, w.name, w.address, w.latitude, w.longitude, w.photo_path, w.is_open,
                       w.serves_cars, w.serves_two_wheelers,
                       array_agg(DISTINCT sc.s_name) FILTER (WHERE sc.s_name IS NOT NULL) AS service_names,
                       (SELECT AVG(r.rating) FROM review r WHERE r.w_id = w.w_id) AS rating_avg,
                       (SELECT COUNT(*) FROM review r WHERE r.w_id = w.w_id) AS rating_count
                FROM workshop w
                LEFT JOIN service s ON s.w_id = w.w_id
                LEFT JOIN service_catalog sc ON sc.sc_id = s.sc_id AND sc.vehicle_type = %s
                {where}
                GROUP BY w.w_id, w.name, w.address, w.latitude, w.longitude, w.photo_path, w.is_open,
                         w.serves_cars, w.serves_two_wheelers
            """,
                params,
            )
            rows = cur.fetchall()

            w_ids = [r['w_id'] for r in rows]
            team_map = {}
            if w_ids:
                cur.execute("""
                    SELECT m.w_id, u.name, u.profile_picture, m.experience_yrs
                    FROM mechanic m JOIN users u ON m.u_id = u.u_id
                    WHERE m.w_id = ANY(%s)
                """, (w_ids,))
                for tm in cur.fetchall():
                    team_map.setdefault(tm['w_id'], []).append(dict(tm))

            # signed-in customers see which results they already saved
            bookmarked_ids = []
            if session.get("role") == "customer":
                cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
                c_row = cur.fetchone()
                if c_row:
                    cur.execute("SELECT w_id FROM bookmark WHERE c_id = %s", (c_row["c_id"],))
                    bookmarked_ids = [r["w_id"] for r in cur.fetchall()]

            # opening hours turn the manual Open/Closed flag into an effective "open now"
            hours_map = {}
            if w_ids:
                hours_map = fetch_map(cur, w_ids)
    finally:
        conn.close()

    workshops = []
    for r in rows:
        w = dict(r)
        w["rating_avg"] = float(w["rating_avg"]) if w["rating_avg"] is not None else None
        w["team"] = team_map.get(w["w_id"], [])
        w["distance_km"] = w["distance_label"] = None
        if lat is not None and w["latitude"] is not None and w["longitude"] is not None:
            km = _distance_km(lat, lng, w["latitude"], w["longitude"])
            w["distance_km"] = round(km, 3)
            w["distance_label"] = _distance_label(km)
        workshops.append(w)

    # effective "open now" combines the manual switch with today's schedule
    for w in workshops:
        w["is_open"] = open_now(w["is_open"], hours_map.get(w["w_id"], {}))

    # Order: best match (distance + rating) by default; see app/ranking.py for the formula.
    sort_mode = ranking.normalize_sort(request.args.get("sort"))
    workshops = ranking.sort_workshops(workshops, sort_mode, have_location=lat is not None)

    return render_template(
        "workshops/search.html",
        needs_vehicle=False,
        workshops=workshops,
        service=service,
        terms=terms,
        user_lat=lat,
        user_lng=lng,
        bookmarked_ids=bookmarked_ids,
        sort_mode=sort_mode,
        sort_labels=ranking.SORT_LABELS,
    )


@workshops_bp.route("/nearby")
def nearby():
    try:
        lat = float(request.args["lat"])
        lng = float(request.args["lng"])
        radius = min(float(request.args.get("radius", 25)), 200)
    except (KeyError, ValueError):
        return jsonify(error="Invalid location"), 400

    # the customer's picked vehicle type (?vehicle=, else the one remembered in the session)
    vehicle = vehicles.chosen_vehicle()
    serves_filter = f"AND {_SERVES_COLUMN[vehicle]}" if vehicle else ""

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT * FROM (
            SELECT w.w_id, w.name, w.address, w.photo_path, w.is_open,
                   6371 * acos(LEAST(1, GREATEST(-1,
                       cos(radians(%s)) * cos(radians(w.latitude))
                       * cos(radians(w.longitude) - radians(%s))
                       + sin(radians(%s)) * sin(radians(w.latitude))
                   ))) AS distance_km
            FROM workshop w
            WHERE w.status = 'approved'
              {serves_filter}
              AND w.latitude IS NOT NULL AND w.longitude IS NOT NULL
        ) t
        WHERE distance_km <= %s
        ORDER BY distance_km
        LIMIT 12
    """,
        (lat, lng, lat, radius),
    )
    rows = cur.fetchall()
    w_ids = [r['w_id'] for r in rows]
    team_map = {}
    if w_ids:
        cur.execute("""
            SELECT m.w_id, u.name, u.profile_picture, m.experience_yrs
            FROM mechanic m JOIN users u ON m.u_id = u.u_id
            WHERE m.w_id = ANY(%s)
        """, (w_ids,))
        for tm in cur.fetchall():
            team_map.setdefault(tm['w_id'], []).append(dict(tm))

    bookmarked_ids = []
    if session.get("role") == "customer":
        cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
        c_row = cur.fetchone()
        if c_row:
            cur.execute("SELECT w_id FROM bookmark WHERE c_id = %s", (c_row["c_id"],))
            bookmarked_ids = [r["w_id"] for r in cur.fetchall()]

    # effective "open now"; the schedule is fetched while the cursor is still open
    hours_map = {}
    if w_ids:
        hours_map = fetch_map(cur, w_ids)
    cur.close()
    conn.close()

    bookmarked_set = set(bookmarked_ids)
    return jsonify(
        [
            {
                "w_id": r["w_id"],
                "url": url_for("workshops.selected", w_id=r["w_id"]),
                "name": r["name"],
                "address": r["address"],
                "photo_url": r["photo_path"],
                "is_open": open_now(r["is_open"], hours_map.get(r["w_id"], {})),
                "distance_km": round(r["distance_km"], 1),
                "team": team_map.get(r["w_id"], []),
                "bookmarked": r["w_id"] in bookmarked_set,
            }
            for r in rows
        ]
    )


@workshops_bp.route("/<sealed(workshop):w_id>")
def selected(w_id):
    vehicle = vehicles.chosen_vehicle(remember=True)
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM workshop WHERE w_id = %s", (w_id,))
    workshop = cur.fetchone()
    if not workshop:
        cur.close()
        conn.close()
        abort(404)

    # Unapproved workshops are invisible to the public; only the owner and
    # admins may open them (the owner needs the page while it waits for review).
    if workshop["status"] != "approved":
        allowed = False
        if session.get("role") == "admin":
            allowed = True
        elif session.get("role") == "owner":
            cur.execute(
                "SELECT 1 FROM owner WHERE u_id = %s AND o_id = %s",
                (session["user_id"], workshop["o_id"]),
            )
            allowed = cur.fetchone() is not None
        if not allowed:
            cur.close()
            conn.close()
            abort(404)

    cur.execute(
        """
        SELECT s.s_id, sc.s_name, sc.vehicle_type, s.price_range, s.duration
        FROM service s
        JOIN service_catalog sc ON sc.sc_id = s.sc_id
        WHERE s.w_id = %s
        ORDER BY sc.s_name
    """,
        (w_id,),
    )
    services = cur.fetchall()

    # What this workshop serves, and what to show. With a vehicle picked only that type's services
    # are listed; a workshop that does not serve the picked type lists none and says so.
    served_types = vehicles.workshop_types(
        workshop["serves_cars"], workshop["serves_two_wheelers"]
    )
    vehicle_mismatch = vehicle is not None and vehicle not in served_types
    if vehicle is not None:
        services = [s for s in services if s["vehicle_type"] == vehicle]

    # who runs it: the public owner-mapping function (RLS keeps the `owner` table
    # private, so this security-definer lookup is the only sanctioned read path for
    # visitors). A workshop always has an owner row (NOT NULL FK), so no fallback
    # guessing is needed — the card shows nothing only if a row truly is missing.
    owner = None
    if workshop.get('o_id'):
        cur.execute(
            "SELECT * FROM public_workshop_owner(%s)", (workshop["o_id"],)
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

    # --- reviews and rating (public) ---------------------------------------------------------
    cur.execute(
        "SELECT AVG(rating) AS avg, COUNT(*) AS n FROM review WHERE w_id = %s", (w_id,)
    )
    agg = cur.fetchone()
    rating_count = agg["n"]
    rating_avg = float(agg["avg"]) if agg["avg"] is not None else None
    cur.execute(
        """
        SELECT r_id, rating, comment, reviewer_name, created_at, owner_reply, owner_replied_at
        FROM review WHERE w_id = %s ORDER BY created_at DESC, r_id DESC LIMIT 20
        """,
        (w_id,),
    )
    reviews = cur.fetchall()

    role = session.get("role")
    # which of this customer's completed visits can still be reviewed (one review per booking)
    reviewable = []
    if role == "customer":
        cur.execute(
            """
            SELECT b.b_id, b.requested_time, sc.s_name
            FROM booking b
            JOIN service s ON s.s_id = b.s_id
            JOIN service_catalog sc ON sc.sc_id = s.sc_id
            WHERE b.w_id = %s AND b.status = 'completed'
              AND b.c_id = (SELECT c_id FROM customer WHERE u_id = %s)
              AND NOT EXISTS (SELECT 1 FROM review r WHERE r.b_id = b.b_id)
            ORDER BY b.requested_time DESC
            """,
            (w_id, session["user_id"]),
        )
        reviewable = cur.fetchall()
    # the owner of THIS workshop may reply to its reviews
    is_workshop_owner = False
    if role == "owner":
        cur.execute(
            "SELECT 1 FROM owner WHERE u_id = %s AND o_id = %s",
            (session["user_id"], workshop["o_id"]),
        )
        is_workshop_owner = cur.fetchone() is not None

    # --- contact buttons: numbers only reach the page for a signed-in customer or mechanic ----
    workshop = dict(workshop)

    # opening hours: the badge shows the EFFECTIVE status (switch AND today's schedule),
    # and the weekly schedule itself is shown on the page
    cur.execute(
        "SELECT dow, open_time, close_time FROM workshop_hours WHERE workshop_id = %s ORDER BY dow",
        (workshop["w_id"],),
    )
    hours = [dict(r) for r in cur.fetchall()]
    hours_uniform = len({(h["open_time"], h["close_time"]) for h in hours}) == 1 if hours else False
    hours_map = {r["dow"]: (r["open_time"], r["close_time"]) for r in hours}
    workshop["is_open"] = open_now(workshop["is_open"], hours_map)
    # Contact details are public on the hero card so anyone can reach the workshop.
    contact_buttons = contact.public_buttons(workshop.get("contact_no"), workshop.get("whatsapp_no"))
    workshop_contact_no = (workshop.get("contact_no") or "").strip() or None
    workshop_whatsapp_no = (workshop.get("whatsapp_no") or "").strip() or None
    workshop.pop("contact_no", None)
    workshop.pop("whatsapp_no", None)

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

    # is the signed-in customer already saving this workshop?
    is_bookmarked = False
    if session.get("role") == "customer":
        cur.execute("SELECT c_id FROM customer WHERE u_id = %s", (session["user_id"],))
        c_row = cur.fetchone()
        if c_row:
            cur.execute(
                "SELECT 1 FROM bookmark WHERE c_id = %s AND w_id = %s",
                (c_row["c_id"], w_id),
            )
            is_bookmarked = cur.fetchone() is not None

    cur.close()
    conn.close()

    return render_template(
        "workshops/selected.html",
        workshop=workshop,
        hours=hours,
        hours_uniform=hours_uniform,
        services=services,
        mech=mech,
        owner=owner,
        team=team,
        completed_jobs=completed_jobs,
        is_bookmarked=is_bookmarked,
        served_types=served_types,
        vehicle_mismatch=vehicle_mismatch,
        contact_buttons=contact_buttons,
        workshop_contact_no=workshop_contact_no,
        workshop_whatsapp_no=workshop_whatsapp_no,
        rating_avg=rating_avg,
        rating_count=rating_count,
        reviews=reviews,
        reviewable=reviewable,
        is_workshop_owner=is_workshop_owner,
        stars=review_rules.stars,
        review_text_max=review_rules.TEXT_MAX,
    )


@workshops_bp.route("/<sealed(workshop):w_id>/review", methods=["POST"])
@role_required("customer")
def post_review(w_id):
    """A customer reviews one of their COMPLETED bookings at this workshop, once."""
    back = url_for("workshops.selected", w_id=w_id) + "#reviews"
    rating, text, error = review_rules.clean_review(
        request.form.get("rating"), request.form.get("comment")
    )
    b_id = request.form.get("b_id", type=int)
    if error or b_id is None:
        flash(error or "Please choose which visit you are reviewing.", "error")
        return redirect(back)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM users WHERE u_id = %s", (session["user_id"],))
            name = review_rules.public_name(cur.fetchone()["name"])
            # The review is built FROM the booking, so the workshop and customer can never
            # disagree with it, and only a completed booking of this customer qualifies.
            cur.execute(
                """
                INSERT INTO review (b_id, w_id, c_id, rating, comment, reviewer_name, created_at)
                SELECT b.b_id, b.w_id, b.c_id, %s, %s, %s, %s
                FROM booking b
                WHERE b.b_id = %s AND b.w_id = %s AND b.status = 'completed'
                  AND b.c_id = (SELECT c_id FROM customer WHERE u_id = %s)
                ON CONFLICT (b_id) DO NOTHING
                RETURNING r_id
                """,
                (rating, text, name, rules.now(), b_id, w_id, session["user_id"]),
            )
            created = cur.fetchone()
            reason = None
            if created:
                cur.execute(
                    "SELECT u_id FROM public_workshop_owner((SELECT o_id FROM workshop WHERE w_id = %s))",
                    (w_id,),
                )
                owner_row = cur.fetchone()
                if owner_row:
                    booking_events.send_notice(
                        cur,
                        owner_row["u_id"],
                        f"New {rating}-star review from {name}",
                        f"{name} reviewed your workshop: {text}\n\nYou can post one public reply "
                        "from your workshop page.",
                        rules.now(),
                    )
            else:
                cur.execute(
                    "SELECT 1 FROM review WHERE b_id = %s", (b_id,)
                )
                reason = "already" if cur.fetchone() else "ineligible"
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if created:
        flash("Thanks! Your review is now on the workshop page.", "success")
    elif reason == "already":
        flash("You have already reviewed that visit.", "error")
    else:
        flash("You can only review a completed booking of your own at this workshop.", "error")
    return redirect(back)


@workshops_bp.route("/review/<sealed(review):r_id>/reply", methods=["POST"])
@role_required("owner")
def reply_to_review(r_id):
    """The workshop's owner posts ONE public reply to a review of their workshop."""
    text, error = review_rules.clean_reply(request.form.get("reply"))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            w_id = None
            if not error:
                # only this owner's workshop, and only while there is no reply yet
                cur.execute(
                    """
                    UPDATE review SET owner_reply = %s, owner_replied_at = %s
                    WHERE r_id = %s AND owner_reply IS NULL
                      AND w_id = (SELECT w.w_id FROM workshop w JOIN owner o ON o.o_id = w.o_id
                                  WHERE o.u_id = %s)
                    RETURNING b_id, w_id
                    """,
                    (text, rules.now(), r_id, session["user_id"]),
                )
                done = cur.fetchone()
                if done:
                    w_id = done["w_id"]
                    parties = booking_events.get_parties(cur, done["b_id"])
                    if parties:
                        booking_events.send_notice(
                            cur,
                            parties["customer_u_id"],
                            f'{parties["workshop_name"]} replied to your review',
                            f'{parties["workshop_name"]} replied: {text}',
                            rules.now(),
                        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if error:
        flash(error, "error")
        return redirect(safe_back(url_for("dashboard.owner")))
    if not w_id:
        flash("That review is not on your workshop, or it already has a reply.", "error")
        return redirect(url_for("dashboard.owner"))
    flash("Your reply is now public.", "success")
    return redirect(url_for("workshops.selected", w_id=w_id) + "#reviews")


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
        SELECT u_id, name, COALESCE(role, 'owner') AS role, profile_picture, created_at
        FROM users WHERE u_id = %s
    """,
        (u_id,),
    )
    person = cur.fetchone()
    if not person:
        cur.close()
        conn.close()
        abort(404)

    # decide the profile type once: owner-style (owns / administers workshops) vs mechanic.
    # the template must use this same flag, never second-guess from person.role alone.
    is_owner = person["role"] in ("owner", "admin") or person["role"] is None
    workshops, mech, jobs, team, boss = [], None, None, [], None

    if is_owner:
        # the public mapping function translates the account into its workshop
        # owner-ids; the rest of the reads (workshops, services, team) go through
        # the already-public workshop/service/mechanic tables, so no owner-table
        # access is needed on this public page.
        cur.execute(
            "SELECT public_owner_workshops(%s) AS o_id", (u_id,)
        )
        o_ids = [r["o_id"] for r in cur.fetchall()]

        if o_ids:
            cur.execute(
                """
                SELECT w.w_id, w.name, w.address, w.photo_path, w.capacity, w.is_open,
                (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size
                FROM workshop w
                WHERE w.o_id = ANY(%s) AND w.status = 'approved'
                ORDER BY w.name
            """,
                (o_ids,),
            )
            workshops = [dict(r) for r in cur.fetchall()]

            # effective "open now" per workshop (manual switch AND today's schedule)
            hours_map = fetch_map(cur, [w["w_id"] for w in workshops])
            for w in workshops:
                w["is_open"] = open_now(w["is_open"], hours_map.get(w["w_id"], {}))

            # what each workshop offers (names only), to show as tags on its card
            cur.execute(
                """
                SELECT s.w_id, sc.s_name
                FROM service s
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE s.w_id IN (SELECT w_id FROM workshop WHERE o_id = ANY(%s) AND status = 'approved')
                ORDER BY sc.s_name
            """,
                (o_ids,),
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
                WHERE b.w_id IN (SELECT w_id FROM workshop WHERE o_id = ANY(%s))
            """,
                (o_ids,),
            )
            job_row = cur.fetchone()
            jobs = job_row["completed"] if job_row and job_row["completed"] is not None else 0

            # everyone who works for this owner
            cur.execute(
                """
                SELECT u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat, w.name AS workshop_name
                FROM mechanic m
                JOIN users u ON m.u_id = u.u_id
                JOIN workshop w ON m.w_id = w.w_id
                WHERE w.o_id = ANY(%s)
                ORDER BY m.experience_yrs DESC NULLS LAST, u.name
            """,
                (o_ids,),
            )
            team = cur.fetchall()
    else:
        cur.execute(
            """
            SELECT m.experience_yrs, m.active_stat, w.w_id, w.o_id, w.name AS workshop_name,
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

        # effective "open now" for the mechanic's workshop
        hours_map = fetch_map(cur, [mech["w_id"]])
        mech["is_open"] = open_now(mech["is_open"], hours_map.get(mech["w_id"], {}))

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
            "SELECT * FROM public_workshop_owner(%s)", (mech["o_id"],)
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
        is_owner=is_owner,
        workshops=workshops,
        mech=mech,
        jobs=jobs,
        team=team,
        boss=boss,
    )
