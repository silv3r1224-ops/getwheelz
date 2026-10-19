import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('COOKIE_SECURE') == '1'

    # Stay logged in after the browser is closed: the login cookie lasts this many days and is
    # renewed every time the person uses the site (so it only expires after that long of NOT visiting).
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.environ.get('SESSION_DAYS', '30')))

    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME')
    DB_USER = os.environ.get('DB_USER')
    DB_PASSWORD = os.environ.get('DB_PASSWORD')

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB