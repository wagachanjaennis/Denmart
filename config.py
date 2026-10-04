import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse

BASE_DIR = Path(__file__).resolve().parent


def normalize_db_url(url: str | None) -> str:
    url = url or f"sqlite:///{BASE_DIR / 'instance' / 'real_mart.db'}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = normalize_db_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 512 * 1024 * 1024
    PRODUCT_IMAGE_LOOKUP_URL = os.getenv("PRODUCT_IMAGE_LOOKUP_URL", "https://world.openfoodfacts.org/cgi/search.pl")
    PRODUCT_IMAGE_LOOKUP_TIMEOUT = float(os.getenv("PRODUCT_IMAGE_LOOKUP_TIMEOUT", "6"))
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    WTF_CSRF_TIME_LIMIT = None
    SESSION_COOKIE_SECURE = os.getenv("FLASK_ENV", "development") == "production"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CURRENCY = os.getenv("CURRENCY", "KES")
    TIMEZONE = os.getenv("TIMEZONE", "Africa/Nairobi")
    BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Denmart")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    # Fixed merchant destination for the current deployment. Keep this server-side; never bake it into the Android APK.
    # Optional stable public URL, e.g. https://denmart.onrender.com. When set,
    # the Android gateway link is generated from this value instead of depending
    # on reverse-proxy URL inference.
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    # Optional shared gateway secret for deployments that need to reconnect an
    # existing Android APK after moving/rebuilding the database. Prefer the
    # database-generated secret when this is not set.
    ANDROID_GATEWAY_SHARED_SECRET = os.getenv("ANDROID_GATEWAY_SHARED_SECRET", "").strip() or os.getenv("PAYMENT_GATEWAY_SHARED_SECRET", "").strip()


# New PAY module defaults. These seed only the independent payment module and do not reuse payment history.
