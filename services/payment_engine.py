from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from extensions import db
from config import Config
from models import PayOrder, PayOrderItem, PayReceipt, PaySettings, PayEvent, StoreProduct, InventoryTransaction, now

TWOPLACES = Decimal("0.01")


def normalize_phone(value):
    raw = re.sub(r"\D", "", str(value or "").strip())
    if raw.startswith("254") and len(raw) == 12 and raw[3] in "17":
        return raw
    if raw.startswith("0") and len(raw) == 10 and raw[1] in "17":
        return "254" + raw[1:]
    if len(raw) == 9 and raw[0] in "17":
        return "254" + raw
    return ""


def normalize_name(value):
    value = str(value or "").upper().strip()
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_amount(value):
    try:
        if isinstance(value, Decimal):
            amount = value
        else:
            text = re.sub(r"[^0-9.\-]", "", str(value or ""))
            amount = Decimal(text)
        return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def make_reference():
    return f"DM-PAY-{now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3).upper()}"


def make_public_token():
    return secrets.token_urlsafe(32)


def get_pay_settings(business_id, create=True):
    row = PaySettings.query.filter_by(business_id=business_id).first()
    if row:
        # Hard-coded fallback keeps checkout usable even when the independent
        # PAY settings row exists but has never been configured.
        if not (row.paybill_number or row.buy_goods_till):
            row.buy_goods_till = (getattr(Config, "DENMART_MERCHANT_TILL", "") or "").strip()
            row.mode = "BUY_GOODS"
            row.display_name = row.display_name or "Denmart"
            row.instructions = row.instructions or "Send the exact amount to the Denmart M-PESA Till shown below, then wait for approval."
            row.updated_at = now()
            db.session.add(row)
            db.session.flush()
        return row if create else row
    if not create:
        return None
    from os import getenv
    fixed_till = (getattr(Config, "DENMART_MERCHANT_TILL", "") or "").strip()
    row = PaySettings(
        business_id=business_id,
        mode=(getenv("PAYMENT_METHOD_MODE", getattr(Config, "DENMART_PAYMENT_METHOD", "BUY_GOODS")) or "BUY_GOODS").upper(),
        paybill_number=(getenv("PAYBILL_NUMBER", "") or "").strip(),
        paybill_account_name=(getenv("PAYBILL_ACCOUNT_NAME", "Denmart") or "Denmart").strip(),
        buy_goods_till=(getenv("BUY_GOODS_TILL", fixed_till) or fixed_till).strip(),
        display_name=(getenv("PAYMENT_DISPLAY_NAME", "Denmart") or "Denmart").strip(),
        instructions=(getenv("PAYMENT_INSTRUCTIONS", "Send the exact amount to the Denmart M-PESA Till shown below, then wait for approval.") or "").strip(),
        updated_at=now(),
    )
    db.session.add(row)
    db.session.flush()
    return row


def payment_instruction_snapshot(settings, method):
    method = (method or "").upper()
    if method == "PAYBILL":
        return {
            "method": "PAYBILL",
            "label": settings.display_name or "Denmart",
            "paybill_number": settings.paybill_number or "",
            "account_name": settings.paybill_account_name or settings.display_name or "Denmart",
            "instructions": settings.instructions or "Pay using the PayBill details shown.",
        }
    if method == "BUY_GOODS":
        return {
            "method": "BUY_GOODS",
            "label": settings.display_name or "Denmart",
            "till_number": settings.buy_goods_till or "",
            "instructions": settings.instructions or "Pay using the Buy Goods Till shown.",
        }
    return {}


def enabled_methods(settings):
    out = []
    mode = (settings.mode or "").upper()
    if mode in {"PAYBILL", "BOTH"} and settings.paybill_number:
        out.append("PAYBILL")
    if mode in {"BUY_GOODS", "BOTH"} and settings.buy_goods_till:
        out.append("BUY_GOODS")
    return out


def create_payment_order(*, business_id, store_id, customer_name, phone, amount, items=None, channel="ONLINE", payment_method=None):
    name = str(customer_name or "").strip()[:160]
    name_norm = normalize_name(name)
    phone_norm = normalize_phone(phone)
    total = normalize_amount(amount)
    if not name_norm or len(name_norm) < 2:
        raise ValueError("Enter the customer's full M-PESA registered name.")
    if not phone_norm:
        raise ValueError("Enter a valid Kenyan phone number.")
    if total is None or total <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    settings = get_pay_settings(business_id)
    methods = enabled_methods(settings)
    if not methods:
        # Final hard-coded fallback: the customer-facing payment flow must not
        # depend on an admin settings row existing or being populated.
        settings.buy_goods_till = getattr(Config, "DENMART_MERCHANT_TILL", "0757817361")
        settings.mode = "BUY_GOODS"
        settings.display_name = settings.display_name or "Denmart"
        settings.instructions = settings.instructions or "Send the exact amount to the Denmart M-PESA Till shown below, then wait for approval."
        db.session.add(settings)
        db.session.flush()
        methods = enabled_methods(settings)
    if not methods:
        raise ValueError("Payment destination is unavailable.")
    method = (payment_method or methods[0]).upper()
    if method not in methods:
        raise ValueError("Choose one of the available payment methods.")

    prepared = []
    if items:
        calculated = Decimal("0")
        for raw in items:
            sp_id = str(raw.get("store_product_id") or raw.get("id") or "").strip()
            try:
                qty = Decimal(str(raw.get("quantity") or raw.get("qty") or 0))
            except InvalidOperation:
                raise ValueError("Invalid item quantity.")
            if qty <= 0 or not sp_id:
                raise ValueError("Invalid basket item.")
            sp = StoreProduct.query.filter_by(id=sp_id, store_id=store_id).with_for_update().first()
            if not sp or not sp.is_available or not sp.available_online:
                raise ValueError("One of the selected items is no longer available.")
            available = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(sp.reserved_quantity or 0))
            if available < qty:
                raise ValueError(f"Not enough stock for {sp.product.name}.")
            unit_price = Decimal(str(sp.selling_price)).quantize(TWOPLACES)
            line = (unit_price * qty).quantize(TWOPLACES)
            calculated += line
            prepared.append((sp, qty, unit_price, line))
        if calculated.quantize(TWOPLACES) != total:
            total = calculated.quantize(TWOPLACES)
    snapshot = payment_instruction_snapshot(settings, method)
    reference = make_reference()
    order = PayOrder(
        business_id=business_id,
        store_id=store_id,
        public_token=make_public_token(),
        reference=reference,
        channel=(channel or "ONLINE").upper(),
        customer_name=name,
        customer_name_normalized=name_norm,
        customer_phone=phone_norm,
        expected_amount=total,
        payment_method=method,
        payment_instructions=snapshot,
        payment_status="PENDING",
        fulfillment_status="AWAITING_PAYMENT",
        created_at=now(),
        expires_at=now() + timedelta(minutes=30),
    )
    db.session.add(order)
    db.session.flush()
    for sp, qty, unit_price, line in prepared:
        db.session.add(PayOrderItem(
            payment_order_id=order.id,
            store_product_id=sp.id,
            product_id=sp.product_id,
            product_name_snapshot=sp.product.name,
            quantity=qty,
            unit_price=unit_price,
            line_total=line,
        ))
    db.session.add(PayEvent(payment_order_id=order.id, event_type="CREATED", source=order.channel, note="Payment request created."))
    db.session.commit()
    return order


def process_gateway_receipt(*, business_id, transaction_code, amount, payer_name, phone, received_at, device_id, sim_slot, sender, message, telemetry_id=None):
    code = str(transaction_code or "").strip().upper()[:40]
    total = normalize_amount(amount)
    name = str(payer_name or "").strip()[:160]
    name_norm = normalize_name(name)
    phone_norm = normalize_phone(phone)
    received_at = received_at or now()
    if not code or total is None or not phone_norm or not name_norm:
        return {"classification": "PAYMENT_UNMATCHED", "matched": False, "reason": "INVALID_PARSED_FIELDS"}

    # Transaction code is the immutable de-duplication key.
    existing = PayReceipt.query.filter_by(transaction_code=code).with_for_update().first()
    if existing:
        return {"classification": "DUPLICATE", "matched": False, "duplicate": True, "payment_order_id": existing.matched_payment_order_id}

    # First build the exact phone+amount pool. This prevents amount-only or
    # name-only approvals and keeps every auto-approval tied to the customer's
    # actual payment request.
    candidates = (PayOrder.query.filter(
        PayOrder.business_id == business_id,
        PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"]),
        PayOrder.customer_phone == phone_norm,
        PayOrder.expected_amount == total,
        or_(PayOrder.expires_at.is_(None), PayOrder.expires_at > now()),
    ).with_for_update().all())

    name_candidates = [o for o in candidates if o.customer_name_normalized == name_norm]
    order = None
    phone_orders = []
    classification = "PAYMENT_UNMATCHED"
    method = "NO_SAFE_EXACT_MATCH"
    reason = "No safe exact pending match."

    # Highest priority: name + phone + exact amount. If there is one unique
    # match, approve immediately even when another payment shares the phone+amount.
    if len(name_candidates) == 1:
        order = name_candidates[0]
        classification = "PAYMENT_MATCHED"
        method = "NAME_PHONE_AND_AMOUNT"
        reason = "Exact normalized M-PESA name, phone and amount match."
    elif len(name_candidates) > 1:
        classification = "PAYMENT_AMBIGUOUS"
        method = "MULTIPLE_NAME_PHONE_AMOUNT"
        reason = "More than one pending payment has the same normalized name, phone and amount."
    elif len(candidates) == 1:
        # Safe fallback required by the payment contract: a unique exact phone+
        # amount candidate cannot be blocked by harmless name formatting/provider text.
        order = candidates[0]
        classification = "PAYMENT_MATCHED"
        method = "PHONE_AND_AMOUNT"
        reason = "Exactly one eligible pending payment matches the normalized phone and exact amount."
    elif len(candidates) > 1:
        classification = "PAYMENT_AMBIGUOUS"
        method = "MULTIPLE_PHONE_AND_AMOUNT"
        reason = "More than one pending payment has the same phone and amount; manual selection is required."
    else:
        # Nothing matched the exact amount. A phone-only lookup is used only to
        # classify an under/over payment; it can never auto-approve.
        phone_orders = (PayOrder.query.filter(
            PayOrder.business_id == business_id,
            PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"]),
            PayOrder.customer_phone == phone_norm,
            or_(PayOrder.expires_at.is_(None), PayOrder.expires_at > now()),
        ).with_for_update().all())
        if len(phone_orders) == 1:
            order = phone_orders[0]
            expected = normalize_amount(order.expected_amount)
            if expected is not None and total < expected:
                classification, method, reason = "UNDERPAYMENT", "PHONE_MATCH_AMOUNT_LOW", "Received amount is below the pending amount."
            elif expected is not None and total > expected:
                classification, method, reason = "OVERPAYMENT", "PHONE_MATCH_AMOUNT_HIGH", "Received amount is above the pending amount."
            else:
                classification, method, reason = "PAYMENT_UNMATCHED", "SAFE_MATCH_FAILED", "Payment details did not pass the safe match path."
        elif len(phone_orders) > 1:
            classification, method, reason = "PAYMENT_AMBIGUOUS", "MULTIPLE_PHONE_CANDIDATES", "More than one pending payment belongs to this phone number."

    candidate_ids = [o.id for o in (candidates or [])]
    if phone_orders:
        candidate_ids = [o.id for o in phone_orders]

    receipt = PayReceipt(
        business_id=business_id,
        transaction_code=code,
        amount=total,
        payer_name=name,
        payer_name_normalized=name_norm,
        payer_phone=phone_norm,
        received_at=received_at,
        gateway_device_id=str(device_id or "android-gateway")[:120],
        sim_slot=int(sim_slot or 0),
        sender=str(sender or "")[:120],
        raw_message=str(message or "")[:12000],
        gateway_telemetry_id=telemetry_id,
        classification=classification,
        matching_method=method,
        matched_payment_order_id=order.id if classification in {"PAYMENT_MATCHED", "NAME_MISMATCH", "UNDERPAYMENT", "OVERPAYMENT", "PHONE_MISMATCH", "STOCK_CONFLICT"} and order else None,
        candidate_payment_order_ids=candidate_ids or None,
        processed_at=now(),
    )
    db.session.add(receipt)

    if order and classification == "PAYMENT_MATCHED":
        # Lock the live order and stock rows, then settle the payment and receipt
        # together so a successful approval cannot exist without its audit record.
        live_order = PayOrder.query.filter_by(id=order.id).with_for_update().first()
        if live_order and live_order.payment_status in {"PENDING", "MANUAL_REVIEW"}:
            for line in PayOrderItem.query.filter_by(payment_order_id=live_order.id).all():
                sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
                available = Decimal(str(sp.stock_quantity or 0)) if sp else Decimal("-1")
                if not sp or available < Decimal(str(line.quantity)):
                    live_order.payment_status = "MANUAL_REVIEW"
                    live_order.review_reason = "STOCK_CONFLICT_AFTER_PAYMENT"
                    live_order.last_match_note = "Payment matched, but stock changed before settlement; administrator review required."
                    classification = "STOCK_CONFLICT"
                    receipt.classification = classification
                    receipt.matching_method = "EXACT_MATCH_STOCK_CONFLICT"
                    db.session.add(PayEvent(payment_order_id=live_order.id, event_type="REVIEW_REQUIRED", source="ANDROID_GATEWAY", note=live_order.last_match_note))
                    db.session.commit()
                    return {"classification": classification, "matched": False, "payment_order_id": live_order.id, "reason": live_order.last_match_note, "method": method}
            for line in PayOrderItem.query.filter_by(payment_order_id=live_order.id).all():
                sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
                sp.stock_quantity = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(line.quantity))
                db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id, transaction_type="ONLINE_PAYMENT", quantity=-Decimal(str(line.quantity)), unit_cost=sp.cost_price, reference_type="PAY_ORDER", reference_id=live_order.id))
            live_order.payment_status = "PAID"
            live_order.fulfillment_status = "PACKAGING"
            live_order.mpesa_transaction_code = code
            live_order.paid_amount = total
            live_order.paid_name = name
            live_order.paid_phone = phone_norm
            live_order.paid_at = received_at
            live_order.paid_source = "ANDROID_GATEWAY_AUTO"
            live_order.matched_by = method
            live_order.review_reason = None
            live_order.last_match_note = reason
            receipt.matched_payment_order_id = live_order.id
            db.session.add(PayEvent(payment_order_id=live_order.id, event_type="AUTO_APPROVED", source="ANDROID_GATEWAY", note=reason))
    elif order:
        order.review_reason = reason
        order.last_match_note = reason
        if order.payment_status == "PENDING" and classification in {"UNDERPAYMENT", "OVERPAYMENT", "PAYMENT_AMBIGUOUS", "PAYMENT_UNMATCHED"}:
            order.payment_status = "MANUAL_REVIEW"
        db.session.add(PayEvent(payment_order_id=order.id, event_type="MATCH_REVIEW", source="ANDROID_GATEWAY", note=reason))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = PayReceipt.query.filter_by(transaction_code=code).first()
        if existing:
            return {"classification": "DUPLICATE", "matched": False, "duplicate": True, "payment_order_id": existing.matched_payment_order_id}
        raise

    return {
        "classification": classification,
        "matched": classification == "PAYMENT_MATCHED",
        "payment_order_id": order.id if order else None,
        "reason": reason,
        "method": method,
    }


def manual_approve(order, actor_id, reason="Manual approval"):
    if order.payment_status == "PAID":
        return False, "Already paid."
    if order.payment_status not in {"PENDING", "MANUAL_REVIEW"}:
        return False, "This payment is no longer awaiting approval."
    for line in PayOrderItem.query.filter_by(payment_order_id=order.id).all():
        sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
        available = Decimal(str(sp.stock_quantity or 0)) if sp else Decimal("-1")
        if not sp or available < Decimal(str(line.quantity)):
            return False, "Stock changed while waiting; resolve stock before approving."
    for line in PayOrderItem.query.filter_by(payment_order_id=order.id).all():
        sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
        sp.stock_quantity = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(line.quantity))
        db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id, transaction_type="MANUAL_PAYMENT", quantity=-Decimal(str(line.quantity)), unit_cost=sp.cost_price, reference_type="PAY_ORDER", reference_id=order.id, created_by=actor_id))
    receipt = (PayReceipt.query.filter_by(matched_payment_order_id=order.id)
               .order_by(PayReceipt.created_at.desc()).first())
    if receipt and receipt.transaction_code:
        order.mpesa_transaction_code = receipt.transaction_code
        order.paid_amount = receipt.amount
        order.paid_name = receipt.payer_name
        order.paid_phone = receipt.payer_phone
        order.paid_at = receipt.received_at
        receipt.classification = "MANUAL_APPROVED"
        receipt.matching_method = "ADMIN_REVIEW"
    order.payment_status = "PAID"
    order.fulfillment_status = "PACKAGING"
    order.paid_at = order.paid_at or now()
    order.paid_source = "ADMIN_MANUAL"
    order.manual_approved_by = actor_id
    order.manual_approved_at = now()
    order.review_reason = None
    order.last_match_note = reason[:1000]
    db.session.add(PayEvent(payment_order_id=order.id, event_type="MANUAL_APPROVED", source="ADMIN", actor_user_id=actor_id, note=reason[:1000]))
    db.session.commit()
    return True, "Approved manually."


def set_fulfillment(order, status, actor_id):
    allowed = {"PACKAGING", "READY", "DISPATCHED", "COMPLETED"}
    status = (status or "").upper()
    if order.payment_status != "PAID":
        raise ValueError("Payment must be approved before fulfillment can move forward.")
    if status not in allowed:
        raise ValueError("Invalid fulfillment status.")
    order.fulfillment_status = status
    db.session.add(PayEvent(payment_order_id=order.id, event_type=f"FULFILLMENT_{status}", source="ADMIN", actor_user_id=actor_id, note=f"Fulfillment moved to {status}."))
    db.session.commit()
