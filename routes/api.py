from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import json
import re
import hashlib
from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user, login_required
from extensions import csrf, db
from models import Product, ProductAlias, StoreProduct, Sale, SaleItem, InventoryTransaction, now, Store, Customer, Business, SystemSetting, GatewaySmsMessage
from services.search import forgiving_rank
from services.product_images import public_product_image, has_public_product_image

bp = Blueprint("api", __name__, url_prefix="/api")


def safe_product_payload(r, include_stock=False):
    data = {"id": r.id, "product_id": r.product_id, "name": r.product.name, "barcode": r.product.barcode,
            "sku": r.product.sku, "price": str(r.selling_price), "image_url": public_product_image(r.product), "slug": r.product.slug, "category_id": r.product.category_id}
    if include_stock:
        data["stock"] = str(r.stock_quantity)
    return data




def _gateway_business_for_secret(secret):
    secret = str(secret or "").strip()
    if not secret:
        return None
    configured = str(current_app.config.get("ANDROID_GATEWAY_SHARED_SECRET") or current_app.config.get("PAYMENT_GATEWAY_SHARED_SECRET") or "").strip()
    if configured and secret == configured:
        businesses = Business.query.order_by(Business.created_at).limit(2).all()
        if len(businesses) == 1:
            return businesses[0]
    setting = SystemSetting.query.filter_by(key="android_gateway_secret", value=secret).first()
    if not setting:
        return None
    return db.session.get(Business, setting.business_id)


def _gateway_is_mpesa_message(sender, message):
    raw_sender = re.sub(r"\s+", "", str(sender or "").upper())
    upper = str(message or "").upper()
    if not (raw_sender in {"MPESA", "M-PESA", "SAFARICOM"} or "MPESA" in raw_sender or "SAFARICOM" in raw_sender):
        return False
    if re.search(r"MINI[- ]?STATEMENT|STATEMENT|AIRTIME|DATA BUNDLE|\bBUNDLE\b|WITHDRAW|SENT TO|PAID TO", upper) and "RECEIVED" not in upper:
        return False
    return bool(re.search(r"\bRECEIVED\b", upper))


def _gateway_parse_amount(message):
    text = str(message or "")
    patterns = [
        r"\b(?:received|credited)\s+(?:a\s+)?(?:ksh|kshs|kes)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b",
        r"\b(?:ksh|kshs|kes)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s+(?:was\s+)?(?:received|credited)\b",
        r"\b(?:received|credited)\s+([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:ksh|kshs|kes)\b",
        r"\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:ksh|kshs|kes)\s+(?:was\s+)?(?:received|credited)\b",
        r"\b(?:ksh|kshs|kes)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                value = Decimal(m.group(1).replace(",", ""))
                if value > 0:
                    return value
            except InvalidOperation:
                pass
    return None


def _gateway_parse_transaction(message):
    text = str(message or "").upper()
    for pattern in [
        r"(?:^|\s)([A-Z0-9]{8,20})\s+CONFIRMED(?:\.|\s|$)",
        r"\bCONFIRMED[.\s:-]+([A-Z0-9]{8,20})\b",
        r"\bTRANSACTION(?:\s+CODE)?[:\s]+([A-Z0-9]{8,20})\b",
        r"\b(?:RECEIPT|CONFIRMATION)[:\s-]+([A-Z0-9]{8,20})\b",
    ]:
        m=re.search(pattern,text)
        if m:
            return m.group(1).strip().upper()
    return None


def _gateway_parse_customer(message):
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    m = re.search(r"\b(?:received|credited)\b.*?\b(?:from|by)\s+(.+?)(?=\s+(?:on behalf|for account|account|at\s+\d|on\s+\d|new balance|account balance|balance)\b|$)", text, re.I)
    if not m:
        return ""
    value = m.group(1).strip(" .,-")
    # Airtel-to-M-PESA receipts commonly expose a provider prefix before the
    # actual payer name, e.g. "AIRTEL MONEY - JOSIAH MUKUNG 739952128".
    value = re.sub(r"^AIRTEL\s+MONEY\s*[-:–—]?\s*", "", value, flags=re.I)
    value = re.sub(r"\s+(?:(?:\+?254|0)?[17]\d{8})\b.*$", "", value, flags=re.I)
    return value.strip(" .,-")[:240]


def _gateway_parse_phone(message):
    text = str(message or "")
    # Accept all Kenyan formats used by real gateway SMSes, including the
    # bare nine-digit form (e.g. 739952128).
    patterns = [
        r"\b(?:\+?254)(?:7|1)\d{8}\b",
        r"\b0(?:7|1)\d{8}\b",
        r"\b(?:7|1)\d{8}\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        raw = re.sub(r"\D", "", m.group(0))
        if raw.startswith("254") and len(raw) == 12 and raw[3] in "17":
            return raw
        if raw.startswith("0") and len(raw) == 10 and raw[1] in "17":
            return "254" + raw[1:]
        if len(raw) == 9 and raw[0] in "17":
            return "254" + raw
    return ""


@bp.get("/products/search")
def product_search():
    # PUBLIC catalogue: never expose stock, cost, supplier, internal IDs beyond
    # the cart-facing StoreProduct token, or operational endpoints.
    q = request.args.get("q", "").strip(); store_id = request.args.get("store_id")
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.available_online.is_(True), StoreProduct.stock_quantity > StoreProduct.reserved_quantity, Product.status == "ACTIVE")
    if store_id: query = query.filter(StoreProduct.store_id == store_id)
    rows = query.order_by(Product.name).limit(2000).all()
    if q:
        aliases_by_product = {}
        ids = [r.product_id for r in rows]
        if ids:
            for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(ids)).all():
                aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
        ranked = forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=60)
        rows = [row for _, row in sorted(enumerate(ranked), key=lambda pair: (0 if has_public_product_image(pair[1].product) else 1, pair[0]))]
    else:
        rows = sorted(rows, key=lambda row: (0 if has_public_product_image(row.product) else 1, row.product.name.lower()))[:60]
    return jsonify(items=[safe_product_payload(r) for r in rows])


def cashier_api(fn):
    from functools import wraps
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        from flask import session
        if session.get("portal") != "pos" or not current_user.has_permission("sales.create") or not current_user.store_id:
            return jsonify(error="forbidden"), 403
        return fn(*args, **kwargs)
    return wrapped


@bp.get("/pos/products/search")
@cashier_api
def pos_product_search():
    q = request.args.get("q", "").strip()
    query = StoreProduct.query.join(Product).filter(StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id, StoreProduct.available_pos.is_(True), Product.status == "ACTIVE")
    rows = query.order_by(Product.name).limit(2000).all()
    if q:
        aliases_by_product = {}
        ids = [r.product_id for r in rows]
        if ids:
            for alias in ProductAlias.query.filter(ProductAlias.product_id.in_(ids)).all():
                aliases_by_product.setdefault(alias.product_id, []).append(alias.alias)
        ranked = forgiving_rank(rows, q, aliases_by_product=aliases_by_product, limit=50)
        rows = [row for _, row in sorted(enumerate(ranked), key=lambda pair: (0 if has_public_product_image(pair[1].product) else 1, pair[0]))]
    else:
        rows = sorted(rows, key=lambda row: (0 if has_public_product_image(row.product) else 1, row.product.name.lower()))[:50]
    return jsonify(items=[safe_product_payload(r, include_stock=True) for r in rows])


@csrf.exempt
@bp.route("/payment-gateway/ping", methods=["GET", "POST"])
def android_gateway_ping():
    """Compatibility health endpoint used by the existing Android gateway app."""
    supplied_key = (
        request.args.get("key")
        or request.headers.get("X-Denmart-Gateway-Key")
        or request.headers.get("X-RealMart-Gateway-Key")
        or ""
    ).strip()
    business = _gateway_business_for_secret(supplied_key)
    if not business:
        return jsonify(error="gateway_not_authorized"), 401
    return jsonify(
        ok=True,
        business_id=business.id,
        server_time=now().isoformat(),
        sms_endpoint=url_for("api.android_gateway_sms", _external=True),
    ), 200


@csrf.exempt
@bp.post("/payment-gateway/sms")
@bp.post("/payment-gateway/telemetry")
@bp.post("/mpesa-listener/event")
def android_gateway_sms():
    """Receive the existing Android gateway feed, persist the live mirror, and hand valid M-PESA candidates to the independent PAY matcher."""
    supplied_key = (
        request.args.get("key")
        or request.headers.get("X-Denmart-Gateway-Key")
        or request.headers.get("X-RealMart-Gateway-Key")
        or ""
    ).strip()
    business = _gateway_business_for_secret(supplied_key)
    if not business:
        return jsonify(error="gateway_not_authorized"), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict(flat=True)
    if not payload and request.data:
        payload = {"raw_message": request.get_data(as_text=True)}

    event_id = (
        request.headers.get("X-Denmart-Event-Id")
        or request.headers.get("X-RealMart-Event-Id")
        or payload.get("event_id") or payload.get("message_id") or payload.get("sms_id") or payload.get("id") or ""
    ).strip()[:160]
    device_id = (
        request.headers.get("X-Denmart-Gateway-Id")
        or request.headers.get("X-RealMart-Gateway-Id")
        or payload.get("gateway_device_id") or payload.get("device_id") or payload.get("deviceId")
        or payload.get("android_id") or payload.get("imei") or "android-gateway"
    ).strip()[:120]
    raw_message = str(payload.get("raw_message") or payload.get("sms_body") or payload.get("body") or payload.get("receipt") or payload.get("message") or "").strip()
    sender = str(payload.get("sender") or payload.get("originating_address") or payload.get("address") or payload.get("from") or "").strip()[:120]
    source = str(payload.get("source") or "android_sms_telemetry").strip()[:40]
    if not event_id and raw_message:
        fingerprint="|".join([device_id,str(payload.get("sim_slot") or payload.get("sim") or "0"),sender,raw_message,str(payload.get("received_at") or payload.get("timestamp") or payload.get("date") or "")])
        event_id="legacy-"+hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:48]
    if not event_id or not raw_message:
        return jsonify(error="event_id_raw_message_required"), 400

    try:
        sim_slot=int(payload.get("sim_slot") if payload.get("sim_slot") is not None else (payload.get("sim") or 0))
    except (TypeError,ValueError):
        sim_slot=0
    sim_slot=max(0,min(sim_slot,1))
    try:
        raw_received=payload.get("received_at") or payload.get("timestamp") or payload.get("date")
        if raw_received:
            if isinstance(raw_received,(int,float)) or str(raw_received).isdigit():
                value=int(raw_received); value=value/1000 if value>10_000_000_000 else value
                received_at=datetime.fromtimestamp(value,tz=timezone.utc)
            else:
                received_at=datetime.fromisoformat(str(raw_received).strip().replace("Z","+00:00"))
                if received_at.tzinfo is None: received_at=received_at.replace(tzinfo=timezone.utc)
                received_at=received_at.astimezone(timezone.utc)
        else:
            received_at=now()
    except Exception:
        received_at=now()

    existing=GatewaySmsMessage.query.filter_by(business_id=business.id,gateway_device_id=device_id,event_id=event_id).first()
    if existing:
        existing.last_seen_at=now()
        db.session.commit()
        return jsonify(ok=True,duplicate=True,event_id=event_id,telemetry_id=existing.id),200

    mpesa=_gateway_is_mpesa_message(sender,raw_message)
    parsed={
        "transaction_code": _gateway_parse_transaction(raw_message),
        "amount": str(_gateway_parse_amount(raw_message) or ""),
        "payer_name": _gateway_parse_customer(raw_message),
        "normalized_phone": _gateway_parse_phone(raw_message),
    }
    telemetry=GatewaySmsMessage(
        business_id=business.id,
        gateway_device_id=device_id,
        event_id=event_id,
        sim_slot=sim_slot,
        subscription_id=int(payload.get("subscription_id")) if str(payload.get("subscription_id") or "").isdigit() else None,
        source=source,
        sender=sender,
        message=raw_message[:12000],
        received_at=received_at,
        is_mpesa_candidate=mpesa,
        delivery_status="RECEIVED",
        last_seen_at=now(),
        raw_payload={**payload,"raw_message":raw_message,"parsed":parsed},
    )
    db.session.add(telemetry)
    db.session.commit()

    payment_result = None
    if mpesa and parsed.get("transaction_code") and parsed.get("amount") and parsed.get("normalized_phone") and parsed.get("payer_name"):
        try:
            from services.payment_engine import process_gateway_receipt
            payment_result = process_gateway_receipt(
                business_id=business.id,
                transaction_code=parsed.get("transaction_code"),
                amount=parsed.get("amount"),
                payer_name=parsed.get("payer_name"),
                phone=parsed.get("normalized_phone"),
                received_at=received_at,
                device_id=device_id,
                sim_slot=sim_slot,
                sender=sender,
                message=raw_message,
                telemetry_id=telemetry.id,
            )
            telemetry.raw_payload = {**(telemetry.raw_payload or {}), "payment": payment_result}
            telemetry.last_seen_at = now()
            db.session.commit()
        except Exception:
            current_app.logger.exception("Gateway payment comparison failed; telemetry was preserved.")
            payment_result = {"classification": "PAYMENT_PROCESSING_ERROR", "matched": False}
    return jsonify(ok=True,telemetry=True,event_id=event_id,telemetry_id=telemetry.id,mpesa_candidate=mpesa,parsed=parsed,payment=payment_result),200


@bp.get("/pos/catalogue/cache")
@cashier_api
def pos_catalogue_cache():
    rows = (StoreProduct.query.join(Product)
            .filter(StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id,
                    StoreProduct.available_pos.is_(True), Product.status == "ACTIVE")
            .order_by(Product.name).limit(min(int(request.args.get("limit", 500)), 1000)).all())
    return jsonify(items=[safe_product_payload(r, include_stock=True) for r in rows])


@bp.get("/pos/products/barcode/<barcode>")
@cashier_api
def pos_barcode(barcode):
    row = StoreProduct.query.join(Product).filter(Product.barcode == barcode, StoreProduct.is_available.is_(True), StoreProduct.store_id == current_user.store_id, StoreProduct.available_pos.is_(True), Product.status == "ACTIVE").first()
    if not row: return jsonify(error="product_not_found"), 404
    return jsonify(safe_product_payload(row, include_stock=True))
