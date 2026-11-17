import logging
import os
import re
from datetime import datetime, timedelta

from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash

from app import vehicles
from app.catalog import clear_catalog_cache
from app.db import get_db_connection
from app.routes.dashboard import dashboard_bp
from werkzeug.exceptions import HTTPException

from app.utils import (
    UPLOAD_FOLDER,
    admin_access_required,
    decode_uid,
    decode_wid,
    encode_uid,
)

# Which account role each sub-admin type looks after.
DOMAIN_ROLE = {
    "customer_manager": "customer",
    "owner_workshop_manager": "owner",
    "mechanic_manager": "mechanic",
}
SUBADMIN_TYPES = tuple(DOMAIN_ROLE)


def _wants_json():
    """True only for the admin.js fetch() calls (they send X-Requested-With: fetch).

    Do NOT use request.accept_mimetypes.accept_json for this: a normal browser form post
    sends "Accept: text/html,...,*/*;q=0.8", and "*/*" matches JSON, so plain form submits
    (Suspend / Restore) used to get raw JSON back instead of a redirect and a flash message.
    """
    return request.headers.get("X-Requested-With") == "fetch"


def _back(fallback_endpoint="dashboard.admin", anchor=""):
    """Redirect to the page the admin came from (same site only), else to a safe default."""
    back = request.referrer
    if back and back.startswith(request.host_url):
        return redirect(back)
    return redirect(url_for(fallback_endpoint) + anchor)


def _pending_workshops(cur):
    cur.execute("""
        SELECT w.w_id, w.name, w.address, u.name AS owner_name, u.email AS owner_email
        FROM workshop w
        JOIN owner o ON w.o_id = o.o_id
        JOIN users u ON o.u_id = u.u_id
        WHERE w.status = 'pending'
        ORDER BY w.w_id
    """)
    return cur.fetchall()


def _pending_join_requests(cur):
    cur.execute("""
        SELECT jr.jr_id, jr.created_at, w.w_id, w.name AS workshop_name, w.capacity,
               (SELECT COUNT(*) FROM mechanic m2 WHERE m2.w_id = w.w_id) AS team_size,
               mu.name AS mechanic_name, mu.email AS mechanic_email
        FROM join_request jr
        JOIN mechanic m ON jr.m_id = m.m_id
        JOIN users mu ON m.u_id = mu.u_id
        JOIN workshop w ON jr.w_id = w.w_id
        WHERE jr.status = 'pending'
        ORDER BY jr.created_at
    """)
    return cur.fetchall()


# =================================================ADMIN DASHBOARD=================================================#
@dashboard_bp.route("/admin")
@admin_access_required()
def admin():
    conn = get_db_connection()
    cur = conn.cursor()

    # Sub-admins get a purpose-built dashboard containing only their assigned domain.
    cur.execute("SELECT admin_type FROM admin WHERE u_id = %s", (session["user_id"],))
    admin_profile = cur.fetchone()
    if not admin_profile:
        cur.close()
        conn.close()
        abort(403)

    if admin_profile["admin_type"] != "main":
        manager_type = admin_profile["admin_type"]
        records = []
        managed_workshops = []
        pending_workshops = []
        pending_requests = []
        if manager_type == "customer_manager":
            cur.execute("""
                SELECT c.c_id AS record_id, u.u_id, u.name, u.email, u.created_at, u.profile_picture,
                       c.phone_no,
                       (SELECT COUNT(*) FROM booking b WHERE b.c_id = c.c_id) AS booking_count
                FROM customer c JOIN users u ON c.u_id = u.u_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
        elif manager_type == "owner_workshop_manager":
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
            pending_workshops = _pending_workshops(cur)
        elif manager_type == "mechanic_manager":
            cur.execute("""
                SELECT m.m_id AS record_id, u.u_id, u.name, u.email, u.created_at, u.profile_picture,
                m.experience_yrs, m.active_stat, w.name AS workshop_name
                FROM mechanic m JOIN users u ON m.u_id = u.u_id
                LEFT JOIN workshop w ON m.w_id = w.w_id
                ORDER BY u.created_at DESC
            """)
            records = cur.fetchall()
            pending_requests = _pending_join_requests(cur)
        cur.close()
        conn.close()

        # numbers for the summary cards
        cutoff = datetime.now() - timedelta(days=30)
        stats = {
            "total": len(records),
            "new_30d": sum(
                1 for r in records if r["created_at"] and r["created_at"] >= cutoff
            ),
        }
        if manager_type == "owner_workshop_manager":
            stats["workshops"] = len(managed_workshops)
            stats["no_workshop"] = sum(1 for r in records if r["workshop_count"] == 0)
        elif manager_type == "mechanic_manager":
            stats["assigned"] = sum(1 for r in records if r["workshop_name"])
            stats["unassigned"] = len(records) - stats["assigned"]
        elif manager_type == "customer_manager":
            stats["with_bookings"] = sum(1 for r in records if r["booking_count"] > 0)

        return render_template(
            "dashboard/subadmin.html",
            manager_type=manager_type,
            records=records,
            managed_workshops=managed_workshops,
            pending_workshops=pending_workshops,
            pending_requests=pending_requests,
            stats=stats,
        )

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

    # Workshops waiting for approval (shown in the Approvals section)
    pending_workshops = _pending_workshops(cur)

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
        pending_workshops=pending_workshops,
    )


# Live search (no page reload): admin.js fetches this and renders records inline.
# The result list is capped: a broad query ("a") must not put every account on the page, and the
# admin can only delete what is on screen. Past the cap the reply says so (truncated) and the page
# asks the admin to narrow the search.
SEARCH_LIMIT = 500


@dashboard_bp.route("/admin/search")
@admin_access_required()
def admin_search():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    status_filter = request.args.get("status", "")

    if not q:
        return jsonify({"ok": False, "error": "Enter a search query."}), 400

    # The main admin searches every role; a sub-admin only ever sees their own domain.
    roles_to_check = [role] if role in ("customer", "owner", "mechanic") else ["customer", "owner", "mechanic"]
    manager_type = session.get("admin_type")
    if manager_type != "main":
        own_role = DOMAIN_ROLE.get(manager_type)
        roles_to_check = [r for r in roles_to_check if r == own_role]

    # Escape LIKE wildcards so a "%" or "_" typed by the admin is searched literally.
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"

    conn = get_db_connection()
    records = []
    try:
        with conn.cursor() as cur:
            for r_type in roles_to_check:
                # Ask for one row more than the cap in total, so "exactly at the cap" and
                # "more than the cap" can be told apart without a separate COUNT query.
                remaining = SEARCH_LIMIT + 1 - len(records)
                if remaining <= 0:
                    break
                # r_type and id_col come from fixed whitelists, never from the request
                id_col = {"customer": "c_id", "owner": "o_id", "mechanic": "m_id"}[r_type]
                clauses = "u.name ILIKE %s OR u.email ILIKE %s"
                params = [like, like]
                if r_type == "customer":  # only customers have a phone number
                    clauses += " OR t.phone_no ILIKE %s"
                    params.append(like)

                query = f"""
                    SELECT t.{id_col} AS role_id, u.u_id, u.name, u.email, u.created_at, u.is_suspended
                    FROM {r_type} t
                    JOIN users u ON t.u_id = u.u_id
                    WHERE ({clauses})
                """
                if status_filter == "suspended":
                    query += " AND u.is_suspended"
                elif status_filter == "active":
                    query += " AND NOT u.is_suspended"
                query += " ORDER BY u.created_at DESC LIMIT %s"
                params.append(remaining)

                cur.execute(query, tuple(params))
                for row in cur.fetchall():
                    records.append({
                        "u_id": row["u_id"],
                        "role_id": row["role_id"],
                        "role": r_type,
                        "name": row["name"],
                        "email": row["email"],
                        "is_suspended": bool(row["is_suspended"]),
                        "joined": row["created_at"].strftime("%d %b %Y") if row["created_at"] else "",
                        "profile_url": url_for("dashboard.admin_user_profile", token=encode_uid(row["u_id"])),
                        "delete_url": url_for("dashboard.admin_terminate", role=r_type, u_id=row["u_id"]),
                    })
    finally:
        conn.close()

    truncated = len(records) > SEARCH_LIMIT
    if truncated:
        records = records[:SEARCH_LIMIT]
    return jsonify({
        "ok": True,
        "found": len(records) > 0,
        "records": records,
        "truncated": truncated,
        "limit": SEARCH_LIMIT,
    })


# Terminate
# =================================================ADMIN: VIEW A USER'S PROFILE=================================================#
@dashboard_bp.route("/admin/profile/<token>")
@admin_access_required()
def admin_user_profile(token):
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u_id, name, email, role, profile_picture, created_at, is_suspended
                FROM users
                WHERE u_id = %s AND role IN ('customer', 'owner', 'mechanic')
            """,
                (u_id,),
            )
            person = cur.fetchone()
            if not person:
                abort(404)

            # Sub-admins may only view accounts inside their own domain.
            manager_type = session.get("admin_type")
            if (
                manager_type != "main"
                and DOMAIN_ROLE.get(manager_type) != person["role"]
            ):
                abort(403)

            details, workshops, bookings, jobs, jr_status = None, [], [], 0, None

            if person["role"] == "customer":
                cur.execute(
                    """
                    SELECT c.c_id, c.phone_no FROM customer c WHERE c.u_id = %s
                """,
                    (u_id,),
                )
                details = cur.fetchone()
                if details:
                    cur.execute(
                        """
                        SELECT b.b_id, b.requested_time, b.status,
                               w.name AS workshop_name, sc.s_name
                        FROM booking b
                        JOIN workshop w ON b.w_id = w.w_id
                        JOIN service s ON b.s_id = s.s_id
                        JOIN service_catalog sc ON sc.sc_id = s.sc_id
                        WHERE b.c_id = %s
                        ORDER BY b.requested_time DESC
                        LIMIT 15
                    """,
                        (details["c_id"],),
                    )
                    bookings = cur.fetchall()
                    cur.execute(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                               COUNT(*) FILTER (WHERE status = 'completed') AS completed
                        FROM booking WHERE c_id = %s
                    """,
                        (details["c_id"],),
                    )
                    jobs = cur.fetchone()

            elif person["role"] == "owner":
                cur.execute(
                    """
                    SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path, w.capacity,
                           w.status, w.rejection_reason,
                           (SELECT COUNT(*) FROM mechanic m WHERE m.w_id = w.w_id) AS team_size
                    FROM workshop w JOIN owner o ON w.o_id = o.o_id
                    WHERE o.u_id = %s
                    ORDER BY w.name
                """,
                    (u_id,),
                )
                workshops = cur.fetchall()
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

            else:  # mechanic (may not have joined a workshop yet)
                cur.execute(
                    """
                    SELECT m.experience_yrs, m.active_stat, w.w_id, w.name AS workshop_name,
                           w.address, w.photo_path
                    FROM mechanic m LEFT JOIN workshop w ON m.w_id = w.w_id
                    WHERE m.u_id = %s
                """,
                    (u_id,),
                )
                details = cur.fetchone()
                cur.execute(
                    """
                    SELECT 1 FROM join_request jr
                    JOIN mechanic m ON jr.m_id = m.m_id
                    WHERE m.u_id = %s AND jr.status = 'pending'
                    LIMIT 1
                """,
                    (u_id,),
                )
                jr_status = "pending" if cur.fetchone() else None
    finally:
        conn.close()

    return render_template(
        "dashboard/admin_user_profile.html",
        person=person,
        details=details,
        workshops=workshops,
        bookings=bookings,
        jobs=jobs,
        jr_status=jr_status,
    )

# =================================================ADMIN: VIEW A WORKSHOP=================================================#
@dashboard_bp.route("/admin/workshop/<token>")
@admin_access_required()
def admin_workshop_preview(token):
    # Customer managers have no business with workshops (see the team-profile description).
    if session.get("admin_type") == "customer_manager":
        abort(403)

    w_id = decode_wid(token)
    if w_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.w_id, w.name, w.address, w.contact_no, w.photo_path,
                       w.latitude, w.longitude, w.capacity, w.status, w.rejection_reason,
                       w.serves_cars, w.serves_two_wheelers,
                       u.name AS owner_name, u.u_id AS owner_uid,
                       u.email AS owner_email, u.profile_picture AS owner_picture,
                       u.created_at AS owner_since
                FROM workshop w
                JOIN owner o ON w.o_id = o.o_id
                JOIN users u ON o.u_id = u.u_id
                WHERE w.w_id = %s
            """,
                (w_id,),
            )
            workshop = cur.fetchone()
            if not workshop:
                abort(404)

            cur.execute(
                """
                SELECT sc.s_name, s.price_range, s.duration
                FROM service s
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE s.w_id = %s
                ORDER BY sc.s_name
            """,
                (w_id,),
            )
            services = cur.fetchall()

            cur.execute(
                """
                SELECT m.m_id, u.u_id, u.name, u.profile_picture, m.experience_yrs, m.active_stat
                FROM mechanic m
                JOIN users u ON m.u_id = u.u_id
                WHERE m.w_id = %s
                ORDER BY m.experience_yrs DESC NULLS LAST, u.name
            """,
                (w_id,),
            )
            team = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                       COUNT(*) FILTER (WHERE status = 'completed') AS completed
                FROM booking WHERE w_id = %s
            """,
                (w_id,),
            )
            jobs = cur.fetchone()

            cur.execute(
                """
                SELECT b.b_id, b.requested_time, b.status,
                       cu.name AS customer_name, sc.s_name
                FROM booking b
                JOIN customer c ON b.c_id = c.c_id
                JOIN users cu ON c.u_id = cu.u_id
                JOIN service s ON b.s_id = s.s_id
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                WHERE b.w_id = %s
                ORDER BY b.requested_time DESC
                LIMIT 10
            """,
                (w_id,),
            )
            recent_bookings = cur.fetchall()
    finally:
        conn.close()

    # which profiles this admin is allowed to open from the workshop page
    admin_type = session.get("admin_type")
    can_view_owner = admin_type in ("main", "owner_workshop_manager")
    can_view_mechanics = admin_type in ("main", "mechanic_manager")
    served_types = vehicles.workshop_types(workshop["serves_cars"], workshop["serves_two_wheelers"])

    return render_template(
        "dashboard/admin_workshop_preview.html",
        workshop=workshop,
        services=services,
        team=team,
        jobs=jobs,
        recent_bookings=recent_bookings,
        open_slots=workshop["capacity"] - len(team),
        can_view_owner=can_view_owner,
        can_view_mechanics=can_view_mechanics,
        served_types=served_types,
    )


# =================================================OWNER ACCOUNT REMOVAL=================================================#
# Removing an owner removes their workshop, so it runs as one controlled, ordered process:
#   1. impact check    - what will be lost (services, bookings, mechanics ...)
#   2. confirmation    - the admin must confirm explicitly when live data is affected
#   3. notifications   - customers with open bookings and the workshop's mechanics are told
#   4. ordered cleanup - children before parents, each step verified, all-or-nothing
def _owner_impact(cur, u_id):
    """What deleting this owner's account would affect. `workshop` is None if they have none."""
    cur.execute(
        """
        SELECT w.w_id, w.name, w.photo_path
        FROM workshop w JOIN owner o ON w.o_id = o.o_id
        WHERE o.u_id = %s
    """,
        (u_id,),
    )
    w = cur.fetchone()
    if not w:
        return {"workshop": None}

    w_id = w["w_id"]
    cur.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM service WHERE w_id = %(w)s)                          AS services,
          (SELECT COUNT(*) FROM mechanic WHERE w_id = %(w)s)                         AS mechanics,
          (SELECT COUNT(*) FROM join_request WHERE w_id = %(w)s AND status = 'pending') AS join_requests,
          (SELECT COUNT(*) FROM booking WHERE w_id = %(w)s)                          AS bookings,
          (SELECT COUNT(*) FROM booking WHERE w_id = %(w)s
                 AND status IN ('pending', 'confirmed', 'in_progress'))                              AS active_bookings,
          (SELECT COUNT(*) FROM payment p JOIN booking b ON p.b_id = b.b_id
                 WHERE b.w_id = %(w)s)                                               AS payments
    """,
        {"w": w_id},
    )
    counts = cur.fetchone()
    return {
        "workshop": {"w_id": w_id, "name": w["name"], "photo_path": w["photo_path"]},
        "services": counts["services"],
        "mechanics": counts["mechanics"],
        "join_requests": counts["join_requests"],
        "bookings": counts["bookings"],
        "active_bookings": counts["active_bookings"],
        "payments": counts["payments"],
    }


def _impact_summary(impact):
    """One readable sentence for the confirmation dialog."""
    def n(count, word):
        return f"{count} {word}{'' if count == 1 else 's'}"

    parts = [n(impact["services"], "service")]
    parts.append(n(impact["bookings"], "booking") + (
        f" ({impact['active_bookings']} still open)" if impact["active_bookings"] else ""))
    if impact["mechanics"]:
        parts.append(n(impact["mechanics"], "mechanic") + " (they will be unassigned, not deleted)")
    return (
        f'This owner runs the workshop "{impact["workshop"]["name"]}". Deleting the account also '
        f"permanently deletes the workshop with its {', '.join(parts)}. Customers with open bookings "
        "and the workshop's mechanics will be notified."
    )


def _notify(cur, user_ids, subject, body):
    """Best effort: a failed notification must never block the removal itself."""
    for uid in user_ids:
        cur.execute("SAVEPOINT notify")
        try:
            cur.execute(
                """
                INSERT INTO messages (sender_u_id, recipient_u_id, subject, body, sent_at, category)
                VALUES (NULL, %s, %s, %s, NOW(), 'update')
            """,
                (uid, subject, body),
            )
            cur.execute("RELEASE SAVEPOINT notify")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT notify")
            logging.exception("Could not notify user %s", uid)


def _remove_owner_workshop(cur, u_id, impact):
    """Ordered, verified cleanup of everything that hangs off the owner's workshop."""
    w = impact["workshop"]
    w_id, w_name = w["w_id"], w["name"]

    # --- notifications first (needs the rows that are about to disappear)
    cur.execute(
        """
        SELECT DISTINCT c.u_id FROM booking b JOIN customer c ON b.c_id = c.c_id
        WHERE b.w_id = %s AND b.status IN ('pending', 'confirmed', 'in_progress')
    """,
        (w_id,),
    )
    _notify(
        cur,
        [r["u_id"] for r in cur.fetchall()],
        "Your booking was cancelled",
        f'The workshop "{w_name}" is no longer available, so your open booking there was cancelled. '
        "Please book another workshop.",
    )
    cur.execute("SELECT u_id FROM mechanic WHERE w_id = %s", (w_id,))
    _notify(
        cur,
        [r["u_id"] for r in cur.fetchall()],
        "Your workshop was removed",
        f'The workshop "{w_name}" was removed from the platform. You are now unassigned and can '
        "apply to another workshop.",
    )

    # --- cleanup, children before parents
    cur.execute("DELETE FROM join_request WHERE w_id = %s", (w_id,))
    cur.execute(  # mechanics keep their accounts; they just become available again
        """
        UPDATE mechanic SET w_id = NULL, leave_requested_at = NULL, leave_reason = NULL
        WHERE w_id = %s
    """,
        (w_id,),
    )
    cur.execute("DELETE FROM payment WHERE b_id IN (SELECT b_id FROM booking WHERE w_id = %s)", (w_id,))
    cur.execute("DELETE FROM booking WHERE w_id = %s", (w_id,))
    cur.execute("DELETE FROM bookmark WHERE w_id = %s", (w_id,))
    cur.execute("DELETE FROM service WHERE w_id = %s", (w_id,))
    cur.execute("DELETE FROM workshop WHERE w_id = %s", (w_id,))
    if cur.rowcount != 1:
        # row-level security (or a concurrent change) hid the workshop: stop instead of half-deleting
        raise RuntimeError(f"workshop {w_id} could not be deleted (rowcount={cur.rowcount})")


def _delete_photo(photo_path):
    if not photo_path:
        return
    try:
        image_file = os.path.join(UPLOAD_FOLDER, os.path.basename(photo_path))
        if os.path.isfile(image_file):
            os.remove(image_file)
    except OSError:
        logging.exception("Account deleted, but the workshop image could not be removed.")


@dashboard_bp.route("/admin/terminate/<role>/<sealed(user):u_id>", methods=["POST"])
@admin_access_required("customer_manager", "owner_workshop_manager", "mechanic_manager")
def admin_terminate(role, u_id):
    if role not in ("customer", "owner", "mechanic"):
        if _wants_json():
            return jsonify({"ok": False, "error": "Invalid role."}), 400
        abort(404)

    # Managers may only remove accounts inside their assigned domain.
    manager_type = session.get("admin_type")
    if manager_type != "main" and DOMAIN_ROLE.get(manager_type) != role:
        if _wants_json():
            return jsonify({"ok": False, "error": "Forbidden."}), 403
        abort(403)

    photo_to_delete = None
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE u_id = %s", (u_id,))
            target = cur.fetchone()

            if not target:
                # Usually a stale page: the account was already deleted (second click, other tab).
                msg = "This account no longer exists - it was probably already deleted. Refresh the page."
                if _wants_json():
                    return jsonify({"ok": False, "gone": True, "error": msg}), 404
                flash(msg, "error")
                return redirect(url_for("dashboard.admin"))

            if target["role"] != role:
                actual = target["role"]
                if actual not in ("customer", "owner", "mechanic"):
                    msg = "This account is not a customer, owner or mechanic account and cannot be removed here."
                    if _wants_json():
                        return jsonify({"ok": False, "error": msg}), 403
                    abort(403)
                # The link said one role but the account is stored as another (inconsistent data).
                # Trust the database, apply the same permission rule to the real role, and carry on.
                logging.warning("Role mismatch on terminate: u_id=%s link=%s stored=%s", u_id, role, actual)
                if manager_type != "main" and DOMAIN_ROLE.get(manager_type) != actual:
                    if _wants_json():
                        return jsonify({"ok": False, "error": "Forbidden."}), 403
                    abort(403)
                role = actual

            # Payments are not removed by the booking cascade, so a customer who has paid
            # for anything could not be deleted (foreign-key error). Remove them first.
            if role == "customer":
                cur.execute("""
                    DELETE FROM payment WHERE b_id IN (
                        SELECT b.b_id FROM booking b
                        JOIN customer c ON b.c_id = c.c_id
                        WHERE c.u_id = %s
                    )
                """, (u_id,))

            if role == "owner":
                impact = _owner_impact(cur, u_id)
                if impact["workshop"]:
                    # Live data is affected: make the admin confirm it knowingly.
                    needs_confirm = impact["active_bookings"] or impact["mechanics"] or impact["bookings"]
                    confirmed = request.headers.get("X-Force-Delete") == "1" or request.form.get("force") == "1"
                    if needs_confirm and not confirmed:
                        if _wants_json():
                            return jsonify({"ok": False, "needs_confirm": True,
                                            "error": _impact_summary(impact)}), 409
                        flash(_impact_summary(impact) + " Open the owner's profile and confirm to continue.", "error")
                        return redirect(url_for("dashboard.admin"))
                    _remove_owner_workshop(cur, u_id, impact)
                    photo_to_delete = impact["workshop"]["photo_path"]
                cur.execute("DELETE FROM owner WHERE u_id = %s", (u_id,))

            cur.execute("DELETE FROM users WHERE u_id = %s", (u_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise  # a deliberate abort(403/404), not a database failure
    except Exception as exc:
        conn.rollback()
        logging.exception("Database error during account termination for u_id %s", u_id)
        # Nothing was changed (single transaction). Name the blocking constraint for the admin,
        # but never send the raw exception text to the browser.
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
        hint = f" (blocked by: {constraint})" if constraint else ""
        message = f"Could not delete the account{hint}. No changes were made."
        if _wants_json():
            return jsonify({"ok": False, "error": message}), 500
        flash(message, "error")
        return redirect(url_for("dashboard.admin"))
    finally:
        conn.close()

    _delete_photo(photo_to_delete)  # only after the commit succeeded

    if _wants_json():
        payload = {"ok": True, "message": "Account terminated."}
        # profile page: there is no table row to remove, so send the admin back to the dashboard
        if request.headers.get("X-After-Delete") == "redirect":
            flash("Account terminated.", "success")
            payload["redirect"] = url_for("dashboard.admin")
        return jsonify(payload)

    flash("Account terminated.", "success")
    return redirect(url_for("dashboard.admin"))


# =================================================BULK ACCOUNT REMOVAL=================================================#
BULK_LIMIT = 200  # accounts per request


def _clean_ids(raw):
    """Positive, de-duplicated integer ids from untrusted JSON, order preserved."""
    ids, seen = [], set()
    for value in raw if isinstance(raw, list) else []:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value in seen:
            continue
        seen.add(value)
        ids.append(value)
    return ids


def _constraint_hint(exc):
    constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
    return f" (blocked by: {constraint})" if constraint else ""


@dashboard_bp.route("/admin/terminate-bulk", methods=["POST"])
@admin_access_required("customer_manager", "owner_workshop_manager", "mechanic_manager")
def admin_terminate_bulk():
    """Delete many accounts of ONE role in a single request.

    Body (JSON): {"role": "customer|owner|mechanic", "ids": [u_id, ...], "force": false}
    Reply: {"ok": true, "deleted": [..], "gone": [..],
            "needs_confirm": [{"u_id", "summary"}], "skipped": [{"u_id", "reason"}],
            "failed": [{"u_id", "error"}]}

    * Customers and mechanics are removed with a few set-based statements (fast, all or nothing).
    * Owners are handled one by one, each in its own savepoint. An owner whose workshop holds live
      data (bookings / mechanics) is NOT deleted until the admin confirms with force=true, so one
      problem account never blocks the rest of the batch.
    """
    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    force = payload.get("force") is True
    ids = _clean_ids(payload.get("ids"))

    if role not in ("customer", "owner", "mechanic"):
        return jsonify({"ok": False, "error": "Invalid role."}), 400
    if not ids:
        return jsonify({"ok": False, "error": "Nothing selected."}), 400
    if len(ids) > BULK_LIMIT:
        return jsonify({"ok": False, "error": f"Select at most {BULK_LIMIT} accounts at a time."}), 400

    manager_type = session.get("admin_type")
    if manager_type != "main" and DOMAIN_ROLE.get(manager_type) != role:
        return jsonify({"ok": False, "error": "Forbidden."}), 403

    result = {"deleted": [], "gone": [], "needs_confirm": [], "skipped": [], "failed": []}
    photos = []

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. who is actually there, and under which role (one query for the whole batch)
            cur.execute("SELECT u_id, role FROM users WHERE u_id = ANY(%s)", (ids,))
            found = {r["u_id"]: r["role"] for r in cur.fetchall()}

            eligible = []
            for uid in ids:
                if uid not in found:
                    result["gone"].append(uid)  # already deleted (stale page)
                elif found[uid] != role:
                    result["skipped"].append({
                        "u_id": uid,
                        "reason": f"stored as a {found[uid]} account, not a {role}",
                    })
                else:
                    eligible.append(uid)

            # 2. remove them
            if eligible and role in ("customer", "mechanic"):
                cur.execute("SAVEPOINT bulk_fast")
                try:
                    if role == "customer":
                        cur.execute(
                            """
                            DELETE FROM payment WHERE b_id IN (
                                SELECT b.b_id FROM booking b
                                JOIN customer c ON b.c_id = c.c_id
                                WHERE c.u_id = ANY(%s))
                        """,
                            (eligible,),
                        )
                    cur.execute(
                        "DELETE FROM users WHERE u_id = ANY(%s) AND role = %s RETURNING u_id",
                        (eligible, role),
                    )
                    removed = {r["u_id"] for r in cur.fetchall()}
                    cur.execute("RELEASE SAVEPOINT bulk_fast")
                    result["deleted"] += [u for u in eligible if u in removed]
                    result["gone"] += [u for u in eligible if u not in removed]
                except Exception:
                    # One bad account must not sink the batch: undo, then go one by one.
                    cur.execute("ROLLBACK TO SAVEPOINT bulk_fast")
                    logging.exception("Bulk %s delete failed, retrying one by one", role)
                    for uid in eligible:
                        cur.execute("SAVEPOINT bulk_one")
                        try:
                            if role == "customer":
                                cur.execute(
                                    """
                                    DELETE FROM payment WHERE b_id IN (
                                        SELECT b.b_id FROM booking b
                                        JOIN customer c ON b.c_id = c.c_id
                                        WHERE c.u_id = %s)
                                """,
                                    (uid,),
                                )
                            cur.execute("DELETE FROM users WHERE u_id = %s AND role = %s", (uid, role))
                            cur.execute("RELEASE SAVEPOINT bulk_one")
                            result["deleted"].append(uid)
                        except Exception as exc:
                            cur.execute("ROLLBACK TO SAVEPOINT bulk_one")
                            logging.exception("Could not delete %s %s", role, uid)
                            result["failed"].append({
                                "u_id": uid,
                                "error": f"Could not delete{_constraint_hint(exc)}.",
                            })

            elif eligible and role == "owner":
                for uid in eligible:
                    cur.execute("SAVEPOINT bulk_owner")
                    try:
                        impact = _owner_impact(cur, uid)
                        workshop = impact["workshop"]
                        if workshop:
                            has_live_data = impact["active_bookings"] or impact["mechanics"] or impact["bookings"]
                            if has_live_data and not force:
                                cur.execute("RELEASE SAVEPOINT bulk_owner")
                                result["needs_confirm"].append({
                                    "u_id": uid,
                                    "summary": _impact_summary(impact),
                                    "workshop": workshop["name"],
                                    "services": impact["services"],
                                    "bookings": impact["bookings"],
                                    "active_bookings": impact["active_bookings"],
                                    "mechanics": impact["mechanics"],
                                })
                                continue
                            _remove_owner_workshop(cur, uid, impact)
                            photos.append(workshop["photo_path"])
                        cur.execute("DELETE FROM owner WHERE u_id = %s", (uid,))
                        cur.execute("DELETE FROM users WHERE u_id = %s AND role = 'owner'", (uid,))
                        cur.execute("RELEASE SAVEPOINT bulk_owner")
                        result["deleted"].append(uid)
                    except Exception as exc:
                        cur.execute("ROLLBACK TO SAVEPOINT bulk_owner")
                        logging.exception("Could not delete owner %s", uid)
                        result["failed"].append({
                            "u_id": uid,
                            "error": f"Could not delete{_constraint_hint(exc)}. Nothing was changed for this owner.",
                        })
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Bulk account removal failed")
        return jsonify({"ok": False, "error": "Could not complete the deletion. No changes were made."}), 500
    finally:
        conn.close()

    for photo in photos:  # only after the commit succeeded
        _delete_photo(photo)

    return jsonify({"ok": True, **result})


# feedback
@dashboard_bp.route("/admin/feedback/<sealed(feedback):f_id>/read", methods=["POST"])
@admin_access_required(main_only=True)
def mark_feedback_read(f_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE feedback SET is_read = TRUE WHERE f_id = %s", (f_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("dashboard.admin"))


@dashboard_bp.route("/admin/user/<sealed(user):u_id>/suspension/<action>", methods=["POST"])
@admin_access_required()
def set_user_suspension(u_id, action):
    if action not in ("suspend", "restore"):
        if _wants_json():
            return jsonify({"ok": False, "error": "Invalid action."}), 400
        abort(400)

    is_suspended = (action == "suspend")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE u_id = %s", (u_id,))
            target = cur.fetchone()
            if not target:
                if _wants_json():
                    return jsonify({"ok": False, "error": "User not found."}), 404
                abort(404)

            # Admin accounts are managed under Sub-admin Management. Suspending one here would
            # let an admin lock themselves (or the main admin) out of the platform.
            if target["role"] not in ("customer", "owner", "mechanic"):
                if _wants_json():
                    return jsonify({"ok": False, "error": "Admin accounts cannot be suspended here."}), 403
                abort(403)

            # Check manager permissions
            manager_type = session.get("admin_type")
            if manager_type != "main" and DOMAIN_ROLE.get(manager_type) != target["role"]:
                if _wants_json():
                    return jsonify({"ok": False, "error": "Forbidden."}), 403
                abort(403)

            # keep who suspended the account and when: an appeal goes to someone else if the main admin did it
            cur.execute(
                "UPDATE users SET is_suspended = %s, suspended_by = %s, suspended_at = %s WHERE u_id = %s",
                (is_suspended, session["user_id"] if is_suspended else None,
                 datetime.now() if is_suspended else None, u_id),
            )
            conn.commit()
    except HTTPException:
        conn.rollback()
        raise  # a deliberate abort(403/404), not a database failure
    except Exception:
        conn.rollback()
        logging.exception("Database error during user suspension update for u_id %s", u_id)
        if _wants_json():
            return jsonify({"ok": False, "error": "Could not update the account. Please try again."}), 500
        raise
    finally:
        conn.close()

    if _wants_json():
        return jsonify({"ok": True, "is_suspended": is_suspended})

    flash(f"Account successfully {'suspended' if is_suspended else 'restored'}.", "success")
    return _back()



# =================================================ADMIN: BOOKINGS OVERSIGHT =================================================#
@dashboard_bp.route("/admin/bookings")
@admin_access_required(main_only=True)
def admin_bookings():
    # optional ?workshop=<w_id> (the workshop page links here)
    workshop_id = request.args.get("workshop", type=int)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT b.b_id, b.requested_time, b.status, b.amount,
                       w.name AS workshop_name, w.w_id,
                       cu.name AS customer_name, cu.email AS customer_email,
                       sc.s_name, s.price_range,
                       mu.name AS mechanic_name,
                       p.amount AS paid_amount, p.method AS paid_method, p.paid_at
                FROM booking b
                JOIN workshop w ON b.w_id = w.w_id
                JOIN customer c ON b.c_id = c.c_id
                JOIN users cu ON c.u_id = cu.u_id
                JOIN service s ON b.s_id = s.s_id
                JOIN service_catalog sc ON sc.sc_id = s.sc_id
                LEFT JOIN mechanic bm ON b.assigned_m_id = bm.m_id
                LEFT JOIN users mu ON bm.u_id = mu.u_id
                LEFT JOIN payment p ON p.b_id = b.b_id
                WHERE (%s::int IS NULL OR b.w_id = %s::int)
                ORDER BY b.requested_time DESC
            """, (workshop_id, workshop_id))
            bookings = cur.fetchall()
    finally:
        conn.close()

    return render_template(
        "dashboard/admin_bookings.html",
        bookings=bookings,
        workshop_filter=bookings[0]["workshop_name"] if (workshop_id and bookings) else None,
        workshop_filter_id=workshop_id,
    )


@dashboard_bp.route("/admin/bookings/<sealed(booking):b_id>/cancel", methods=["POST"])
@admin_access_required(main_only=True)
def admin_cancel_booking(b_id):
    """Cancel a pending or confirmed booking (same transitions the workshop owner has)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE booking SET status = 'cancelled'
                WHERE b_id = %s AND status IN ('pending', 'confirmed', 'in_progress')
            """,
                (b_id,),
            )
            changed = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Could not cancel booking %s", b_id)
        changed = 0
    finally:
        conn.close()

    if changed:
        flash(f"Booking #{b_id} cancelled.", "success")
    else:
        flash("That booking cannot be cancelled (it is already completed or cancelled).", "error")
    return _back("dashboard.admin_bookings")


# =================================================SERVICE CATALOG=================================================#
# The catalog is split in two: a car catalog and a two-wheeler catalog (spec section 5). A service name
# only has to be unique within its own catalog, so "Tyres" can exist in both.
def _clean_service_name(raw):
    """Collapse extra spaces so ' Brake   Repair ' becomes 'Brake Repair'."""
    return " ".join((raw or "").split())


def _catalog_label(vehicle_type):
    return f"{vehicles.SINGULAR_LABELS[vehicle_type].lower()} catalog"


@dashboard_bp.route("/admin/services", methods=["GET", "POST"])
@admin_access_required(main_only=True)
def admin_services():
    # which catalog the page shows: ?type=car|two_wheeler (cars when missing or unrecognised)
    catalog_type = vehicles.normalize(request.args.get("type")) or vehicles.CAR

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if request.method == "POST":
                s_name = _clean_service_name(request.form.get("s_name"))
                vehicle_type = vehicles.normalize(request.form.get("vehicle_type"))
                if vehicle_type is None:
                    flash("Please choose which catalog this service belongs to: four-wheelers or two-wheelers.", "error")
                elif not s_name:
                    flash("Please enter a service name.", "error")
                elif len(s_name) > 100:
                    flash("Service names can be at most 100 characters.", "error")
                else:
                    # the UNIQUE constraint is case-sensitive, so check "tires" vs "Tires" ourselves
                    # (within this catalog only: the other catalog may use the same name)
                    cur.execute(
                        "SELECT 1 FROM service_catalog WHERE LOWER(s_name) = LOWER(%s) AND vehicle_type = %s",
                        (s_name, vehicle_type),
                    )
                    if cur.fetchone():
                        flash(f'"{s_name}" is already in the {_catalog_label(vehicle_type)}.', "error")
                    else:
                        try:
                            cur.execute(
                                "INSERT INTO service_catalog (s_name, vehicle_type) VALUES (%s, %s)",
                                (s_name, vehicle_type),
                            )
                            conn.commit()
                            clear_catalog_cache()
                            flash(
                                f'"{s_name}" added to the {_catalog_label(vehicle_type)}.',
                                "success",
                            )
                        except Exception:
                            conn.rollback()
                            logging.exception("Could not add catalog service")
                            flash("Could not add that service.", "error")
                return redirect(url_for("dashboard.admin_services", type=vehicle_type or catalog_type))

            cur.execute(
                """
                SELECT sc.sc_id, sc.s_name,
                       COUNT(DISTINCT s.s_id) AS workshop_count,
                       COUNT(b.b_id)          AS booking_count
                FROM service_catalog sc
                LEFT JOIN service s ON s.sc_id = sc.sc_id
                LEFT JOIN booking b ON b.s_id = s.s_id
                WHERE sc.vehicle_type = %s
                GROUP BY sc.sc_id, sc.s_name
                ORDER BY sc.s_name
            """,
                (catalog_type,),
            )
            catalog = cur.fetchall()

            cur.execute("SELECT vehicle_type, COUNT(*) AS n FROM service_catalog GROUP BY vehicle_type")
            catalog_counts = dict.fromkeys(vehicles.VEHICLE_TYPES, 0)
            for r in cur.fetchall():
                if r["vehicle_type"] in catalog_counts:
                    catalog_counts[r["vehicle_type"]] = r["n"]
    finally:
        conn.close()

    in_use = sum(1 for c in catalog if c["workshop_count"] > 0)
    stats = {"total": len(catalog), "in_use": in_use, "unused": len(catalog) - in_use}
    return render_template(
        "dashboard/admin_service.html",
        catalog=catalog,
        stats=stats,
        catalog_type=catalog_type,
        catalog_counts=catalog_counts,
    )


@dashboard_bp.route("/admin/services/<sealed(catalog):sc_id>/rename", methods=["POST"])
@admin_access_required(main_only=True)
def rename_catalog_service(sc_id):
    new_name = _clean_service_name(request.form.get("s_name"))
    vehicle_type = None

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s_name, vehicle_type FROM service_catalog WHERE sc_id = %s", (sc_id,)
            )
            row = cur.fetchone()
            if not row:
                abort(404)
            vehicle_type = row["vehicle_type"]

            if not new_name:
                flash("Please enter a service name.", "error")
            elif len(new_name) > 100:
                flash("Service names can be at most 100 characters.", "error")
            elif new_name == row["s_name"]:
                pass  # nothing changed
            else:
                # names only have to be unique inside the same catalog
                cur.execute(
                    "SELECT 1 FROM service_catalog "
                    "WHERE LOWER(s_name) = LOWER(%s) AND sc_id <> %s AND vehicle_type = %s",
                    (new_name, sc_id, vehicle_type),
                )
                if cur.fetchone():
                    flash(f"Another service in the {_catalog_label(vehicle_type)} already has that name.", "error")
                else:
                    try:
                        cur.execute(
                            "UPDATE service_catalog SET s_name = %s WHERE sc_id = %s",
                            (new_name, sc_id),
                        )
                        conn.commit()
                        clear_catalog_cache()
                        flash(f'Renamed to "{new_name}".', "success")
                    except Exception:
                        conn.rollback()
                        logging.exception("Could not rename catalog service")
                        flash("Could not rename that service.", "error")
    finally:
        conn.close()
    return redirect(url_for("dashboard.admin_services", type=vehicle_type))


@dashboard_bp.route("/admin/services/<sealed(catalog):sc_id>/delete", methods=["POST"])
@admin_access_required(main_only=True)
def delete_catalog_service(sc_id):
    ok, message, vehicle_type = False, "", None
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s_name, vehicle_type,
                (SELECT COUNT(*) FROM service WHERE sc_id = %s) AS in_use
                FROM service_catalog WHERE sc_id = %s
            """,
                (sc_id, sc_id),
            )
            row = cur.fetchone()
            if not row:
                message = "That service no longer exists."
            else:
                vehicle_type = row["vehicle_type"]
                if row["in_use"]:
                    n = row["in_use"]
                    message = (
                        f'"{row["s_name"]}" is offered by {n} workshop{"" if n == 1 else "s"}, '
                        "so it can't be removed."
                    )
                else:
                    try:
                        cur.execute("DELETE FROM service_catalog WHERE sc_id = %s", (sc_id,))
                        conn.commit()
                        clear_catalog_cache()
                        ok, message = True, f'"{row["s_name"]}" removed from the {_catalog_label(vehicle_type)}.'
                    except Exception:
                        conn.rollback()
                        logging.exception("Could not delete catalog service")
                        message = "Could not remove that service."
    finally:
        conn.close()

    # admin.js sends this with fetch() and expects JSON; a plain form post gets a flash + redirect
    if _wants_json():
        if ok:
            return jsonify({"ok": True, "message": message})
        return jsonify({"ok": False, "error": message}), 409
    flash(message, "success" if ok else "error")
    return redirect(url_for("dashboard.admin_services", type=vehicle_type))


# =================================================SUB-ADMIN MANAGEMENT=================================================#
@dashboard_bp.route("/admin/subadmins", methods=["GET", "POST"])
@admin_access_required(main_only=True)
def admin_subadmins():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if request.method == "POST":
                name = request.form.get("name", "").strip()
                email = request.form.get("email", "").strip().lower()
                password = request.form.get("password", "")
                confirm_password = request.form.get("confirm_password", "")
                admin_type = request.form.get("admin_type", "")
                valid_types = (
                    "customer_manager",
                    "owner_workshop_manager",
                    "mechanic_manager",
                )

                if not name or not email or len(password) < 8:
                    flash(
                        "Enter a name, email, and password of at least 8 characters.",
                        "error",
                    )
                elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                    flash("Enter a valid email address.", "error")
                elif password != confirm_password:
                    flash("Passwords do not match.", "error")
                elif admin_type not in valid_types:
                    flash("Choose a valid sub-admin type.", "error")
                else:
                    try:
                        cur.execute(
                            "INSERT INTO users (name, email, password, role, created_at) VALUES (%s, %s, %s, 'admin', NOW()) RETURNING u_id",
                            (name, email, generate_password_hash(password)),
                        )
                        new_uid = cur.fetchone()["u_id"]
                        cur.execute(
                            "INSERT INTO admin (u_id, admin_type, is_active) VALUES (%s, %s, TRUE)",
                            (new_uid, admin_type),
                        )
                        conn.commit()
                        flash("Sub-admin created successfully.", "success")
                        return redirect(url_for("dashboard.admin_subadmins"))
                    except Exception:
                        conn.rollback()
                        logging.exception("Could not create sub-admin")
                        flash(
                            "Could not create account. Check whether the email is already registered.",
                            "error",
                        )

            cur.execute("""
                SELECT a.a_id, a.u_id, a.admin_type, a.is_active,
                u.name, u.email, u.created_at, u.profile_picture
                FROM admin a JOIN users u ON a.u_id = u.u_id
                ORDER BY (a.admin_type = 'main') DESC, u.created_at DESC
            """)
            subadmins = cur.fetchall()
    finally:
        conn.close()
    return render_template("dashboard/subadmins.html", subadmins=subadmins)


@dashboard_bp.route("/admin/subadmins/profile/<token>")
@admin_access_required(main_only=True)
def admin_team_profile(token):
    u_id = decode_uid(token)
    if u_id is None:
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.a_id, a.admin_type, a.is_active,
                u.u_id, u.name, u.email, u.profile_picture, u.created_at
                FROM admin a JOIN users u ON a.u_id = u.u_id
                WHERE u.u_id = %s
            """,
                (u_id,),
            )
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

    return render_template(
        "dashboard/admin_team_profile.html", member=member, scope=scope
    )


@dashboard_bp.route("/admin/subadmins/<sealed(subadmin):a_id>/toggle", methods=["POST"])
@admin_access_required(main_only=True)
def toggle_subadmin(a_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT u_id, admin_type, is_active FROM admin WHERE a_id = %s", (a_id,)
            )
            target = cur.fetchone()
            if not target:
                abort(404)
            if target["admin_type"] == "main" or target["u_id"] == session["user_id"]:
                flash("The main admin account cannot be deactivated here.", "error")
            else:
                cur.execute(
                    "UPDATE admin SET is_active = NOT is_active WHERE a_id = %s",
                    (a_id,),
                )
                conn.commit()
                flash("Sub-admin status updated.", "success")
    finally:
        conn.close()
    return redirect(url_for("dashboard.admin_subadmins"))


# =================================================WORKSHOP APPROVALS=================================================#
# New workshops start as 'pending' and stay hidden from customers until approved here.
# Main admin and the owner/workshop manager may decide; other sub-admins get a 403.
# Every decision is recorded (who, when) and tells the owner in their inbox. The decision and the
# notice are saved in ONE transaction: if the notice cannot be written, the decision is rolled back,
# so an owner is never left without an answer.
REJECTION_REASON_MIN = 10  # a one-word reason does not tell the owner what to fix
REJECTION_REASON_MAX = 300


def _notice_name(name):
    """Workshop names go in a 150-character subject line, so keep them short there."""
    name = name or "your workshop"
    return name if len(name) <= 90 else name[:87] + "..."


def _send_owner_notice(cur, owner_u_id, subject, body, ref=None):
    """A plain system notice (no sender) in the owner's inbox. Raises on failure (not best effort).

    ``ref`` = (ref_type, ref_id) links the notice to something the owner can act on; a rejection
    notice carries ('listing_appeal', w_id) so its popup shows the Appeal button."""
    ref_type, ref_id = ref if ref else (None, None)
    cur.execute(
        """
        INSERT INTO messages (sender_u_id, recipient_u_id, subject, body, sent_at, category, ref_type, ref_id)
        VALUES (NULL, %s, %s, %s, NOW(), 'update', %s, %s)
    """,
        (owner_u_id, subject[:150], body[:2000], ref_type, ref_id),
    )


@dashboard_bp.route("/admin/workshop/<sealed(workshop):w_id>/approve", methods=["POST"])
@admin_access_required("owner_workshop_manager")
def approve_workshop(w_id):
    failed = False
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workshop w
                SET status = 'approved', rejection_reason = NULL,
                    decided_by = %s, decided_at = NOW()
                FROM owner o
                WHERE w.o_id = o.o_id AND w.w_id = %s AND w.status = 'pending'
                RETURNING w.name, o.u_id AS owner_u_id
            """,
                (session["user_id"], w_id),
            )
            row = cur.fetchone()
            if row:
                _send_owner_notice(
                    cur,
                    row["owner_u_id"],
                    f'Your workshop "{_notice_name(row["name"])}" was approved',
                    f'Good news: "{row["name"]}" has been approved. It is now visible to customers '
                    "and mechanics, and customers can find it in search and send you booking requests.",
                )
        conn.commit()
        clear_catalog_cache()  # service counts only include approved workshops
    except Exception:
        conn.rollback()
        logging.exception("Could not approve workshop %s", w_id)
        row, failed = None, True
        flash("Could not approve that workshop. Please try again.", "error")
    finally:
        conn.close()

    if row:
        flash(f'"{row["name"]}" approved. It is now visible to customers, and the owner has been told.', "success")
    elif not failed:
        flash("That workshop is not waiting for approval.", "error")
    return _back("dashboard.admin", "#all-approvals")


@dashboard_bp.route("/admin/workshop/<sealed(workshop):w_id>/reject", methods=["POST"])
@admin_access_required("owner_workshop_manager")
def reject_workshop(w_id):
    # A reason is required: the owner needs to know what to fix before they resubmit.
    reason = " ".join((request.form.get("reason") or "").split())
    if len(reason) < REJECTION_REASON_MIN:
        flash(
            f"Please give the owner a reason for rejecting their workshop (at least {REJECTION_REASON_MIN} characters).",
            "error",
        )
        return _back("dashboard.admin", "#all-approvals")
    if len(reason) > REJECTION_REASON_MAX:
        flash(f"Please keep the reason under {REJECTION_REASON_MAX} characters.", "error")
        return _back("dashboard.admin", "#all-approvals")

    failed = False
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workshop w
                SET status = 'rejected', rejection_reason = %s,
                    decided_by = %s, decided_at = NOW()
                FROM owner o
                WHERE w.o_id = o.o_id AND w.w_id = %s AND w.status = 'pending'
                RETURNING w.name, o.u_id AS owner_u_id
            """,
                (reason, session["user_id"], w_id),
            )
            row = cur.fetchone()
            if row:
                _send_owner_notice(
                    cur,
                    row["owner_u_id"],
                    f'Your workshop "{_notice_name(row["name"])}" was not approved',
                    f'Your workshop "{row["name"]}" was not approved.\n\nReason: {reason}\n\n'
                    "To fix this, open your dashboard, update your workshop details and save. "
                    "Saving sends it back for review. If you think this decision is wrong, "
                    "you can appeal it instead.",
                    ref=("listing_appeal", w_id),
                )
        conn.commit()
        clear_catalog_cache()
    except Exception:
        conn.rollback()
        logging.exception("Could not reject workshop %s", w_id)
        row, failed = None, True
        flash("Could not reject that workshop. Please try again.", "error")
    finally:
        conn.close()

    if row:
        flash(f'"{row["name"]}" rejected. The owner has been told why and can fix the details and resubmit.', "success")
    elif not failed:
        flash("That workshop is not waiting for approval.", "error")
    return _back("dashboard.admin", "#all-approvals")


# =================================================MECHANIC JOIN REQUESTS=================================================#
# Main admin and the mechanic manager can accept or reject a mechanic's request to join a workshop
# (the workshop owner can do the same from their inbox).
@dashboard_bp.route("/admin/join_request/<sealed(joinreq):jr_id>/<action>", methods=["POST"])
@admin_access_required("mechanic_manager")
def admin_review_join_request(jr_id, action):
    if action not in ("accept", "reject"):
        abort(404)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT jr.m_id, jr.w_id, w.capacity
                FROM join_request jr
                JOIN workshop w ON jr.w_id = w.w_id
                WHERE jr.jr_id = %s AND jr.status = 'pending'
            """,
                (jr_id,),
            )
            req = cur.fetchone()

            if not req:
                flash("That request was not found or has already been handled.", "error")
            elif action == "reject":
                cur.execute(
                    "UPDATE join_request SET status = 'rejected' WHERE jr_id = %s", (jr_id,)
                )
                flash("Request rejected.", "success")
            else:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM mechanic WHERE w_id = %s", (req["w_id"],)
                )
                if cur.fetchone()["n"] >= req["capacity"]:
                    flash(
                        "That workshop is full. Its owner must increase the capacity "
                        "before more mechanics can join.",
                        "error",
                    )
                else:
                    cur.execute(
                        "UPDATE mechanic SET w_id = %s WHERE m_id = %s AND w_id IS NULL",
                        (req["w_id"], req["m_id"]),
                    )
                    if cur.rowcount:
                        cur.execute(
                            "UPDATE join_request SET status = 'accepted' WHERE jr_id = %s",
                            (jr_id,),
                        )
                        # the mechanic now has a workshop, so their other open requests are void
                        cur.execute(
                            "UPDATE join_request SET status = 'rejected' "
                            "WHERE m_id = %s AND status = 'pending'",
                            (req["m_id"],),
                        )
                        flash("Mechanic added to the workshop.", "success")
                    else:
                        cur.execute(
                            "UPDATE join_request SET status = 'rejected' WHERE jr_id = %s",
                            (jr_id,),
                        )
                        flash("That mechanic already joined another workshop.", "error")
        conn.commit()
    except Exception:
        conn.rollback()
        logging.exception("Could not review join request %s", jr_id)
        flash("Could not update that request. Please try again.", "error")
    finally:
        conn.close()
    return _back("dashboard.admin", "#joinrequests")


# =================================================SUB-ADMIN ACCOUNT CONTROLS=================================================#
def _load_subadmin(cur, a_id):
    """-> the sub-admin row (404 if missing). Returns None, after flashing, for the main admin
    or the signed-in admin themselves, who cannot be changed from these controls."""
    cur.execute(
        "SELECT a_id, u_id, admin_type FROM admin WHERE a_id = %s", (a_id,)
    )
    target = cur.fetchone()
    if not target:
        abort(404)
    if target["admin_type"] == "main" or target["u_id"] == session["user_id"]:
        flash("The main admin account cannot be changed from here.", "error")
        return None
    return target


@dashboard_bp.route("/admin/subadmins/<sealed(subadmin):a_id>/role", methods=["POST"])
@admin_access_required(main_only=True)
def subadmin_change_role(a_id):
    new_type = request.form.get("admin_type", "")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            target = _load_subadmin(cur, a_id)
            if target is None:
                return redirect(url_for("dashboard.admin_subadmins"))
            if new_type not in SUBADMIN_TYPES:
                flash("Choose a valid sub-admin type.", "error")
            else:
                cur.execute(
                    "UPDATE admin SET admin_type = %s WHERE a_id = %s", (new_type, a_id)
                )
                conn.commit()
                flash("Role updated. It applies on their next action.", "success")
            token = encode_uid(target["u_id"])
    finally:
        conn.close()
    return redirect(url_for("dashboard.admin_team_profile", token=token))


@dashboard_bp.route("/admin/subadmins/<sealed(subadmin):a_id>/password", methods=["POST"])
@admin_access_required(main_only=True)
def subadmin_reset_password(a_id):
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            target = _load_subadmin(cur, a_id)
            if target is None:
                return redirect(url_for("dashboard.admin_subadmins"))
            if len(password) < 8:
                flash("The new password must be at least 8 characters.", "error")
            elif password != confirm:
                flash("Passwords do not match.", "error")
            else:
                cur.execute(
                    "UPDATE users SET password = %s, password_set = TRUE WHERE u_id = %s",
                    (generate_password_hash(password), target["u_id"]),
                )
                conn.commit()
                flash("Password updated.", "success")
            token = encode_uid(target["u_id"])
    finally:
        conn.close()
    return redirect(url_for("dashboard.admin_team_profile", token=token))


@dashboard_bp.route("/admin/subadmins/<sealed(subadmin):a_id>/delete", methods=["POST"])
@admin_access_required(main_only=True)
def delete_subadmin(a_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            target = _load_subadmin(cur, a_id)
            if target is None:
                return redirect(url_for("dashboard.admin_subadmins"))
            # the admin row goes with the user (ON DELETE CASCADE); customers/owners they
            # registered keep their records (their admin link is set to NULL)
            cur.execute("DELETE FROM users WHERE u_id = %s", (target["u_id"],))
        conn.commit()
        flash("Sub-admin removed.", "success")
    except HTTPException:
        conn.rollback()
        raise  # a deliberate abort(403/404), not a database failure
    except Exception:
        conn.rollback()
        logging.exception("Could not delete sub-admin %s", a_id)
        flash("Could not remove that sub-admin.", "error")
    finally:
        conn.close()
    return redirect(url_for("dashboard.admin_subadmins"))
