import logging
import os

from flask import (
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db_connection
from app.routes.dashboard import dashboard_bp
from app.utils import login_required, save_upload_image


# delete the logged-in user's own account (the profile page asks for the password first)
@dashboard_bp.route("/profile/delete-account", methods=["POST"])
@login_required
def delete_account():
    password = request.form.get("password", "")

    # Admin accounts are managed from the admin panel; deleting one here could lock everyone out.
    if session.get("role") == "admin":
        flash("Admin accounts cannot be deleted from here.", "error")
        return redirect(url_for("dashboard.profile"))

    conn = get_db_connection()
    cur = conn.cursor()
    files_to_remove = []

    try:
        cur.execute(
            "SELECT password, password_set, profile_picture FROM users WHERE u_id = %s",
            (session["user_id"],),
        )
        user = cur.fetchone()

        if not user:
            flash("User account not found.", "error")
            return redirect(url_for("dashboard.profile"))

        if user["password_set"]:
            if not password:
                flash("Please enter your password to delete your account.", "error")
                return redirect(url_for("dashboard.profile"))
            if not check_password_hash(user["password"], password):
                flash("Incorrect password. Your account was not deleted.", "error")
                return redirect(url_for("dashboard.profile"))
        else:
            # signed up with Google, so there is no password to ask for: they type DELETE instead
            if request.form.get("confirm_text", "").strip().upper() != "DELETE":
                flash("Type DELETE to confirm. Your account was not deleted.", "error")
                return redirect(url_for("dashboard.profile"))

        # Don't silently wipe out bookings that people are still counting on.
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM booking b
               JOIN customer c ON b.c_id = c.c_id
               WHERE c.u_id = %(u)s AND b.status IN ('pending', 'confirmed', 'in_progress')) AS as_customer,
              (SELECT COUNT(*) FROM booking b
               JOIN workshop w ON b.w_id = w.w_id
               JOIN owner o ON w.o_id = o.o_id
               WHERE o.u_id = %(u)s AND b.status IN ('pending', 'confirmed', 'in_progress')) AS as_owner
        """,
            {"u": session["user_id"]},
        )
        active = cur.fetchone()

        if active["as_customer"]:
            flash(
                "You still have pending or confirmed bookings. Cancel them or wait until "
                "they are completed before deleting your account.",
                "error",
            )
            return redirect(url_for("dashboard.profile"))
        if active["as_owner"]:
            flash(
                "Your workshop still has pending or confirmed bookings. Complete or cancel "
                "them before deleting your account.",
                "error",
            )
            return redirect(url_for("dashboard.profile"))

        # Remember the uploaded images so the files can be removed once the account is gone.
        if user["profile_picture"]:
            files_to_remove.append(user["profile_picture"])
        cur.execute(
            """
            SELECT w.photo_path FROM workshop w
            JOIN owner o ON w.o_id = o.o_id
            WHERE o.u_id = %s
        """,
            (session["user_id"],),
        )
        workshop = cur.fetchone()
        if workshop and workshop["photo_path"]:
            files_to_remove.append(workshop["photo_path"])

        # Role rows, the workshop, services, join requests etc. are removed by ON DELETE CASCADE.
        cur.execute("DELETE FROM users WHERE u_id = %s", (session["user_id"],))
        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Error deleting account")
        flash("Something went wrong while deleting your account.", "error")
        return redirect(url_for("dashboard.profile"))

    finally:
        cur.close()
        conn.close()

    # Best-effort clean-up of the image files (the account is already deleted at this point).
    for relative_path in files_to_remove:
        if not relative_path.startswith("uploads/"):
            continue
        try:
            file_path = os.path.join("app", "static", relative_path)
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            logging.exception("Could not remove %s", relative_path)

    session.clear()
    flash("Your account has been deleted.", "success")
    return redirect(url_for("main.index"))

# =============================================================PROFILE========================================================#
@dashboard_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT u_id, name, email, role, created_at, profile_picture, password_set
        FROM users WHERE u_id = %s
        """,
        (session["user_id"],),
    )
    user = cur.fetchone()

    cur.execute(" SELECT admin_type from admin where u_id = %s", (session["user_id"],),)
    admin_info = cur.fetchone()

    role_info = {}
    if user["role"] == "customer":
        cur.execute(
            "SELECT phone_no FROM customer WHERE u_id = %s", (session["user_id"],)
        )
        role_info = cur.fetchone()
    elif user["role"] == "mechanic":
        cur.execute(
            """
            SELECT m.experience_yrs, w.name AS workshop_name
            FROM mechanic m LEFT JOIN workshop w ON m.w_id = w.w_id
            WHERE m.u_id = %s
        """,
            (session["user_id"],),
        )
        role_info = cur.fetchone()
    elif user["role"] == "owner":
        cur.execute(
            "SELECT name FROM workshop WHERE o_id = (SELECT o_id FROM owner WHERE u_id = %s)",
            (session["user_id"],),
        )
        role_info = cur.fetchone()

    if request.method == "POST":
        name = request.form["name"]
        cur.execute(
            "UPDATE users SET name = %s WHERE u_id = %s", (name, session["user_id"])
        )

        if user["role"] == "customer":
            phone_number = request.form.get("phone_no")
            cur.execute(
                "UPDATE customer SET phone_no = %s WHERE u_id = %s",
                (phone_number, session["user_id"]),
            )

        conn.commit()
        session["user_name"] = name
        flash("Profile updated.", "success")
        cur.close()
        conn.close()
        return redirect(url_for("dashboard.profile"))

    cur.close()
    conn.close()

    return render_template("dashboard/profile.html", user=user, role_info=role_info, admin_info=admin_info)


@dashboard_bp.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("old_pass", "")
    new_password = request.form.get("new_pass", "")
    confirm_password = request.form.get("confirm_pass", "")

    # Basic validation (the current password is checked below, only for accounts that have one)
    if not new_password or not confirm_password:
        flash("Please fill in all password fields.", "error")
        return redirect(url_for("dashboard.profile"))

    if new_password != confirm_password:
        flash("New passwords do not match.", "error")
        return redirect(url_for("dashboard.profile"))

    if len(new_password) < 8:
        flash("New password must be at least 8 characters long.", "error")
        return redirect(url_for("dashboard.profile"))

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Get the current password hash
        cur.execute("SELECT name, email, password, password_set FROM users WHERE u_id = %s", (session["user_id"],))
        user = cur.fetchone()

        if not user:
            flash("User account not found.", "error")
            return redirect(url_for("dashboard.profile"))

        # Accounts created with Google have no password yet, so there is no current one to check.
        if user["password_set"]:
            if not current_password:
                flash("Please fill in all password fields.", "error")
                return redirect(url_for("dashboard.profile"))

            # Check current password
            if not check_password_hash(user["password"], current_password):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("dashboard.profile"))

            # Prevent using the same password
            if check_password_hash(user["password"], new_password):
                flash("New password must be different from your current password.", "error")
                return redirect(url_for("dashboard.profile"))

        # Hash the new password using the same method as signup
        new_password_hash = generate_password_hash(new_password)

        cur.execute(
            "UPDATE users SET password = %s, password_set = TRUE WHERE u_id = %s",
            (new_password_hash, session["user_id"]),
        )

        conn.commit()

        if user["password_set"]:
            flash("Password changed successfully.", "success")
        else:
            flash("Password set. You can now also log in with your email and password.", "success")

    except Exception:
        conn.rollback()
        logging.exception("Error changing password")
        flash("Something went wrong while changing your password.", "error")

    finally:
        cur.close()
        conn.close()

    return redirect(url_for("dashboard.profile"))


# upload profile picture
@dashboard_bp.route("/profile/upload-picture", methods=["POST"])
@login_required
def upload_profile_picture():
    conn = get_db_connection()
    cur = conn.cursor()

    photo = request.files.get("photo")

    profile_upload_folder = os.path.join("app", "static", "uploads", "profiles")
    filename = save_upload_image(photo, profile_upload_folder, f"profile_{session['user_id']}")

    if filename:
        profile_picture_path = f"uploads/profiles/{filename}"

        cur.execute(
            "UPDATE users SET profile_picture = %s WHERE u_id = %s",
            (profile_picture_path, session["user_id"]),
        )

        conn.commit()
        session["profile_picture"] = profile_picture_path
        flash("Profile picture updated.", "success")
    else:
        flash("Please upload a valid image (png, jpg, jpeg, webp).", "error")

    cur.close()
    conn.close()

    return redirect(url_for("dashboard.profile"))


# remove profile picture
@dashboard_bp.route("/profile/remove-picture", methods=["POST"])
@login_required
def remove_profile_picture():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT profile_picture FROM users WHERE u_id = %s", (session["user_id"],)
    )
    user = cur.fetchone()

    if user and user["profile_picture"]:
        # Build the actual file path
        file_path = os.path.join("app", "static", user["profile_picture"])

        # Delete the physical image if it exists
        if os.path.exists(file_path):
            os.remove(file_path)

        # Remove the path from database
        cur.execute(
            "UPDATE users SET profile_picture = NULL WHERE u_id = %s",
            (session["user_id"],),
        )

        conn.commit()
        session["profile_picture"] = ""
        flash("Profile picture removed.", "success")

    cur.close()
    conn.close()

    return redirect(url_for("dashboard.profile"))
