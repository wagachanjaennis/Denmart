from __future__ import annotations

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from extensions import db
from models import AutoPaymentReceipt, Customer, Order, OrderItem, Payment, PaymentDestination, Sale, SaleItem, Store, SystemSetting


bp = Blueprint("pay", __name__)


def pay_admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if (session.get("portal") != "admin" or not current_user.is_authenticated or
                not current_user.has_permission("payments.view")):
            return redirect(f"/control?next={request.path}")
        return fn(*args, **kwargs)
    return wrapped


def _business_store():
    business_id = current_user.business_id
    stores = Store.query.filter_by(business_id=business_id, is_active=True).order_by(Store.created_at).all()
    return business_id, stores[0] if len(stores) == 1 else None


def _destination(store):
    business_id = current_user.business_id if current_user.is_authenticated else (store.business_id if store else None)
    if not business_id:
        return {"channel": "TILL", "number": "", "label": "Denmart M-PESA"}
    destination = None
    if store:
        destination = (PaymentDestination.query.filter_by(
            business_id=business_id, store_id=store.id, is_active=True, is_default=True
        ).first() or PaymentDestination.query.filter_by(
            business_id=business_id, store_id=store.id, is_active=True
        ).order_by(PaymentDestination.created_at.desc()).first())
    destination = destination or PaymentDestination.query.filter_by(
        business_id=business_id, store_id=None, is_active=True, is_default=True
    ).first() or PaymentDestination.query.filter_by(
        business_id=business_id, store_id=None, is_active=True
    ).order_by(PaymentDestination.created_at.desc()).first()
    if destination:
        return {"channel": destination.channel or "TILL", "number": destination.number or "", "label": destination.label or "Denmart M-PESA"}
    q = SystemSetting.query.filter_by(business_id=business_id, key="payment_gateway_merchant_number").first()
    number = (q.value or "").strip() if q else ""
    if not number:
        from flask import current_app
        number = str(current_app.config.get("DENMART_MERCHANT_TILL") or "").strip()
    return {"channel": "TILL", "number": number, "label": "Denmart M-PESA Till"}


def _order_row(order):
    customer = db.session.get(Customer, order.customer_id) if order.customer_id else None
    items = [{"name": i.product_name_snapshot, "quantity": str(i.quantity), "total": str(i.line_total)} for i in OrderItem.query.filter_by(order_id=order.id).all()]
    return {
        "type": "ONLINE", "id": order.id, "reference": order.order_number,
        "name": customer.name if customer else "", "phone": customer.phone if customer else "",
        "total": str(order.total or 0), "payment_status": order.payment_status,
        "status": order.status, "created_at": order.created_at.isoformat() if order.created_at else None, "items": items,
    }


def _sale_row(sale):
    payment = (Payment.query.filter(
        Payment.sale_id == sale.id,
        Payment.method.in_({"MPESA", "MPESA_TILL", "MPESA_GATEWAY_INTENT", "MPESA_GATEWAY"}),
    ).order_by(Payment.created_at.desc()).first())
    raw_name = ""
    if payment and payment.raw_provider_reference:
        import json
        try:
            raw = json.loads(payment.raw_provider_reference) if isinstance(payment.raw_provider_reference, str) else payment.raw_provider_reference
            raw_name = str(raw.get("customer_name") or "").strip() if isinstance(raw, dict) else ""
        except Exception:
            raw_name = ""
    items = [{"name": i.product_name_snapshot, "quantity": str(i.quantity), "total": str(i.line_total)} for i in SaleItem.query.filter_by(sale_id=sale.id).all()]
    return {
        "type": "POS", "id": sale.id, "reference": sale.receipt_number,
        "name": raw_name, "phone": payment.phone_number if payment else "",
        "total": str(sale.total or 0), "payment_status": sale.payment_status,
        "status": sale.status, "created_at": sale.created_at.isoformat() if sale.created_at else None, "items": items,
    }


@bp.get("/pay")
@pay_admin_required
def dashboard():
    return render_template("pay/dashboard.html", destination=_destination(None))


@bp.get("/pay/api/pending")
@pay_admin_required
def pending_api():
    business_id, single_store = _business_store()
    orders_q = Order.query.filter(Order.business_id == business_id, Order.payment_status.in_({"UNPAID", "PENDING_APPROVAL"}), ~Order.status.in_({"CANCELLED", "DELETED", "EXPIRED"}))
    sales_q = Sale.query.filter(Sale.business_id == business_id, Sale.payment_status.in_({"UNPAID", "PENDING_APPROVAL"}), ~Sale.status.in_({"CANCELLED", "VOID", "DELETED", "EXPIRED"}))
    if single_store:
        orders_q = orders_q.filter(Order.store_id == single_store.id)
        sales_q = sales_q.filter(Sale.store_id == single_store.id)
    orders = orders_q.order_by(Order.created_at.desc()).limit(100).all()
    sales = sales_q.order_by(Sale.created_at.desc()).limit(100).all()
    return jsonify(ok=True, orders=[_order_row(o) for o in orders], sales=[_sale_row(s) for s in sales])


@bp.get("/pay/api/live")
@pay_admin_required
def live_api():
    business_id, _ = _business_store()
    rows = AutoPaymentReceipt.query.filter_by(business_id=business_id).order_by(AutoPaymentReceipt.received_at.desc()).limit(50).all()
    return jsonify(ok=True, events=[{
        "id": r.id, "event_id": r.event_id, "transaction_code": r.transaction_code,
        "amount": str(r.amount or 0), "payer_name": r.payer_name or "", "phone": r.phone or "",
        "normalized_phone": r.normalized_phone or "", "sender": r.sender or "",
        "raw_message": r.raw_message, "received_at": r.received_at.isoformat() if r.received_at else None,
        "classification": r.classification, "matching_method": r.matching_method or "",
        "matched_order_id": r.matched_order_id, "matched_sale_id": r.matched_sale_id,
        "matched_payment_id": r.matched_payment_id,
    } for r in rows])


@bp.get("/pay/api/automated")
@pay_admin_required
def automated_api():
    business_id, _ = _business_store()
    rows = AutoPaymentReceipt.query.filter(
        AutoPaymentReceipt.business_id == business_id,
        AutoPaymentReceipt.classification.in_({"AUTO_APPROVED", "PAYMENT_UNMATCHED", "PAYMENT_AMBIGUOUS", "UNDERPAYMENT", "OVERPAYMENT", "DUPLICATE_ALREADY_PROCESSED"}),
    ).order_by(AutoPaymentReceipt.received_at.desc()).limit(100).all()
    return jsonify(ok=True, events=[{
        "transaction_code": r.transaction_code, "amount": str(r.amount or 0), "payer_name": r.payer_name or "",
        "phone": r.normalized_phone or r.phone or "", "received_at": r.received_at.isoformat() if r.received_at else None,
        "classification": r.classification, "matching_method": r.matching_method or "",
        "matched_order_id": r.matched_order_id, "matched_sale_id": r.matched_sale_id,
    } for r in rows])


@bp.get("/pay/checkout")
def checkout():
    from routes.shop import active_stores, selected_store
    store = selected_store()
    stores = active_stores()
    return render_template("pay/checkout.html", store=store, stores=stores, destination=_destination(store))


@bp.get("/pay/order/<order_number>")
def payment_page(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    items = OrderItem.query.filter_by(order_id=order.id).all()
    store = db.session.get(Store, order.store_id)
    customer = db.session.get(Customer, order.customer_id) if order.customer_id else None
    return render_template("pay/order_payment.html", order=order, items=items, store=store, customer=customer, destination=_destination(store))


@bp.get("/pay/api/order/<order_number>")
def order_status(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    receipt = AutoPaymentReceipt.query.filter_by(matched_order_id=order.id).order_by(AutoPaymentReceipt.received_at.desc()).first()
    return jsonify(ok=True, order_number=order.order_number, payment_status=order.payment_status, status=order.status, total=str(order.total or 0),
                   receipt={"transaction_code": receipt.transaction_code, "amount": str(receipt.amount or 0), "classification": receipt.classification,
                            "received_at": receipt.received_at.isoformat() if receipt.received_at else None} if receipt else None)
