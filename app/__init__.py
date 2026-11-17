import gzip
import logging
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env before anything reads environment variables (including the limiter storage below).
# The env file lives inside app/ (app/.env); also accept one next to the working directory.
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect

from app import booking_rules, crypto, inbox_ui
from app.booking_rules import label as booking_status_label
from app.payments import money
from app.utils import encode_uid, encode_wid

csrf = CSRFProtect()
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Memory storage is fine for a single worker in development. Behind multiple gunicorn workers
# (or across restarts) limits are per-worker and reset on restart, so set
# RATE_LIMIT_STORAGE_URI (e.g. "redis://localhost:6379/0") in production.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://"),
)


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")
    # encrypted ids in URLs: <sealed("workshop"):w_id> (app/crypto.py)
    app.url_map.converters["sealed"] = crypto.SealedConverter
    app.jinja_env.filters["seal"] = lambda value, purpose: crypto.seal(purpose, value)
    app.config["CONSENT_GATE_ENABLED"] = os.environ.get("GETWHEELZ_DISABLE_CONSENT_GATE_FOR_TESTS") != "1"
    app.jinja_env.filters["wtoken"] = encode_wid
    app.jinja_env.filters["utoken"] = encode_uid
    app.jinja_env.filters["money"] = money  # used by the admin bookings page
    app.jinja_env.filters["status_label"] = booking_status_label  # "in_progress" -> "In progress"
    # inbox presentation (app/inbox_ui.py): compact rows show relative times, one-line previews and
    # a category icon
    app.jinja_env.filters["rel_time"] = lambda moment: inbox_ui.relative_time(moment, booking_rules.now())
    app.jinja_env.filters["preview"] = inbox_ui.preview
    app.jinja_env.filters["cat_icon"] = inbox_ui.category_icon
    app.jinja_env.filters["cat_label"] = inbox_ui.category_label

    csrf.init_app(app)
    limiter.init_app(app)
    from app.db import close_db_connections

    app.teardown_appcontext(close_db_connections)

    # Register blueprints
    from app.routes.appeals import appeals_bp
    from app.routes.auth import auth_bp
    from app.routes.bookings import bookings_bp
    from app.routes.customers import customer_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.legal import legal_bp
    from app.routes.main import main_bp
    from app.routes.mechanics import mechanics_bp
    from app.routes.workshops import workshops_bp

    from app.live import LIVE_OFF_ENDPOINTS, live_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(legal_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(workshops_bp, url_prefix="/workshops")
    app.register_blueprint(bookings_bp, url_prefix="/bookings")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(customer_bp, url_prefix="/customer")
    app.register_blueprint(mechanics_bp, url_prefix="/mechanics")

    # ------------------------------------------------------------------
    # Security headers on every response.
    #
    # The CSP is pragmatic, not maximal: the app still uses inline <script>
    # blocks, so 'unsafe-inline' is allowed for scripts, but everything else
    # is restricted to the site itself plus the few external origins the app
    # genuinely uses (Google Fonts, unpkg, OpenStreetMap tiles, which load as
    # <img>). The flash messages / maps keep working; XSS payloads from other
    # origins, object embeds, data: URIs, mixed content and clickjacking
    # iframes are blocked.
    # ------------------------------------------------------------------
    # Directives are separated by semicolons — a missing one makes the browser parse
    # every later directive as a source expression of default-src (and ignore the
    # policy's 'none' conflict), so the whole header would be nullified.
    _CSP = "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://unpkg.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com https://api.fontshare.com",
            "font-src 'self' https://fonts.gstatic.com https://unpkg.com https://cdn.fontshare.com",
            "img-src 'self' data: blob: https://unpkg.com https://*.tile.openstreetmap.org",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "frame-src 'none'",
            "worker-src 'self'",
            "manifest-src 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        ]
    )

    @app.after_request
    def add_security_headers(response):
        secure = request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"
        # "upgrade-insecure-requests" only when the page really came over https; on plain-http local development it
        # would turn every redirect into an https request that nothing answers
        response.headers.setdefault("Content-Security-Policy", _CSP + ("; upgrade-insecure-requests" if secure else ""))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(self), camera=(), microphone=(), payment=(), usb=(), "
            "serial=(), accelerometer=(), gyroscope=(), magnetometer=(), interest-cohort=()",
        )
        # no other site can open this one in a window it controls, or embed its files
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.headers.setdefault("X-DNS-Prefetch-Control", "off")
        # pages of a signed-in person (and the JSON behind them) are never kept by the browser or a proxy,
        # so the Back button after logout cannot show someone else's data
        if session.get("user_id") and request.endpoint != "static" and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
        # HSTS only when actually served over HTTPS (behind a proxy, trust the header)
        if secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    # ------------------------------------------------------------------
    # Delivery speed: gzip + browser caching. The stylesheet alone is ~620 KB and the scripts add
    # several hundred more; uncompressed that is a long wait on a phone or a slow connection.
    # Text responses are gzipped when the browser accepts it (static files are compressed once and
    # kept in memory), and static files get a cache lifetime: a week for files whose URL carries a
    # ?v= tag (the tag changes whenever the file does), an hour for the rest. Off in debug mode so
    # development edits show up immediately.
    # ------------------------------------------------------------------
    _GZ_TYPES = ("text/", "application/javascript", "application/json", "image/svg+xml")
    _gz_cache = {}

    @app.after_request
    def compress_and_cache(response):
        if request.endpoint == "static" and response.status_code == 200 and not app.debug:
            week = request.args.get("v") is not None
            response.headers["Cache-Control"] = "public, max-age=604800" if week else "public, max-age=3600"

        if (
            response.status_code != 200
            or response.is_streamed and not response.direct_passthrough
            or "Content-Encoding" in response.headers
            or "gzip" not in request.headers.get("Accept-Encoding", "")
            or not response.mimetype
            or not response.mimetype.startswith(_GZ_TYPES)
            or request.method == "HEAD"
        ):
            return response

        response.direct_passthrough = False
        data = response.get_data()
        if len(data) < 1024:
            return response

        key = None
        if request.endpoint == "static":
            etag = response.headers.get("ETag")
            if etag:
                key = (request.path, etag)
                gz = _gz_cache.get(key)
        if key is None or key not in _gz_cache:
            gz = gzip.compress(data, compresslevel=6)
            if key is not None:
                if len(_gz_cache) > 200:
                    _gz_cache.clear()
                _gz_cache[key] = gz
        response.set_data(gz)
        response.headers["Content-Encoding"] = "gzip"
        response.headers.add("Vary", "Accept-Encoding")
        return response

    @app.before_request
    def block_suspended_accounts():
        # A suspended account loses access immediately, even if it is already
        # signed in: any request from it clears the session and sends it home.
        if request.endpoint == "static" or not session.get("user_id"):
            return
        try:
            from app.db import get_db_connection

            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT is_suspended FROM users WHERE u_id = %s",
                    (session["user_id"],),
                )
                row = cur.fetchone()
            conn.close()
            if row and row["is_suspended"]:
                session.clear()
                flash("Your account has been suspended. Please contact support.", "error")
                return redirect(url_for("main.index"))
        except Exception:
            # A DB hiccup must not lock the whole site out; the next request retries.
            pass

    # --- unanswered-booking sweep (spec section 6: cancel after 48 hours) ---------------------
    # The real schedule is `python scripts/run_booking_sweep.py` (cron / a scheduled task). This
    # check on page load is the safety net for a small host where nothing may be scheduled: it runs
    # the same sweep at most once per BOOKING_SWEEP_SECONDS per process (0 turns it off). It never
    # blocks or breaks a page: failures are logged and the next interval retries, and a database
    # advisory lock stops several workers doing it at once.
    sweep_state = {"last": 0.0}
    sweep_lock = threading.Lock()
    try:
        sweep_every = float(os.environ.get("BOOKING_SWEEP_SECONDS", "300"))
    except ValueError:
        sweep_every = 300.0

    @app.before_request
    def sweep_unanswered_bookings():
        if sweep_every <= 0 or request.method != "GET" or request.endpoint in (None, "static"):
            return
        if time.monotonic() - sweep_state["last"] < sweep_every:
            return
        if not sweep_lock.acquire(blocking=False):
            return
        try:
            # set the time first so a failing database is retried at the next interval, not on every page
            sweep_state["last"] = time.monotonic()
            from app.booking_events import run_sweep

            run_sweep(app.config)
        except Exception:
            logging.exception("Booking sweep on page load failed")
        finally:
            sweep_lock.release()

    # --- login banner (spec section 8) ---------------------------------------------------------
    # Important notices show once, as a dismissible banner, on the first page rendered after login.
    # `banner_done` lives in the session, which is cleared at logout, so every new login gets one
    # check; the notice is marked as shown in the database in the same step, so it never returns
    # for that person (app/routes/main.py: login_banner).
    # --- consent gate (spec section 11) -----------------------------------------------------------
    # Customers, owners and mechanics must have accepted the CURRENT version of the Terms and Privacy
    # Policy (and owners with a workshop the Owner Agreement). Anyone who has not, or whose accepted
    # version is out of date, is sent to the accept page first. The session remembers a successful check
    # (see app/legal.py: signature), so the database is only asked after a sign-in, a version change, or
    # when an owner lists a workshop.
    @app.before_request
    def require_current_consent():
        from app import legal

        # Only the test suite switches this off (tests/conftest.py), because its fixtures create people
        # directly in the database without going through sign-up. Real deployments never set it.
        if not app.config.get("CONSENT_GATE_ENABLED", True):
            return None
        role, uid = session.get("role"), session.get("user_id")
        if not legal.gate_applies(request.endpoint, role, uid):
            return None
        if session.get("consent_sig") == legal.signature(role, session.get("consent_ws", False)):
            return None
        from app.db import get_db_connection
        from app.routes.legal import accepted_pairs, owner_has_workshop, remember_consent

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                has_ws = owner_has_workshop(cur, uid) if role == "owner" else False
                missing = legal.missing_docs(accepted_pairs(cur, uid), role, has_ws)
        finally:
            conn.close()
        if not missing:
            remember_consent(role, has_ws)
            return None
        target = url_for("legal.accept", next=request.full_path.rstrip("?") if request.method == "GET" else None)
        if request.headers.get("X-Requested-With") or request.is_json or request.method != "GET":
            from flask import jsonify

            if request.headers.get("X-Requested-With") or request.is_json:
                return jsonify(ok=False, consent_required=True, redirect=target), 403
            flash("Please accept the updated terms to continue.", "error")
        return redirect(target)

    @app.context_processor
    def inject_live():
        return {"LIVE_OFF_ENDPOINTS": LIVE_OFF_ENDPOINTS}

    @app.context_processor
    def inject_login_banner():
        if not session.get("user_id") or session.get("banner_done"):
            return {}
        banner = []
        try:
            from app.db import get_db_connection
            from app.routes.main import login_banner

            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    banner = login_banner(cur, session["user_id"], session.get("role") or "")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception:
            logging.exception("Could not load the login banner")
        session["banner_done"] = True
        return {"login_banner": banner}

    @app.context_processor
    def inject_catalog_services():
        # makes `catalog_services` available in every template (navbar dropdown, footer, landing page).
        # Once the visitor has picked cars or two-wheelers only that catalog is listed; before that
        # both catalogs are merged. `vehicle_choice` is the pick ('car' / 'two_wheeler') or None.
        from app.catalog import get_catalog_services
        from app.vehicles import (
            PLURAL_LABELS,
            SINGULAR_LABELS,
            VEHICLE_TYPES,
            chosen_vehicle,
        )

        vehicle = chosen_vehicle()
        return {
            "catalog_services": get_catalog_services(vehicle),
            "vehicle_choice": vehicle,
            "VEHICLE_TYPES": VEHICLE_TYPES,
            "VEHICLE_PLURAL": PLURAL_LABELS,
            "VEHICLE_SINGULAR": SINGULAR_LABELS,
        }

    @app.context_processor
    def inject_report_categories():
        # makes the report reason choices available in every template, so the
        # account/workshop report forms and the route validation cannot drift.
        from app.routes.main import (
            LEAVE_REASON_CATEGORY_CHOICES,
            REPORT_CATEGORY_CHOICES,
            WORKSHOP_REPORT_CATEGORY_CHOICES,
        )

        return {
            "REPORT_CATEGORY_CHOICES": REPORT_CATEGORY_CHOICES,
            "WORKSHOP_REPORT_CATEGORY_CHOICES": WORKSHOP_REPORT_CATEGORY_CHOICES,
            "LEAVE_REASON_CATEGORY_CHOICES": LEAVE_REASON_CATEGORY_CHOICES,
        }

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
    def inject_inbox_unread():
        # `inbox_unread_count` = actionable unread items for the signed-in user
        # (unread messages, plus pending join/leave requests for owners), so the
        # navbar envelope can show a badge. Failures degrade to 0 (no badge).
        if not session.get("user_id"):
            return {}
        try:
            from app.db import get_db_connection
            from app.routes.main import _inbox_unread_count

            conn = get_db_connection()
            with conn.cursor() as cur:
                n = _inbox_unread_count(cur, session["user_id"], session.get("role") or "")
            conn.close()
            return {"inbox_unread_count": n}
        except Exception:
            return {"inbox_unread_count": 0}

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