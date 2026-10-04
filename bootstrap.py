"""Production-safe first-boot database bootstrap."""
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from extensions import db
from seed import seed_defaults
from models import Business, Store, Payment, Order, Customer
from services.payments.normalization import normalize_ke_phone


def _ensure_column(table_name, column_name, ddl):
    inspector = inspect(db.engine)
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column_name in existing:
        return
    try:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Multiple Gunicorn workers can bootstrap at the same time. If another worker
        # won the DDL race, the column now exists and no retry is required.
        refreshed = {col["name"] for col in inspect(db.engine).get_columns(table_name)}
        if column_name not in refreshed:
            raise


def _ensure_gateway_schema():
    """Add matcher/audit fields to databases created before the live matcher rebuild."""
    # All additions are nullable so existing production rows remain valid.
    _ensure_column("payments", "normalized_phone", "VARCHAR(16)")
    _ensure_column("payment_gateway_events", "normalized_phone", "VARCHAR(16)")
    _ensure_column("payment_gateway_events", "classification", "VARCHAR(40)")
    _ensure_column("payment_gateway_events", "matched_by", "VARCHAR(60)")
    _ensure_column("payment_gateway_events", "processed_at", "TIMESTAMP")

    # Keep exact normalized-phone lookup fast. IF NOT EXISTS is supported by both
    # PostgreSQL and modern SQLite, and the index is additive/non-destructive.
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_normalized_phone ON payments (normalized_phone)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_payment_gateway_events_normalized_phone ON payment_gateway_events (normalized_phone)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_payment_gateway_events_classification ON payment_gateway_events (classification)"))

    # Backfill canonical phone values for existing payment rows. The raw phone_number
    # remains untouched for audit/display compatibility.
    gateway_methods = {
        "MPESA_TILL_INTENT", "MPESA_TILL", "MPESA_TILL_MANUAL",
        "MPESA_GATEWAY_INTENT", "MPESA_GATEWAY",
    }
    rows = Payment.query.filter(Payment.normalized_phone.is_(None), Payment.method.in_(gateway_methods)).all()
    changed = False
    for payment in rows:
        if payment.method in gateway_methods:
            normalized = normalize_ke_phone(payment.phone_number)
            if not normalized and payment.order_id:
                order = db.session.get(Order, payment.order_id)
                if order and order.customer_id:
                    customer = db.session.get(Customer, order.customer_id)
                    normalized = normalize_ke_phone(customer.phone if customer else None)
            if normalized:
                payment.normalized_phone = normalized
                changed = True
    if changed:
        db.session.commit()


def bootstrap_database():
    db.create_all()
    _ensure_gateway_schema()
    try:
        seed_defaults()
    except IntegrityError:
        db.session.rollback()
        # Another worker may have raced the first boot. The next request can retry safely.


def database_summary():
    return {
        "dialect": db.engine.url.get_backend_name(),
        "database": str(db.engine.url.database or ""),
        "has_business": Business.query.first() is not None,
        "store_count": Store.query.count(),
    }
