from decimal import Decimal
from datetime import timezone
import json
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for, jsonify
from flask_login import current_user, login_required

from extensions import db, csrf
from models import Business, Store, StoreProduct, PayOrder, PayOrderItem, PayReceipt, PaySettings, PayEvent, User, now
from services.payment_engine import (
    create_payment_order,
    enabled_methods,
    get_pay_settings,
    manual_approve,
    set_fulfillment,
    normalize_phone,
)

bp = Blueprint("pay", __name__)


def _admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        from flask import session
        if session.get("portal") != "admin" or not current_user.is_authenticated or not current_user.role or current_user.role.name != "OWNER":
            return "Forbidden", 403
        return fn(*args, **kwargs)
    return wrapped


def _default_store_from_items(items):
    ids = []
    for raw in items or []:
        ids.append(str(raw.get("id") or raw.get("store_product_id") or "").strip())
    ids = [x for x in ids if x]
    if not ids:
        return None
    sp = StoreProduct.query.filter(StoreProduct.id.in_(ids)).first()
    return sp.store if sp else None


def _expire(order):
    # PostgreSQL schemas created by older releases may return timestamp columns
    # without tzinfo even though the model now declares timezone=True. Normalize
    # both representations before Python compares them.
    expires_at = order.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    elif expires_at:
        expires_at = expires_at.astimezone(timezone.utc)
    if order.payment_status in {"PENDING", "MANUAL_REVIEW"} and expires_at and expires_at <= now():
        order.payment_status = "EXPIRED"
        order.review_reason = "Payment request expired."
        db.session.add(PayEvent(payment_order_id=order.id, event_type="EXPIRED", source="SYSTEM", note="Payment window expired without approval."))
        db.session.commit()
        return True
    return False


@bp.get("/pay")
def pay_home():
    return redirect(url_for("shop.cart"))


@bp.post("/pay/start")
def start_payment():
    raw_cart = request.form.get("cart_json", "")
    try:
        items = json.loads(raw_cart) if raw_cart else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list) or not items:
        flash("Your basket is empty. Add items before paying.", "error")
        return redirect("/cart")

    store = _default_store_from_items(items)
    if not store or not store.is_active:
        flash("The selected store is not available. Please refresh your basket.", "error")
        return redirect("/cart")

    customer_name = request.form.get("customer_name", "").strip()
    phone = request.form.get("customer_phone", "").strip()
    method = request.form.get("payment_method", "").strip().upper()

    try:
        # The server recalculates the total from current catalogue prices; client prices are never trusted.
        total = Decimal("0")
        clean_items = []
        for raw in items:
            sp_id = str(raw.get("id") or "").strip()
            qty = Decimal(str(raw.get("qty") or 0))
            if not sp_id or qty <= 0:
                raise ValueError("Your basket contains an invalid item.")
            sp = StoreProduct.query.filter_by(id=sp_id, store_id=store.id).first()
            if not sp:
                raise ValueError("One of the basket items is no longer available.")
            total += (Decimal(str(sp.selling_price)) * qty).quantize(Decimal("0.01"))
            clean_items.append({"store_product_id": sp_id, "quantity": str(qty)})
        order = create_payment_order(
            business_id=store.business_id,
            store_id=store.id,
            customer_name=customer_name,
            phone=phone,
            amount=total,
            items=clean_items,
            channel="ONLINE",
            payment_method=method or None,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect("/cart")
    except Exception:
        db.session.rollback()
        flash("We could not start the payment. Please refresh the basket and try again.", "error")
        return redirect("/cart")
    return redirect(url_for("pay.approval", token=order.public_token))


@bp.get("/pay/approval/<token>")
def approval(token):
    order = PayOrder.query.filter_by(public_token=token).first_or_404()
    _expire(order)
    items = PayOrderItem.query.filter_by(payment_order_id=order.id).order_by(PayOrderItem.product_name_snapshot).all()
    return render_template("pay/approval.html", order=order, items=items)


@bp.get("/pay/api/<token>")
def approval_api(token):
    order = PayOrder.query.filter_by(public_token=token).first_or_404()
    _expire(order)
    return jsonify(
        ok=True,
        reference=order.reference,
        payment_status=order.payment_status,
        fulfillment_status=order.fulfillment_status,
        expected_amount=str(order.expected_amount),
        paid_amount=str(order.paid_amount) if order.paid_amount is not None else None,
        paid_at=order.paid_at.isoformat() if order.paid_at else None,
        transaction_code=order.mpesa_transaction_code,
        reason=order.review_reason,
        updated_at=(order.paid_at or order.created_at).isoformat() if (order.paid_at or order.created_at) else None,
    )


@bp.get("/control/pay")
@_admin_required
def admin_pay():
    business_id = current_user.business_id
    statuses = ["PENDING", "MANUAL_REVIEW", "PAID", "EXPIRED"]
    rows = (PayOrder.query.filter(PayOrder.business_id == business_id, PayOrder.payment_status.in_(statuses))
            .order_by(PayOrder.created_at.desc()).limit(300).all())
    for row in rows:
        _expire(row)
    # Re-query after expiry changes for the clean current list.
    rows = (PayOrder.query.filter(PayOrder.business_id == business_id)
            .order_by(PayOrder.created_at.desc()).limit(300).all())
    settings = get_pay_settings(business_id)
    recent_receipts = PayReceipt.query.filter_by(business_id=business_id).order_by(PayReceipt.created_at.desc()).limit(80).all()
    return render_template("admin/pay.html", rows=rows, settings=settings, methods=enabled_methods(settings), recent_receipts=recent_receipts)


@bp.post("/control/pay/settings")
@_admin_required
def save_pay_settings():
    settings = get_pay_settings(current_user.business_id)
    mode = request.form.get("mode", "PAYBILL").upper()
    if mode not in {"PAYBILL", "BUY_GOODS", "BOTH"}:
        flash("Choose PayBill, Buy Goods, or both.", "error")
        return redirect(url_for("pay.admin_pay"))
    settings.mode = mode
    settings.paybill_number = request.form.get("paybill_number", "").strip()[:40] or None
    settings.paybill_account_name = request.form.get("paybill_account_name", "").strip()[:160] or None
    settings.buy_goods_till = request.form.get("buy_goods_till", "").strip()[:40] or None
    settings.display_name = request.form.get("display_name", "Denmart").strip()[:160] or "Denmart"
    settings.instructions = request.form.get("instructions", "").strip()[:500] or "Pay using the payment option shown, then wait for approval."
    settings.updated_at = now()
    db.session.add(settings)
    db.session.commit()
    flash("PAY settings saved.", "success")
    return redirect(url_for("pay.admin_pay"))


@bp.post("/control/pay/<order_id>/approve")
@_admin_required
def manual_approve_order(order_id):
    order = PayOrder.query.filter_by(id=order_id, business_id=current_user.business_id).first_or_404()
    reason = request.form.get("reason", "Manual approval by administrator").strip()[:1000] or "Manual approval by administrator"
    try:
        ok, message = manual_approve(order, current_user.id, reason)
        if ok:
            flash(f"{order.reference} approved. It is now in packaging.", "success")
        else:
            flash(message, "error")
    except Exception:
        db.session.rollback()
        flash("Manual approval could not be completed safely. No payment state was changed.", "error")
    return redirect(url_for("pay.admin_pay"))


@bp.post("/control/pay/<order_id>/fulfillment")
@_admin_required
def fulfillment(order_id):
    order = PayOrder.query.filter_by(id=order_id, business_id=current_user.business_id).first_or_404()
    status = request.form.get("status", "").upper()
    try:
        set_fulfillment(order, status, current_user.id)
        flash(f"{order.reference} moved to {status}.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    except Exception:
        db.session.rollback()
        flash("Fulfillment update failed safely; no change was saved.", "error")
    return redirect(url_for("pay.admin_pay"))


@bp.get("/control/pay/<order_id>")
@_admin_required
def pay_detail(order_id):
    order = PayOrder.query.filter_by(id=order_id, business_id=current_user.business_id).first_or_404()
    _expire(order)
    items = PayOrderItem.query.filter_by(payment_order_id=order.id).all()
    receipt = PayReceipt.query.filter_by(matched_payment_order_id=order.id).order_by(PayReceipt.created_at.desc()).first()
    events = PayEvent.query.filter_by(payment_order_id=order.id).order_by(PayEvent.created_at.desc()).limit(100).all()
    return render_template("admin/pay_detail.html", order=order, items=items, receipt=receipt, events=events)


@csrf.exempt
@bp.post("/api/pos/pay")
@login_required
def pos_create_payment():
    from flask import session
    if session.get("portal") != "pos" or not current_user.is_active or not current_user.business_id or not current_user.store_id or not current_user.has_permission("sales.create"):
        return jsonify(error="forbidden"), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get("customer_name") or "").strip()
    phone = str(data.get("customer_phone") or "").strip()
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify(error="cart_empty"), 400
    try:
        total = Decimal("0")
        clean = []
        for raw in items:
            sp_id = str(raw.get("store_product_id") or raw.get("id") or "").strip()
            qty = Decimal(str(raw.get("quantity") or raw.get("qty") or 0))
            if not sp_id or qty <= 0:
                raise ValueError("Invalid basket item.")
            sp = StoreProduct.query.filter_by(id=sp_id, store_id=current_user.store_id).first()
            if not sp or not sp.available_pos or not sp.is_available:
                raise ValueError("One of the selected items is no longer available.")
            available = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(sp.reserved_quantity or 0))
            if available < qty:
                raise ValueError(f"Not enough stock for {sp.product.name}.")
            total += (Decimal(str(sp.selling_price)) * qty).quantize(Decimal("0.01"))
            clean.append({"store_product_id": sp.id, "quantity": str(qty)})
        order = create_payment_order(
            business_id=current_user.business_id,
            store_id=current_user.store_id,
            customer_name=name,
            phone=phone,
            amount=total,
            items=clean,
            channel="POS",
            payment_method=str(data.get("payment_method") or "").upper() or None,
        )
        return jsonify(ok=True, payment_id=order.id, reference=order.reference, amount=str(order.expected_amount), approval_url=url_for("pay.approval", token=order.public_token, _external=True))
    except ValueError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    except Exception:
        db.session.rollback()
        return jsonify(error="payment_request_failed"), 500
