"""Production-safe first-boot database bootstrap."""
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from extensions import db
from seed import seed_defaults
from models import Business, Store


def bootstrap_database():
    db.create_all()
    # The independent /pay receipt ledger intentionally permits the same M-PESA
    # transaction code to appear again as a stored duplicate receipt. A prior
    # iteration briefly made transaction_code unique at the receipt-row level,
    # which could prevent the duplicate SMS itself from being audited. Remove that
    # obsolete constraint once, without touching any other table.
    try:
        if db.engine.url.get_backend_name() == "postgresql":
            db.session.execute(text(
                "ALTER TABLE auto_payment_receipts DROP CONSTRAINT IF EXISTS uq_auto_pay_business_transaction"
            ))
            db.session.commit()
    except Exception:
        db.session.rollback()
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
