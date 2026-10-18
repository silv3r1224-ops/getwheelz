from flask import Flask, flash, redirect, url_for, request
from flask_wtf.csrf import CSRFProtect, CSRFError
from app.utils import encode_uid, encode_wid

csrf = CSRFProtect()
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')
    app.jinja_env.filters['wtoken'] = encode_wid
    app.jinja_env.filters['utoken'] = encode_uid

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
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(workshops_bp, url_prefix='/workshops')
    app.register_blueprint(bookings_bp, url_prefix='/bookings')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(customer_bp, url_prefix='/customer')
    app.register_blueprint(mechanics_bp, url_prefix='/mechanics')

    @app.context_processor
    def inject_catalog_services():
        # makes `catalog_services` available in every template (navbar dropdown, footer, landing page)
        from app.catalog import get_catalog_services
        return {'catalog_services': get_catalog_services()}

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash('Your session expired or the form was invalid. Please try again.', 'error')
        return redirect(url_for('main.index'))

    @app.errorhandler(413)
    def file_too_large(e):
        flash('That file is too large. Please upload an image under 5 MB.', 'error')
        back = request.referrer
        if back and back.startswith(request.host_url):
            return redirect(back)
        return redirect(url_for('main.index'))

    @app.errorhandler(429)
    def too_many_requests(e):
        flash('Too many attempts. Please wait a minute and try again.', 'error')
        return redirect(url_for('main.index'))

    return app