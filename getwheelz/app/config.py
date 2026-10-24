import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"

    # Stay logged in after the browser is closed: the login cookie lasts this many days and is
    # renewed every time the person uses the site (so it only expires after that long of NOT visiting).
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=int(os.environ.get("SESSION_DAYS", "30"))
    )

    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    DB_NAME = os.environ.get("DB_NAME")
    DB_USER = os.environ.get("DB_USER")
    DB_PASSWORD = os.environ.get("DB_PASSWORD")

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

    # "Continue with Google". Create an OAuth client in Google Cloud Console and put both values in .env.
    # Without them the Google buttons stay visible but tell the person it is not set up yet.
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    # Optional: the exact callback URL registered in Google (needed behind a proxy / on a custom domain).
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")

    # Password reset links: public address of the site (optional) and how long a link works.
    APP_BASE_URL = os.environ.get("APP_BASE_URL")
    PASSWORD_RESET_MINUTES = int(os.environ.get("PASSWORD_RESET_MINUTES", "60"))

    # Shown on the Contact page. Messages are saved in the database.
    # CONTACT_PHONE is left out of the page while it is empty, so no fake number is shown.
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "support@getwheelz.com")
    CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "")
    CONTACT_LOCATION = os.environ.get("CONTACT_LOCATION", "Guwahati, Assam, India")