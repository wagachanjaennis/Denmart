from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

from extensions import db
from models import (
    AutoPaymentReceipt, Customer, GatewaySmsMessage, Order, OrderItem,
    Payment, PaymentGatewayEvent, Sale, SaleItem, Store, SystemSetting, now,
)


OPEN_ORDER_PAYMENT_STATUSES = {"UNPAID", "PENDING_APPROVAL"}
OPEN_ORDER_STATUSES = {"PENDING", "PROCESSING", "CONFIRMED"}
OPEN_SALE_PAYMENT_STATUSES = {"UNPAID", "PENDING_APPROVAL"}
CANCELLED_STATUSES = {"CANCELLED", "DELETED", "EXPIRED", "VOID", "VOIDED"}


# ---------------------------------------------------------------------------
# Pure normalization/parsing helpers. These are deliberately independent of
# the legacy matcher and do not consult historical scores or time windows.
# ---------------------------------------------------------------------------


def normalize_ke_phone(value):
    """Return one canonical Kenyan mobile form: 2547XXXXXXXX / 2541XXXXXXXX."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("254") and len(digits) == 12 and digits[3] in "17":
        return digits
    if digits.startswith("0") and len(digits) == 10 and digits[1] in "17":
        return "254" + digits[1:]
    if digits.startswith("7") and len(digits) == 9:
        return "254" + digits
    if digits.startswith("1") and len(digits) == 9:
        return "254" + digits
    return None


def normalize_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def parse_amount(message):
    text = str(message or "")
    patterns = (
        r"\b(?:KSH|KSHS|KES)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b",
        r"\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:KSH|KSHS|KES)\b",
    )
    for line in re.split(r"[\r\n]+", text):
        upper = line.upper()
        if "RECEIVED" not in upper and "CREDITED" not in upper:
            continue
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                try:
                    value = Decimal(match.group(1).replace(",", ""))
                    if value > 0:
                        return value.quantize(Decimal("0.01"))
                except InvalidOperation:
                    pass

    # Some SMS variants put the amount and the word "received" in a different
    # order or wrap the receipt over multiple lines.
    fallback_patterns = (
        r"(?:received|credited).*?\b(?:ksh|kshs|kes)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b",
        r"\b(?:ksh|kshs|kes)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b.*?(?:received|credited)",
    )
    for pattern in fallback_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                value = Decimal(match.group(1).replace(",", ""))
                if value > 0:
                    return value.quantize(Decimal("0.01"))
            except InvalidOperation:
                pass
    return None


def parse_transaction(message):
    """Extract an M-PESA confirmation code without mistaking random words for it."""
    text = str(message or "").upper()
    patterns = (
        r"(?:^|\s)(?=[A-Z0-9]{8,20}\s+CONFIRMED)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])([A-Z0-9]{8,20})\s+CONFIRMED(?:\.|\s|$)",
        r"\bCONFIRMED[.\s:-]+(?=[A-Z0-9]{8,20}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])([A-Z0-9]{8,20})\b",
        r"\b(?:TRANSACTION(?:\s+CODE)?|RECEIPT|CONFIRMATION)[:\s-]+(?=[A-Z0-9]{8,20}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])([A-Z0-9]{8,20})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip().upper()
    return None


def parse_phone(message):
    text = str(message or "")
    for pattern in (
        r"(?<!\w)(\+?254(?:7|1)\d{8})(?!\w)",
        r"(?<!\w)(0(?:7|1)\d{8})(?!\w)",
        r"(?<!\w)((?:7|1)\d{8})(?!\w)",
    ):
        match = re.search(pattern, text)
        if match:
            normalized = normalize_ke_phone(match.group(1))
            if normalized:
                return normalized
    return None


def parse_name(message):
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    match = re.search(
        r"\b(?:RECEIVED|CREDITED)\b.*?\b(?:FROM|BY)\s+(.+?)(?=\s+(?:ON BEHALF|FOR ACCOUNT|ACCOUNT|AT\s+\d|ON\s+\d|NEW BALANCE|ACCOUNT BALANCE|BALANCE IS|AVAILABLE BALANCE|RECEIPT|TRANSACTION|\+?254|0(?:7|1)\d{8}\b|(?:7|1)\d{8}\b)|\s*$)",
        text, re.IGNORECASE,
    )
    if not match:
        return ""
    value = match.group(1).strip(" .,-")
    value = re.sub(
        r"^(?:AIRTEL\s+MONEY|AIRTEL|M[-\s]?PESA|SAFARICOM)\s*[-:|]+\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value[:240]


def is_mpesa(message, sender):
    sender_up = re.sub(r"\s+", "", str(sender or "")).upper()
    upper = str(message or "").upper()
    if sender_up and not any(x in sender_up for x in ("MPESA", "M-PESA", "SAFARICOM")):
        return False
    return bool(
        re.search(r"\b(?:RECEIVED|CREDITED)\b", upper)
        and parse_amount(message) is not None
        and parse_transaction(message)
    )


# ---------------------------------------------------------------------------
# Candidate collection. Only currently payable entities are considered.
# ---------------------------------------------------------------------------


def _gateway_store(business_id, sim_slot):
    setting = SystemSetting.query.filter_by(
        business_id=business_id,
        key=f"payment_gateway_sim_{sim_slot}_store_id",
    ).first()
    if setting and setting.value:
        store = db.session.get(Store, setting.value)
        if store and store.business_id == business_id and store.is_active:
            return store
    stores = Store.query.filter_by(
        business_id=business_id, is_active=True
    ).order_by(Store.created_at).all()
    return stores[0] if len(stores) == 1 else None


def _order_phone(order):
    customer = db.session.get(Customer, order.customer_id) if order.customer_id else None
    return normalize_ke_phone(customer.phone if customer else None)


def _sale_phone_map(sale_ids):
    if not sale_ids:
        return {}
    rows = (
        Payment.query.filter(
            Payment.sale_id.in_(sale_ids),
            Payment.status.in_({"PENDING", "PENDING_APPROVAL"}),
            Payment.method.in_({
                "MPESA", "MPESA_TILL", "MPESA_GATEWAY_INTENT", "MPESA_GATEWAY",
            }),
        )
        .order_by(Payment.created_at.desc())
        .all()
    )
    out = {}
    for row in rows:
        if row.sale_id not in out:
            out[row.sale_id] = normalize_ke_phone(row.phone_number)
    return out


def _eligible_candidates(business_id, store_id=None):
    """Return only open online/POS entities. No history, scores, or time windows."""
    candidates = []

    orders = Order.query.filter(
        Order.business_id == business_id,
        Order.payment_status.in_(OPEN_ORDER_PAYMENT_STATUSES),
        Order.status.in_(OPEN_ORDER_STATUSES),
        ~Order.status.in_(CANCELLED_STATUSES),
    )
    if store_id:
        orders = orders.filter(Order.store_id == store_id)
    for order in orders.order_by(Order.created_at.desc()).all():
        phone = _order_phone(order)
        if phone:
            candidates.append({
                "kind": "ORDER",
                "entity": order,
                "id": order.id,
                "phone": phone,
                "amount": Decimal(str(order.total or 0)).quantize(Decimal("0.01")),
            })

    sales = Sale.query.filter(
        Sale.business_id == business_id,
        Sale.payment_status.in_(OPEN_SALE_PAYMENT_STATUSES),
        ~Sale.status.in_(CANCELLED_STATUSES),
    )
    if store_id:
        sales = sales.filter(Sale.store_id == store_id)
    sale_rows = sales.order_by(Sale.created_at.desc()).all()
    phones = _sale_phone_map([sale.id for sale in sale_rows])
    for sale in sale_rows:
        phone = phones.get(sale.id)
        if phone:
            candidates.append({
                "kind": "SALE",
                "entity": sale,
                "id": sale.id,
                "phone": phone,
                "amount": Decimal(str(sale.total or 0)).quantize(Decimal("0.01")),
            })
    return candidates


def _close_old_open_payments(entity):
    entity_filter = (
        Payment.order_id == entity.id
        if isinstance(entity, Order)
        else Payment.sale_id == entity.id
    )
    rows = Payment.query.filter(
        entity_filter,
        Payment.status.in_({"PENDING", "PENDING_APPROVAL"}),
        Payment.method.in_({
            "MPESA", "MPESA_TILL_INTENT", "MPESA_TILL", "MPESA_GATEWAY_INTENT", "MPESA_GATEWAY",
        }),
    ).all()
    for row in rows:
        row.status = "CLOSED_AUTO"
        row.failure_message = (
            "Closed because the independent /pay live M-PESA automation settled this payment."
        )


def _create_paid_payment(candidate, receipt):
    """Create the one new paid ledger row and mark the matched entity paid.

    This function intentionally does not call the legacy settlement or Daraja code.
    Inventory/loyalty side effects are left to the existing fulfillment/accounting flows.
    """
    entity = candidate["entity"]
    payment = Payment(
        business_id=entity.business_id,
        store_id=entity.store_id,
        order_id=entity.id if isinstance(entity, Order) else None,
        sale_id=entity.id if isinstance(entity, Sale) else None,
        provider="SAFARICOM",
        method="MPESA_TILL",
        amount=receipt.amount,
        currency="KES",
        status="PAID",
        external_reference=receipt.transaction_code,
        provider_transaction_id=receipt.transaction_code,
        phone_number=receipt.normalized_phone,
        raw_provider_reference=receipt.raw_message[:12000],
        completed_at=now(),
    )
    db.session.add(payment)
    db.session.flush()

    if isinstance(entity, Order):
        entity.payment_status = "PAID"
        entity.status = "CONFIRMED"
    else:
        entity.payment_status = "PAID"
        entity.status = "COMPLETED"
        entity.completed_at = now()

    _close_old_open_payments(entity)
    return payment


def classify_match(receipt_phone, receipt_amount, candidates):
    """Pure deterministic decision: PHONE + EXACT AMOUNT is the only auto-approve rule."""
    exact = [c for c in candidates if c["phone"] == receipt_phone and c["amount"] == receipt_amount]
    if len(exact) == 1:
        return "AUTO_APPROVED", "PHONE_AND_EXACT_AMOUNT", exact[0]
    if len(exact) > 1:
        return "PAYMENT_AMBIGUOUS", "PHONE_AND_EXACT_AMOUNT_MULTIPLE", None

    phone_matches = [c for c in candidates if c["phone"] == receipt_phone]
    if len(phone_matches) == 1:
        expected = phone_matches[0]["amount"]
        if receipt_amount < expected:
            return "UNDERPAYMENT", "PHONE_MATCH_AMOUNT_MISMATCH", phone_matches[0]
        if receipt_amount > expected:
            return "OVERPAYMENT", "PHONE_MATCH_AMOUNT_MISMATCH", phone_matches[0]
    if len(phone_matches) > 1:
        return "PAYMENT_AMBIGUOUS", "PHONE_MATCH_MULTIPLE_OPEN_PAYMENTS", None
    return "PAYMENT_UNMATCHED", "NO_PHONE_AND_AMOUNT_MATCH", None


def _existing_auto_receipt(business_id, transaction_code):
    if not transaction_code:
        return None
    return AutoPaymentReceipt.query.filter_by(
        business_id=business_id,
        transaction_code=transaction_code,
    ).first()


def _compat_event(*, business_id, store_id, device_id, sim_slot, subscription_id,
                  source, sender, raw_message, received_at, tx, amount, payer_name, phone,
                  status, matched_payment_id=None, payload=None):
    if tx:
        existing = PaymentGatewayEvent.query.filter_by(
            business_id=business_id, gateway_device_id=device_id, transaction_id=tx
        ).first()
        if existing:
            return existing
    event = PaymentGatewayEvent(
        business_id=business_id,
        store_id=store_id,
        gateway_device_id=device_id,
        sim_slot=sim_slot,
        subscription_id=subscription_id,
        source=source,
        sender=sender,
        message=raw_message[:12000],
        received_at=received_at,
        transaction_id=tx,
        amount=amount,
        customer=payer_name,
        customer_phone=phone,
        status=status,
        matched_payment_id=matched_payment_id,
        raw_payload={**(payload or {}), "auto_pay_path": True},
    )
    db.session.add(event)
    return event


def process_gateway_request(*, business_id, payload, headers=None):
    """Receive one APK event and run the isolated /pay matcher."""
    headers = headers or {}
    payload = payload or {}

    event_id = str(
        headers.get("X-Denmart-Event-Id")
        or payload.get("event_id")
        or ""
    ).strip()[:160]
    device_id = str(
        headers.get("X-Denmart-Gateway-Id")
        or payload.get("gateway_device_id")
        or ""
    ).strip()[:120]
    raw_message = str(
        payload.get("raw_message")
        or payload.get("sms_body")
        or payload.get("receipt")
        or payload.get("message")
        or ""
    ).strip()
    sender = str(
        payload.get("sender")
        or payload.get("originating_address")
        or ""
    ).strip()[:120]
    source = str(payload.get("source") or "android_sms_listener").strip()[:40]

    if not event_id or not device_id or not raw_message:
        return {"ok": False, "error": "event_id_device_id_raw_message_required"}, 400

    try:
        sim_slot = max(0, min(1, int(payload.get("sim_slot", 0))))
    except (TypeError, ValueError):
        sim_slot = 0

    try:
        subscription_id = (
            int(payload.get("subscription_id"))
            if str(payload.get("subscription_id") or "").isdigit()
            else None
        )
    except (TypeError, ValueError):
        subscription_id = None

    try:
        received_at = (
            datetime.fromtimestamp(int(payload.get("received_at")) / 1000, tz=timezone.utc)
            if payload.get("received_at")
            else now()
        )
    except Exception:
        received_at = now()

    existing_event = GatewaySmsMessage.query.filter_by(
        business_id=business_id,
        gateway_device_id=device_id,
        event_id=event_id,
    ).first()
    if existing_event:
        existing_event.last_seen_at = now()
        existing_receipt = AutoPaymentReceipt.query.filter_by(
            business_id=business_id,
            gateway_device_id=device_id,
            event_id=event_id,
        ).first()
        db.session.commit()
        return {
            "ok": True,
            "duplicate": True,
            "event_id": event_id,
            "receipt_id": existing_receipt.id if existing_receipt else None,
            "classification": existing_receipt.classification if existing_receipt else "LIVE_RECEIVED",
        }, 200

    candidate = is_mpesa(raw_message, sender)
    amount = parse_amount(raw_message) if candidate else None
    tx = parse_transaction(raw_message) if candidate else None
    phone = parse_phone(raw_message) if candidate else None
    payer_name = normalize_name(parse_name(raw_message)) if candidate else ""
    store = _gateway_store(business_id, sim_slot)
    store_id = store.id if store else None

    telemetry = GatewaySmsMessage(
        business_id=business_id,
        gateway_device_id=device_id,
        event_id=event_id,
        sim_slot=sim_slot,
        subscription_id=subscription_id,
        source=source,
        sender=sender,
        message=raw_message[:12000],
        received_at=received_at,
        is_mpesa_candidate=candidate,
        delivery_status="RECEIVED",
        raw_payload={**payload, "raw_message": raw_message},
    )
    db.session.add(telemetry)

    previous = _existing_auto_receipt(business_id, tx) if candidate and tx else None
    receipt = AutoPaymentReceipt(
        business_id=business_id,
        store_id=store_id,
        gateway_device_id=device_id,
        sim_slot=sim_slot,
        subscription_id=subscription_id,
        event_id=event_id,
        transaction_code=tx,
        amount=amount,
        payer_name=payer_name,
        phone=phone,
        normalized_phone=phone,
        sender=sender,
        raw_message=raw_message[:12000],
        received_at=received_at,
        classification="LIVE_RECEIVED" if not candidate else "PAYMENT_UNMATCHED",
        raw_payload={**payload, "raw_message": raw_message},
    )
    db.session.add(receipt)
    db.session.flush()

    if not candidate or amount is None or not tx:
        receipt.classification = "NOT_MPAYMENT" if not candidate else "PAYMENT_UNMATCHED"
        receipt.matching_method = "RAW_SMS_RECEIVED"
        receipt.processed_at = now()
        telemetry.delivery_status = (
            "IGNORED_FOR_PAYMENTS" if not candidate else "STORED_INCOMPLETE_MPESA"
        )
        event = _compat_event(
            business_id=business_id, store_id=store_id, device_id=device_id,
            sim_slot=sim_slot, subscription_id=subscription_id, source=source,
            sender=sender, raw_message=raw_message, received_at=received_at,
            tx=tx, amount=amount, payer_name=payer_name, phone=phone,
            status="UNMATCHED", payload=payload,
        )
        db.session.flush()
        telemetry.payment_event_id = event.id
        db.session.commit()
        return {
            "ok": True, "receipt_id": receipt.id, "event_id": event_id,
            "classification": receipt.classification, "transaction_code": tx,
            "amount": str(amount) if amount is not None else None,
        }, 200

    # Duplicate protection is anchored in the NEW live receipt ledger. The legacy
    # matcher is never consulted to choose a payment candidate. Duplicate rows are
    # still stored so every received SMS remains auditable.
    if previous:
        receipt.classification = "DUPLICATE_ALREADY_PROCESSED"
        receipt.processed_at = now()
        receipt.matching_method = "TRANSACTION_CODE_ALREADY_SEEN_IN_AUTO_PAY"
        telemetry.delivery_status = "DUPLICATE_PAYMENT_EVENT"
        event = _compat_event(
            business_id=business_id, store_id=store_id, device_id=device_id,
            sim_slot=sim_slot, subscription_id=subscription_id, source=source,
            sender=sender, raw_message=raw_message, received_at=received_at,
            tx=tx, amount=amount, payer_name=payer_name, phone=phone,
            status="UNMATCHED", payload=payload,
        )
        db.session.flush()
        telemetry.payment_event_id = event.id
        db.session.commit()
        return {
            "ok": True, "receipt_id": receipt.id, "event_id": event_id,
            "classification": receipt.classification, "transaction_code": tx,
            "duplicate_of": previous.id,
        }, 200

    candidates = _eligible_candidates(business_id, store_id)
    classification, matching_method, matched_candidate = classify_match(phone, amount, candidates)

    if classification == "AUTO_APPROVED" and matched_candidate:
        candidate = matched_candidate
        # The existing global Payment uniqueness is a second safety net. It cannot
        # influence candidate selection, but it prevents an already-recorded payment
        # from being created twice when an old record happens to carry the same code.
        existing_paid = Payment.query.filter_by(provider_transaction_id=tx).first()
        if existing_paid:
            receipt.classification = "DUPLICATE_ALREADY_PROCESSED"
            receipt.processed_at = now()
            receipt.matching_method = "TRANSACTION_CODE_ALREADY_ON_PAYMENT_LEDGER"
            telemetry.delivery_status = "DUPLICATE_PAYMENT_EVENT"
            event = _compat_event(
                business_id=business_id, store_id=store_id, device_id=device_id,
                sim_slot=sim_slot, subscription_id=subscription_id, source=source,
                sender=sender, raw_message=raw_message, received_at=received_at,
                tx=tx, amount=amount, payer_name=payer_name, phone=phone,
                status="UNMATCHED", payload=payload,
            )
            db.session.flush()
            telemetry.payment_event_id = event.id
            db.session.commit()
            return {
                "ok": True, "receipt_id": receipt.id, "classification": receipt.classification,
                "transaction_code": tx, "duplicate_of": existing_paid.id,
            }, 200

        paid = _create_paid_payment(candidate, receipt)
        receipt.classification = "AUTO_APPROVED"
        receipt.matching_method = "PHONE_AND_EXACT_AMOUNT"
        receipt.matched_order_id = candidate["entity"].id if candidate["kind"] == "ORDER" else None
        receipt.matched_sale_id = candidate["entity"].id if candidate["kind"] == "SALE" else None
        receipt.matched_payment_id = paid.id
        receipt.processed_at = now()
        telemetry.delivery_status = "MATCHED_AND_SETTLED"
        event = _compat_event(
            business_id=business_id, store_id=candidate["entity"].store_id,
            device_id=device_id, sim_slot=sim_slot, subscription_id=subscription_id,
            source=source, sender=sender, raw_message=raw_message,
            received_at=received_at, tx=tx, amount=amount, payer_name=payer_name,
            phone=phone, status="MATCHED", matched_payment_id=paid.id, payload=payload,
        )
        db.session.flush()
        telemetry.payment_event_id = event.id
        db.session.commit()
        return {
            "ok": True, "receipt_id": receipt.id, "classification": receipt.classification,
            "matching_method": receipt.matching_method, "payment_id": paid.id,
            "transaction_code": tx, "amount": str(amount), "phone": phone,
        }, 200

    receipt.classification = classification
    receipt.matching_method = matching_method
    if matched_candidate:
        receipt.matched_order_id = matched_candidate["entity"].id if matched_candidate["kind"] == "ORDER" else None
        receipt.matched_sale_id = matched_candidate["entity"].id if matched_candidate["kind"] == "SALE" else None
    receipt.processed_at = now()
    telemetry.delivery_status = receipt.classification
    event = _compat_event(
        business_id=business_id, store_id=store_id, device_id=device_id, sim_slot=sim_slot,
        subscription_id=subscription_id, source=source, sender=sender, raw_message=raw_message,
        received_at=received_at, tx=tx, amount=amount, payer_name=payer_name, phone=phone,
        status="UNMATCHED", payload={**payload, "classification": receipt.classification},
    )
    db.session.flush()
    telemetry.payment_event_id = event.id

    db.session.commit()
    return {
        "ok": True,
        "receipt_id": receipt.id,
        "classification": receipt.classification,
        "matching_method": receipt.matching_method,
        "transaction_code": tx,
        "amount": str(amount),
        "phone": phone,
    }, 200
