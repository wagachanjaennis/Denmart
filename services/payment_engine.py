from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from extensions import db
from models import PayOrder, PayOrderItem, PayReceipt, PaySettings, PayEvent, StoreProduct, InventoryTransaction, Sale, SaleItem, User, now

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
        # Keep checkout operational even when the settings row was created by an older release.
        if not row.buy_goods_till:
            from config import Config
            row.buy_goods_till = getattr(Config, "DENMART_MERCHANT_TILL", "0757817361")
            if not row.mode or row.mode.upper() == "PAYBILL" and not row.paybill_number:
                row.mode = "BUY_GOODS"
            db.session.add(row)
            db.session.flush()
        return row
    if not create:
        return None
    from os import getenv
    from config import Config
    row = PaySettings(
        business_id=business_id,
        mode="BUY_GOODS",
        paybill_number=(getenv("PAYBILL_NUMBER", "") or "").strip(),
        paybill_account_name=(getenv("PAYBILL_ACCOUNT_NAME", "Denmart") or "Denmart").strip(),
        buy_goods_till=(getenv("BUY_GOODS_TILL", "") or "").strip() or getattr(Config, "DENMART_MERCHANT_TILL", "0757817361"),
        display_name=(getenv("PAYMENT_DISPLAY_NAME", "Denmart") or "Denmart").strip(),
        instructions=(getenv("PAYMENT_INSTRUCTIONS", "Pay using the Buy Goods Till shown below, then wait on this page for approval.") or "").strip(),
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


def create_payment_order(*, business_id, store_id, customer_name, phone, amount, items=None, channel="ONLINE", payment_method=None, pos_cashier_id=None):
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
        from config import Config
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
        pos_cashier_id=(str(pos_cashier_id).strip() if pos_cashier_id else None),
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


def _utc(value):
    """Return a timezone-aware UTC datetime for old/new PostgreSQL timestamp rows."""
    if value is None:
        return None
    from datetime import timezone
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)



def _get_or_create_pos_sale(order):
    """Create the actual POS sale exactly once after its payment is approved."""
    if (order.channel or "").upper() != "POS":
        return None
    receipt_number = f"POS-{order.reference}"[:60]
    existing = Sale.query.filter_by(receipt_number=receipt_number).with_for_update().first()
    if existing:
        return existing
    cashier_id = order.pos_cashier_id
    if not cashier_id:
        fallback = (User.query.filter(
            User.business_id == order.business_id,
            User.store_id == order.store_id,
            User.is_active.is_(True),
        ).order_by(User.created_at.asc()).first())
        if not fallback:
            raise ValueError("No active POS cashier is available to complete the sale.")
        cashier_id = fallback.id
    items = PayOrderItem.query.filter_by(payment_order_id=order.id).order_by(PayOrderItem.product_name_snapshot).all()
    if not items:
        raise ValueError("POS payment has no sale items.")
    total = normalize_amount(order.expected_amount) or Decimal("0.00")
    sale = Sale(
        business_id=order.business_id,
        store_id=order.store_id,
        cashier_id=cashier_id,
        receipt_number=receipt_number,
        subtotal=total,
        discount=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=total,
        status="COMPLETED",
        completed_at=now(),
    )
    db.session.add(sale)
    db.session.flush()
    for line in items:
        db.session.add(SaleItem(
            sale_id=sale.id,
            product_id=line.product_id,
            product_name_snapshot=line.product_name_snapshot,
            barcode_snapshot=None,
            unit_price=line.unit_price,
            quantity=line.quantity,
            discount=Decimal("0.00"),
            tax=Decimal("0.00"),
            line_total=line.line_total,
        ))
    return sale


def get_pos_sale_for_order(order):
    if (order.channel or "").upper() != "POS":
        return None
    return Sale.query.filter_by(receipt_number=f"POS-{order.reference}"[:60]).first()


def process_gateway_receipt(*, business_id, transaction_code, amount, payer_name, phone, received_at, device_id, sim_slot, sender, message, telemetry_id=None):
    code = str(transaction_code or "").strip().upper()[:40]
    total = normalize_amount(amount)
    name = str(payer_name or "").strip()[:160]
    name_norm = normalize_name(name)
    phone_norm = normalize_phone(phone)
    if not code or total is None or not phone_norm:
        return {"classification": "PAYMENT_UNMATCHED", "matched": False, "reason": "INVALID_PARSED_FIELDS"}

    existing = PayReceipt.query.filter_by(transaction_code=code).with_for_update().first()
    if existing:
        return {"classification": "DUPLICATE", "matched": False, "duplicate": True, "payment_order_id": existing.matched_payment_order_id}

    # Primary safe lookup: exact normalized phone + exact amount among live pending requests.
    candidates = (PayOrder.query.filter(
        PayOrder.business_id == business_id,
        PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"]),
        PayOrder.customer_phone == phone_norm,
        PayOrder.expected_amount == total,
    ).with_for_update().all())

    # Expiry is normalized in Python because old DB rows may come back timezone-naive.
    live_candidates = []
    current = now()
    for candidate in candidates:
        expires = _utc(candidate.expires_at)
        if expires is None or expires > current:
            live_candidates.append(candidate)
    candidates = live_candidates

    order = None
    classification = "PAYMENT_UNMATCHED"
    method = "NO_SAFE_EXACT_MATCH"
    reason = "No safe exact pending match."

    if len(candidates) > 1:
        # Never guess when identical phone + amount requests exist.
        classification = "PAYMENT_AMBIGUOUS"
        method = "MULTIPLE_PHONE_AND_AMOUNT"
        reason = "More than one pending payment has the same phone and amount."
    elif len(candidates) == 1:
        order = candidates[0]
        if name_norm and order.customer_name_normalized == name_norm:
            method = "NAME_PHONE_AND_AMOUNT"
            reason = "Exact normalized M-PESA name + phone + amount match."
        else:
            # Safe fallback requested by the business: a single exact phone + amount
            # identifies the payment even when the payer-name spelling/format differs.
            method = "PHONE_AND_AMOUNT"
            reason = "One exact pending phone + amount candidate; payer name kept as supporting review data."
        classification = "PAYMENT_MATCHED"
    else:
        # Amount mismatch path.
        phone_orders = (PayOrder.query.filter(
            PayOrder.business_id == business_id,
            PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"]),
            PayOrder.customer_phone == phone_norm,
        ).with_for_update().all())
        live_phone_orders = []
        for candidate in phone_orders:
            expires = _utc(candidate.expires_at)
            if expires is None or expires > current:
                live_phone_orders.append(candidate)
        phone_orders = live_phone_orders
        if len(phone_orders) == 1:
            order = phone_orders[0]
            expected = normalize_amount(order.expected_amount)
            if expected is not None and total < expected:
                classification, method, reason = "UNDERPAYMENT", "PHONE_MATCH_AMOUNT_LOW", "Received amount is below the pending amount."
            elif expected is not None and total > expected:
                classification, method, reason = "OVERPAYMENT", "PHONE_MATCH_AMOUNT_HIGH", "Received amount is above the pending amount."
        elif len(phone_orders) > 1:
            classification, method, reason = "PAYMENT_AMBIGUOUS", "MULTIPLE_PHONE_CANDIDATES", "More than one pending payment belongs to this phone number."

    candidate_ids = [o.id for o in candidates]
    if classification in {"UNDERPAYMENT", "OVERPAYMENT", "PAYMENT_UNMATCHED"} and order:
        candidate_ids = [order.id]

    receipt = PayReceipt(
        business_id=business_id,
        transaction_code=code,
        amount=total,
        payer_name=name or None,
        payer_name_normalized=name_norm or None,
        payer_phone=phone_norm,
        received_at=received_at or now(),
        gateway_device_id=str(device_id or "android-gateway")[:120],
        sim_slot=int(sim_slot or 0),
        sender=str(sender or "")[:120],
        raw_message=str(message or "")[:12000],
        gateway_telemetry_id=telemetry_id,
        classification=classification,
        matching_method=method,
        matched_payment_order_id=order.id if classification in {"PAYMENT_MATCHED", "UNDERPAYMENT", "OVERPAYMENT"} and order else None,
        candidate_payment_order_ids=candidate_ids or None,
        processed_at=now(),
    )
    db.session.add(receipt)

    if order and classification == "PAYMENT_MATCHED":
        # Receipt recording + settlement occur in the same transaction.
        live_order = PayOrder.query.filter_by(id=order.id).with_for_update().first()
        if not live_order or live_order.payment_status not in {"PENDING", "MANUAL_REVIEW"}:
            db.session.rollback()
            return {"classification": "DUPLICATE_OR_ALREADY_PROCESSED", "matched": False, "payment_order_id": order.id}
        for line in PayOrderItem.query.filter_by(payment_order_id=live_order.id).all():
            sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
            available = Decimal(str(sp.stock_quantity or 0)) if sp else Decimal("-1")
            if not sp or available < Decimal(str(line.quantity)):
                live_order.payment_status = "MANUAL_REVIEW"
                live_order.review_reason = "STOCK_CONFLICT_AFTER_PAYMENT"
                live_order.last_match_note = "Payment matched, but stock changed before settlement; administrator review required."
                receipt.classification = "STOCK_CONFLICT"
                receipt.matching_method = method + "_STOCK_CONFLICT"
                db.session.add(PayEvent(payment_order_id=live_order.id, event_type="REVIEW_REQUIRED", source="ANDROID_GATEWAY", note=live_order.last_match_note))
                db.session.commit()
                return {"classification": "STOCK_CONFLICT", "matched": False, "payment_order_id": live_order.id, "reason": live_order.last_match_note}
        for line in PayOrderItem.query.filter_by(payment_order_id=live_order.id).all():
            sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
            sp.stock_quantity = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(line.quantity))
            db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id, transaction_type="ONLINE_PAYMENT" if (live_order.channel or "").upper() != "POS" else "POS_PAYMENT", quantity=-Decimal(str(line.quantity)), unit_cost=sp.cost_price, reference_type="PAY_ORDER", reference_id=live_order.id))
        pos_sale = _get_or_create_pos_sale(live_order)
        live_order.payment_status = "PAID"
        live_order.fulfillment_status = "PACKAGING"
        live_order.mpesa_transaction_code = code
        live_order.paid_amount = total
        live_order.paid_name = name or None
        live_order.paid_phone = phone_norm
        live_order.paid_at = received_at or now()
        live_order.paid_source = "ANDROID_GATEWAY_AUTO"
        live_order.matched_by = method
        live_order.review_reason = None
        live_order.last_match_note = reason
        receipt.matched_payment_order_id = live_order.id
        if pos_sale:
            live_order.last_match_note = reason + " POS sale completed automatically."
        db.session.add(PayEvent(payment_order_id=live_order.id, event_type="AUTO_APPROVED", source="ANDROID_GATEWAY", note=reason))
    elif order and classification in {"UNDERPAYMENT", "OVERPAYMENT"}:
        order.payment_status = "MANUAL_REVIEW"
        order.review_reason = reason
        order.last_match_note = reason
        db.session.add(PayEvent(payment_order_id=order.id, event_type="MATCH_REVIEW", source="ANDROID_GATEWAY", note=reason))
    elif classification == "PAYMENT_AMBIGUOUS":
        for candidate in candidates[:1]:
            candidate.last_match_note = reason
            db.session.add(PayEvent(payment_order_id=candidate.id, event_type="AMBIGUOUS_RECEIPT", source="ANDROID_GATEWAY", note=reason))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = PayReceipt.query.filter_by(transaction_code=code).first()
        if existing:
            return {"classification": "DUPLICATE", "matched": False, "duplicate": True, "payment_order_id": existing.matched_payment_order_id}
        raise

    return {"classification": classification, "matched": classification == "PAYMENT_MATCHED", "payment_order_id": order.id if order else None, "reason": reason, "method": method}



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
    pos_sale = _get_or_create_pos_sale(order)
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
