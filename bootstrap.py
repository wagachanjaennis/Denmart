"""Production-safe first-boot database bootstrap."""
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from extensions import db
from seed import seed_defaults
from models import Business, Store, SystemSetting
import secrets


def _ensure_gateway_secret():
    """Ensure the existing Android app can keep using its server secret."""
    configured = str(__import__("os").getenv("ANDROID_GATEWAY_SHARED_SECRET") or __import__("os").getenv("PAYMENT_GATEWAY_SHARED_SECRET") or "").strip()
    businesses = Business.query.order_by(Business.created_at).limit(2).all()
    if len(businesses) != 1:
        return
    business=businesses[0]
    row=SystemSetting.query.filter_by(business_id=business.id,key="android_gateway_secret").first()
    legacy=SystemSetting.query.filter_by(business_id=business.id,key="payment_gateway_secret").first()
    if configured:
        if not row:
            row=SystemSetting(business_id=business.id,key="android_gateway_secret",value=configured);db.session.add(row)
        elif row.value != configured:
            row.value=configured
        if legacy and legacy.id != row.id:
            db.session.delete(legacy)
    elif not row or not row.value:
        if legacy and legacy.value:
            row=row or SystemSetting(business_id=business.id,key="android_gateway_secret",value=legacy.value)
            row.value=legacy.value
            db.session.add(row)
            if legacy.id != row.id:
                db.session.delete(legacy)
        else:
            row=row or SystemSetting(business_id=business.id,key="android_gateway_secret")
        row.value=secrets.token_urlsafe(32)
        db.session.add(row)
    db.session.commit()




def _ensure_payment_columns():
    """Add non-destructive columns needed by the independent POS payment flow."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if "pay_orders" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("pay_orders")}
    if "pos_cashier_id" in columns:
        return
    if db.engine.url.get_backend_name() == "postgresql":
        db.session.execute(text('ALTER TABLE pay_orders ADD COLUMN IF NOT EXISTS pos_cashier_id VARCHAR(36) REFERENCES users(id)'))
    else:
        db.session.execute(text('ALTER TABLE pay_orders ADD COLUMN pos_cashier_id VARCHAR(36)'))
    db.session.commit()

def bootstrap_database():
    db.create_all()
    _ensure_payment_columns()
    _ensure_gateway_secret()
    try:
        seed_defaults()
    except IntegrityError:
        db.session.rollback()


def database_summary():
    return {
        "dialect": db.engine.url.get_backend_name(),
        "database": str(db.engine.url.database or ""),
        "has_business": Business.query.first() is not None,
        "store_count": Store.query.count(),
    }
