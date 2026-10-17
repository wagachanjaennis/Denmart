from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from extensions import db
from models import PayOrder, PayOrderItem, PayReceipt, PaySettings, PayEvent, StoreProduct, InventoryTransaction, Sale, SaleItem, User, SystemSetting, now

TWOPLACES = Decimal("0.01")


def normalize_phone(value):
    """Canonicalize Kenyan mobile numbers entered as 07…, 01…, 7…, 1…, +254… or 00254…."""
    raw = re.sub(r"\D", "", str(value or "").strip())
    if raw.startswith("00"):
        raw = raw[2:]
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
    if method == "BANK_TRANSFER":
        saved = SystemSetting.query.filter_by(business_id=settings.business_id, key="bank_payment_instructions").first()
        account_name_row = SystemSetting.query.filter_by(business_id=settings.business_id, key="bank_account_name").first()
        account_number_row = SystemSetting.query.filter_by(business_id=settings.business_id, key="bank_account_number").first()
        details = str(saved.value or "").strip() if saved else ""
        account_name = str(account_name_row.value or "").strip() if account_name_row else ""
        account_number = str(account_number_row.value or "").strip() if account_number_row else ""
        if len("".join(ch for ch in account_number if ch.isdigit())) < 6:
            raise ValueError("Configure the bank receiving account number in Admin → PAY before using bank-transfer matching.")
        if not details:
            details = "Transfer to " + (account_name + " · " if account_name else "") + account_number
        return {"method": "BANK_TRANSFER", "label": settings.display_name or "Denmart",
                "account_name": account_name, "account_number": account_number, "instructions": details}
    return {}


def enabled_methods(settings):
    out = []
    mode = (settings.mode or "").upper()
    if mode in {"PAYBILL", "BOTH"} and settings.paybill_number:
        out.append("PAYBILL")
    if mode in {"BUY_GOODS", "BOTH"} and settings.buy_goods_till:
        out.append("BUY_GOODS")
    return out


def create_payment_order(*, business_id, store_id, customer_name, phone, amount, items=None, channel="ONLINE", payment_method=None, pos_cashier_id=None, delivery_location=None, delivery_distance_km=None, estimated_weight_kg=None, packaging_weight_kg=0, delivery_fee=0):
    channel_name = (channel or "ONLINE").upper()
    is_pos = channel_name == "POS"
    name = str(customer_name or "").strip()[:160]
    name_norm = normalize_name(name)
    phone_norm = normalize_phone(phone)
    total = normalize_amount(amount)
    # POS payments are reconciled against the scanned basket total and the trusted
    # receipt delivered by the paired Android gateway. The cashier does not need to
    # guess or type a customer's registered name or phone number.
    if not is_pos and (not name_norm or len(name_norm) < 2):
        raise ValueError("Enter the customer's full M-PESA registered name.")
    if not is_pos and not phone_norm:
        raise ValueError("Enter a valid Kenyan phone number.")
    if total is None or total <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    delivery_charge = normalize_amount(delivery_fee or 0)
    if delivery_charge is None or delivery_charge < 0:
        raise ValueError("Delivery charge must be a valid non-negative amount.")
    if not is_pos and delivery_charge > 0 and not str(delivery_location or "").strip():
        raise ValueError("Enter the delivery location before continuing to payment.")
    if is_pos:
        name = name or ""
        name_norm = name_norm or ""
        phone_norm = phone_norm or ""

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
    requested_method = str(payment_method or "").strip().upper()
    if is_pos and requested_method in {"BANK", "BANK_TRANSFER", "BANK TRANSFER"}:
        method = "BANK_TRANSFER"
        instructions = payment_instruction_snapshot(settings, method)
    elif is_pos and requested_method in {"", "MPESA", "M-PESA", "MPESA_GATEWAY", "M-PESA_GATEWAY"}:
        method = methods[0]
        instructions = payment_instruction_snapshot(settings, method)
    else:
        method = requested_method or methods[0]
        if method not in methods:
            raise ValueError("Choose one of the available payment methods.")
        instructions = payment_instruction_snapshot(settings, method)

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
            if not sp or not sp.is_available or (not sp.available_pos if is_pos else not sp.available_online):
                raise ValueError("One of the selected items is no longer available for this sales channel.")
            available = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(sp.reserved_quantity or 0))
            if available < qty:
                raise ValueError(f"Not enough stock for {sp.product.name}.")
            unit_price = Decimal(str(sp.selling_price)).quantize(TWOPLACES)
            line = (unit_price * qty).quantize(TWOPLACES)
            calculated += line
            prepared.append((sp, qty, unit_price, line))
        # Always derive the goods subtotal from current server prices, then add the
        # separately calculated delivery charge. Never trust the browser's total.
        total = (calculated + delivery_charge).quantize(TWOPLACES)
    snapshot = instructions
    reference = make_reference()
    order = PayOrder(
        business_id=business_id,
        store_id=store_id,
        public_token=make_public_token(),
        reference=reference,
        channel=channel_name,
        pos_cashier_id=(str(pos_cashier_id).strip() if pos_cashier_id else None),
        customer_name=name,
        customer_name_normalized=name_norm,
        customer_phone=phone_norm,
        expected_amount=total,
        delivery_location=(str(delivery_location or "").strip()[:500] or None),
        delivery_distance_km=normalize_amount(delivery_distance_km) if delivery_distance_km not in (None, "") else None,
        estimated_weight_kg=Decimal(str(estimated_weight_kg or 0)).quantize(Decimal("0.001")),
        packaging_weight_kg=Decimal(str(packaging_weight_kg or 0)).quantize(Decimal("0.001")),
        delivery_fee=delivery_charge,
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


def process_gateway_receipt(*, business_id, transaction_code, amount, payer_name, phone, received_at, device_id, sim_slot, sender, message, telemetry_id=None, is_bank_receipt=False, bank_target_verified=False):
    """Reconcile trusted incoming SMS receipts without requiring POS customer details.

    ONLINE stays strict: the receipt phone and exact amount identify an online request.
    POS can be amount-matched because it has no customer data entry, but only when the
    basket amount and payment route identify one unique live POS request. Collisions
    or amount differences are retained for administrator review, never guessed.
    """
    code = str(transaction_code or "").strip().upper()[:40]
    total = normalize_amount(amount)
    name = str(payer_name or "").strip()[:160]
    name_norm = normalize_name(name)
    phone_norm = normalize_phone(phone)
    bank_receipt = bool(is_bank_receipt)
    if not code or total is None:
        return {"classification": "PAYMENT_UNMATCHED", "matched": False, "reason": "INVALID_PARSED_FIELDS"}

    existing = PayReceipt.query.filter_by(transaction_code=code).with_for_update().first()
    if existing:
        return {"classification": "DUPLICATE", "matched": False, "duplicate": True, "payment_order_id": existing.matched_payment_order_id}

    current = now()
    all_open = (PayOrder.query.filter(
        PayOrder.business_id == business_id,
        PayOrder.payment_status.in_(["PENDING", "MANUAL_REVIEW"]),
    ).with_for_update().all())
    live_orders = []
    for candidate in all_open:
        expires = _utc(candidate.expires_at)
        if expires is None or expires > current:
            live_orders.append(candidate)

    order = None
    classification = "PAYMENT_UNMATCHED"
    method = "NO_SAFE_EXACT_MATCH"
    reason = "No safe exact pending match."
    candidate_ids = []
    pos_source_orders = [o for o in live_orders if (o.channel or "").upper() == "POS"
                         and ((str(o.payment_method or "").upper() == "BANK_TRANSFER") == bank_receipt)]
    online_orders = [o for o in live_orders if (o.channel or "").upper() != "POS"
                     and str(o.payment_method or "").upper() != "BANK_TRANSFER"]

    # Even if an SMS resembles a bank credit and the amount fits a ticket, it must
    # never auto-approve unless the alert identifies Denmart's configured account.
    # Store possible order candidates for the admin queue so they can check the
    # actual statement/receiving account and explicitly approve if appropriate.
    if bank_receipt and not bank_target_verified:
        classification = "BANK_ACCOUNT_UNVERIFIED"
        method = "BANK_ACCOUNT_NOT_VERIFIED"
        reason = "Incoming bank credit could not be verified against Denmart's configured receiving account. Administrator must verify the destination before approving."
        exact_bank_candidates = [o for o in pos_source_orders if normalize_amount(o.expected_amount) == total]
        review_candidates = exact_bank_candidates or (pos_source_orders if len(pos_source_orders) == 1 else [])
        candidate_ids = [o.id for o in review_candidates]
        for candidate in review_candidates:
            candidate.payment_status = "MANUAL_REVIEW"
            candidate.review_reason = reason
            candidate.last_match_note = reason
            db.session.add(PayEvent(payment_order_id=candidate.id, event_type="BANK_ACCOUNT_REVIEW", source="ANDROID_GATEWAY_BANK", note=reason))

    # The strongest evidence wins first: online checkout must match the registered
    # phone and exact amount. Bank account notifications don't reliably carry a payer
    # mobile number, so they are never allowed to auto-approve an online checkout.
    if not bank_receipt and phone_norm:
        online_exact = [o for o in online_orders if o.customer_phone == phone_norm
                        and normalize_amount(o.expected_amount) == total]
        pos_same_amount = [o for o in pos_source_orders if normalize_amount(o.expected_amount) == total]
        if online_exact and pos_same_amount:
            # The payer phone makes an online request plausible, while the same
            # amount matches a cashier ticket with no customer phone. Do not guess
            # which channel received the money; let the administrator choose.
            classification = "PAYMENT_AMBIGUOUS"
            method = "ONLINE_POS_AMOUNT_COLLISION"
            reason = "The receipt matches an online phone/amount request and a POS ticket for the same amount. Administrator review is required to prevent settling the wrong sale."
            candidate_ids = list(dict.fromkeys([o.id for o in online_exact + pos_same_amount]))
        elif len(online_exact) == 1:
            order = online_exact[0]
            method = "NAME_PHONE_AND_AMOUNT" if name_norm and order.customer_name_normalized == name_norm else "PHONE_AND_AMOUNT"
            reason = ("Exact normalized M-PESA name + phone + amount match." if method == "NAME_PHONE_AND_AMOUNT"
                      else "One exact online phone + amount candidate; payer name retained as supporting receipt data.")
            classification = "PAYMENT_MATCHED"
            candidate_ids = [order.id]
        elif len(online_exact) > 1:
            classification = "PAYMENT_AMBIGUOUS"
            method = "MULTIPLE_ONLINE_PHONE_AND_AMOUNT"
            reason = "More than one online request has the same phone and amount. Administrator review required."
            candidate_ids = [o.id for o in online_exact]
        else:
            online_by_phone = [o for o in online_orders if o.customer_phone == phone_norm]
            if len(online_by_phone) == 1:
                order = online_by_phone[0]
                expected = normalize_amount(order.expected_amount)
                if expected is not None and total < expected:
                    classification, method, reason = "UNDERPAYMENT", "ONLINE_PHONE_AMOUNT_LOW", "Received amount is below the pending online amount."
                    candidate_ids = [order.id]
                elif expected is not None and total > expected:
                    classification, method, reason = "OVERPAYMENT", "ONLINE_PHONE_AMOUNT_HIGH", "Received amount is above the pending online amount."
                    candidate_ids = [order.id]
                else:
                    classification, method, reason = "PAYMENT_UNMATCHED", "ONLINE_AMOUNT_UNRESOLVED", "The phone matched, but the receipt did not match an eligible online amount."
                    candidate_ids = [order.id]
            elif len(online_by_phone) > 1:
                classification = "PAYMENT_AMBIGUOUS"
                method = "MULTIPLE_ONLINE_PHONE_CANDIDATES"
                reason = "More than one open online request belongs to this phone number. Administrator review required."
                candidate_ids = [o.id for o in online_by_phone]

    # POS path: match against the total currently owed on the till. A receipt is
    # auto-approved only when there is exactly one amount match and no competing
    # online request with that amount. A cashier never needs to enter the payer name.
    if classification == "PAYMENT_UNMATCHED" and order is None:
        pos_exact = [o for o in pos_source_orders if normalize_amount(o.expected_amount) == total]
        competing_online = []
        if not bank_receipt:
            competing_online = [o for o in online_orders if normalize_amount(o.expected_amount) == total]
        if len(pos_exact) == 1 and not competing_online:
            order = pos_exact[0]
            classification = "PAYMENT_MATCHED"
            method = "POS_BANK_AMOUNT_EXACT" if bank_receipt else "POS_MPESA_AMOUNT_EXACT"
            route_name = "bank-transfer" if bank_receipt else "M-PESA"
            reason = f"Exact pending POS basket amount matched against the incoming {route_name} receipt; payer identity came from the gateway message."
            candidate_ids = [order.id]
        elif pos_exact or competing_online:
            classification = "PAYMENT_AMBIGUOUS"
            method = "POS_AMOUNT_COLLISION"
            reason = "The incoming amount fits more than one possible request. Administrator review is required; no sale was auto-completed."
            candidate_ids = list(dict.fromkeys([o.id for o in pos_exact + competing_online]))
        elif len(pos_source_orders) == 1:
            # Single pending POS ticket but no exact amount: identify it for review,
            # never auto-complete an under/over-payment.
            order = pos_source_orders[0]
            expected = normalize_amount(order.expected_amount)
            if expected is not None and total < expected:
                classification, method, reason = "UNDERPAYMENT", "POS_AMOUNT_LOW", "The received amount is below the pending POS total; administrator review required."
                candidate_ids = [order.id]
            elif expected is not None and total > expected:
                classification, method, reason = "OVERPAYMENT", "POS_AMOUNT_HIGH", "The received amount is above the pending POS total; administrator review required."
                candidate_ids = [order.id]
        elif len(pos_source_orders) > 1 and not bank_receipt:
            # Same source/method but different open POS totals means an off-by-amount
            # receipt cannot safely be attached to a particular ticket.
            classification, method, reason = "PAYMENT_AMBIGUOUS", "MULTIPLE_POS_AMOUNT_CANDIDATES", "Several POS tickets are awaiting this payment route; the amount does not uniquely identify one."
            candidate_ids = [o.id for o in pos_source_orders]

    # Only use the matched order as a single receipt foreign-key when evidence points
    # to exactly one ticket. Ambiguous receipts stay unassigned with their candidates.
    if classification == "PAYMENT_AMBIGUOUS":
        order = None

    receipt = PayReceipt(
        business_id=business_id,
        transaction_code=code,
        amount=total,
        payer_name=name or ("Bank payer" if bank_receipt else "M-PESA payer"),
        payer_name_normalized=name_norm or ("BANK PAYER" if bank_receipt else "MPESA PAYER"),
        payer_phone=phone_norm or "",
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
        live_order = PayOrder.query.filter_by(id=order.id).with_for_update().first()
        if not live_order or live_order.payment_status not in {"PENDING", "MANUAL_REVIEW"}:
            db.session.rollback()
            return {"classification": "DUPLICATE_OR_ALREADY_PROCESSED", "matched": False, "payment_order_id": order.id}
        for line in PayOrderItem.query.filter_by(payment_order_id=live_order.id).all():
            sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
            available = (Decimal(str(sp.stock_quantity or 0)) - Decimal(str(sp.reserved_quantity or 0))) if sp else Decimal("-1")
            if not sp or available < Decimal(str(line.quantity)):
                live_order.payment_status = "MANUAL_REVIEW"
                live_order.review_reason = "STOCK_CONFLICT_AFTER_PAYMENT"
                live_order.last_match_note = "Payment matched, but stock changed before settlement; administrator review required."
                receipt.classification = "STOCK_CONFLICT"
                receipt.matching_method = method + "_STOCK_CONFLICT"
                receipt.matched_payment_order_id = live_order.id
                db.session.add(PayEvent(payment_order_id=live_order.id, event_type="REVIEW_REQUIRED", source="ANDROID_GATEWAY", note=live_order.last_match_note))
                db.session.commit()
                return {"classification": "STOCK_CONFLICT", "matched": False, "payment_order_id": live_order.id, "reason": live_order.last_match_note}
        for line in PayOrderItem.query.filter_by(payment_order_id=live_order.id).all():
            sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
            sp.stock_quantity = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(line.quantity))
            db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id,
                transaction_type="ONLINE_PAYMENT" if (live_order.channel or "").upper() != "POS" else "POS_PAYMENT",
                quantity=-Decimal(str(line.quantity)), unit_cost=sp.cost_price,
                reference_type="PAY_ORDER", reference_id=live_order.id))
        pos_sale = _get_or_create_pos_sale(live_order)
        live_order.payment_status = "PAID"
        live_order.fulfillment_status = "PACKAGING"
        live_order.mpesa_transaction_code = code
        live_order.paid_amount = total
        live_order.paid_name = name or None
        live_order.paid_phone = phone_norm or None
        live_order.paid_at = received_at or now()
        live_order.paid_source = "ANDROID_GATEWAY_BANK_AUTO" if bank_receipt else "ANDROID_GATEWAY_AUTO"
        live_order.matched_by = method
        live_order.review_reason = None
        live_order.last_match_note = reason
        receipt.matched_payment_order_id = live_order.id
        if pos_sale:
            live_order.last_match_note = reason + " POS sale completed automatically."
        db.session.add(PayEvent(payment_order_id=live_order.id, event_type="AUTO_APPROVED", source="ANDROID_GATEWAY_BANK" if bank_receipt else "ANDROID_GATEWAY", note=reason))
    elif order and classification in {"UNDERPAYMENT", "OVERPAYMENT"}:
        order.payment_status = "MANUAL_REVIEW"
        order.review_reason = reason
        order.last_match_note = reason
        db.session.add(PayEvent(payment_order_id=order.id, event_type="MATCH_REVIEW", source="ANDROID_GATEWAY_BANK" if bank_receipt else "ANDROID_GATEWAY", note=reason))
    elif classification == "PAYMENT_AMBIGUOUS":
        for candidate_id in candidate_ids:
            candidate = next((row for row in live_orders if row.id == candidate_id), None)
            if candidate:
                candidate.payment_status = "MANUAL_REVIEW"
                candidate.review_reason = reason
                candidate.last_match_note = reason
                db.session.add(PayEvent(payment_order_id=candidate.id, event_type="AMBIGUOUS_RECEIPT", source="ANDROID_GATEWAY_BANK" if bank_receipt else "ANDROID_GATEWAY", note=reason))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = PayReceipt.query.filter_by(transaction_code=code).first()
        if existing:
            return {"classification": "DUPLICATE", "matched": False, "duplicate": True, "payment_order_id": existing.matched_payment_order_id}
        raise

    return {"classification": classification, "matched": classification == "PAYMENT_MATCHED", "payment_order_id": order.id if order else None, "candidate_payment_order_ids": candidate_ids, "reason": reason, "method": method}


def manual_approve(order, actor_id, reason="Manual approval"):
    if order.payment_status == "PAID":
        return False, "Already paid."
    if order.payment_status not in {"PENDING", "MANUAL_REVIEW"}:
        return False, "This payment is no longer awaiting approval."
    for line in PayOrderItem.query.filter_by(payment_order_id=order.id).all():
        sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
        available = (Decimal(str(sp.stock_quantity or 0)) - Decimal(str(sp.reserved_quantity or 0))) if sp else Decimal("-1")
        if not sp or available < Decimal(str(line.quantity)):
            return False, "Stock changed while waiting; resolve stock before approving."
    for line in PayOrderItem.query.filter_by(payment_order_id=order.id).all():
        sp = StoreProduct.query.filter_by(id=line.store_product_id).with_for_update().first()
        sp.stock_quantity = Decimal(str(sp.stock_quantity or 0)) - Decimal(str(line.quantity))
        db.session.add(InventoryTransaction(store_id=sp.store_id, product_id=sp.product_id, transaction_type="MANUAL_PAYMENT", quantity=-Decimal(str(line.quantity)), unit_cost=sp.cost_price, reference_type="PAY_ORDER", reference_id=order.id, created_by=actor_id))
    pos_sale = _get_or_create_pos_sale(order)
    receipt = (PayReceipt.query.filter_by(matched_payment_order_id=order.id)
               .order_by(PayReceipt.created_at.desc()).first())
    if not receipt:
        # A collision is intentionally stored without choosing a ticket. When an
        # administrator explicitly approves one candidate, attach the receipt then.
        possible = (PayReceipt.query.filter_by(business_id=order.business_id)
                    .order_by(PayReceipt.created_at.desc()).limit(100).all())
        receipt = next((candidate for candidate in possible
                        if order.id in (candidate.candidate_payment_order_ids or [])), None)
        if receipt:
            receipt.matched_payment_order_id = order.id
            receipt.candidate_payment_order_ids = None
    if receipt and receipt.transaction_code:
        order.mpesa_transaction_code = receipt.transaction_code
        order.paid_amount = receipt.amount
        order.paid_name = None if (receipt.payer_name_normalized or "").upper() in {"MPESA PAYER", "BANK PAYER"} else receipt.payer_name
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
