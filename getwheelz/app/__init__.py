from flask import Flask
from app.utils import encode_uid, encode_wid

def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')
    app.jinja_env.filters['wtoken'] = encode_wid
    app.jinja_env.filters['utoken'] = encode_uid

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

    return app