from flask import Flask, flash, redirect, url_for, request, session, render_template
from flask_wtf.csrf import CSRFProtect, CSRFError
from app.utils import encode_uid, encode_wid

csrf = CSRFProtect()
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")
    app.jinja_env.filters["wtoken"] = encode_wid
    app.jinja_env.filters["utoken"] = encode_uid

    csrf.init_app(app)
    limiter.init_app(app)
    from app.db import close_db_connections

    app.teardown_appcontext(close_db_connections)

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.auth import auth_bp
    from app.routes.workshops import workshops_bp
    from app.routes.bookings import bookings_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.customers import customer_bp
    from app.routes.mechanics import mechanics_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(workshops_bp, url_prefix="/workshops")
    app.register_blueprint(bookings_bp, url_prefix="/bookings")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(customer_bp, url_prefix="/customer")
    app.register_blueprint(mechanics_bp, url_prefix="/mechanics")

    @app.context_processor
    def inject_catalog_services():
        # makes `catalog_services` available in every template (navbar dropdown, footer, landing page)
        from app.catalog import get_catalog_services

        return {"catalog_services": get_catalog_services()}

    @app.context_processor
    def inject_nav_user():
        # `nav_picture` = the signed-in person's profile picture (static-relative path), or '' if none.
        # Looked up once after login and then kept in the session, so pages do not query it every time.
        if not session.get("user_id"):
            return {}
        if "profile_picture" not in session:
            try:
                from app.db import get_db_connection

                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT profile_picture FROM users WHERE u_id = %s",
                        (session["user_id"],),
                    )
                    row = cur.fetchone()
                session["profile_picture"] = (row and row["profile_picture"]) or ""
            except Exception:
                return {"nav_picture": ""}
        return {"nav_picture": session["profile_picture"]}

    @app.context_processor
    def inject_tour():
        # `tour_pending` is True until a new account finishes or skips NEO's first-login tour.
        # Looked up once per login and kept in the session. If the tour_seen column does not exist
        # yet (migrate_tour.sql not run) the tour is simply switched off, the site keeps working.
        if not session.get("user_id"):
            return {}
        if "tour_seen" not in session:
            try:
                from app.db import get_db_connection

                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute("SELECT tour_seen FROM users WHERE u_id = %s", (session["user_id"],))
                    row = cur.fetchone()
                session["tour_seen"] = bool(row["tour_seen"]) if row else True
            except Exception:
                return {"tour_pending": False}
        return {"tour_pending": not session["tour_seen"]}

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash(
            "Your session expired or the form was invalid. Please try again.", "error"
        )
        return redirect(url_for("main.index"))

    @app.errorhandler(413)
    def file_too_large(e):
        flash("That file is too large. Please upload an image under 5 MB.", "error")
        back = request.referrer
        if back and back.startswith(request.host_url):
            return redirect(back)
        return redirect(url_for("main.index"))

    @app.errorhandler(429)
    def too_many_requests(e):
        flash("Too many attempts. Please wait a minute and try again.", "error")
        return redirect(url_for("main.index"))

    # friendly error pages: NEO looks around (404), looks worried (403) or is fixing things (500)
    def _error_page(code, title, text, mood, skin="", wander=False):
        return (
            render_template(
                "errors/error.html",
                code=code,
                title=title,
                text=text,
                mood=mood,
                skin=skin,
                wander=wander,
            ),
            code,
        )

    @app.errorhandler(404)
    def not_found(e):
        return _error_page(
            404,
            "Page not found",
            "NEO looked everywhere, but this page isn't here. It may have moved.",
            "neutral",
            "violet",
            True,
        )

    @app.errorhandler(403)
    def forbidden(e):
        return _error_page(
            403, "Not allowed", "This area isn't open to your account.", "strained"
        )

    @app.errorhandler(500)
    def server_error(e):
        return _error_page(
            500,
            "Something broke",
            "NEO is on it with a screwdriver. Please try again in a moment.",
            "screwing",
        )

    return app