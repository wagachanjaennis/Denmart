from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from extensions import db
from models import SystemSetting, StoreProduct

CENT = Decimal("0.01")
THREE = Decimal("0.001")
DEFAULTS = {
    "shipping_delivery_enabled": "1",
    "shipping_base_fee": "50",
    "shipping_per_km_fee": "20",
    "shipping_weight_limit_kg": "10",
    "shipping_overweight_fee": "100",
    "shipping_packaging_weight_kg": "0.25",
    "shipping_include_packaging_weight": "1",
    "shipping_charge_overweight": "1",
}

def _setting(business_id, key):
    row = SystemSetting.query.filter_by(business_id=business_id, key=key).first()
    return (row.value if row and row.value is not None else DEFAULTS.get(key, "0"))

def _decimal(value, fallback="0"):
    try:
        out = Decimal(str(value if value not in (None, "") else fallback))
        return out if out.is_finite() else Decimal(fallback)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(fallback)

def shipping_settings(business_id):
    return {key: _setting(business_id, key) for key in DEFAULTS}

def calculate_delivery_quote(business_id, store_id, items, distance_km):
    """Return a server-calculated fee and weight breakdown for an online basket."""
    config = shipping_settings(business_id)
    distance = _decimal(distance_km, "-1")
    if not distance.is_finite() or distance < 0 or distance > Decimal("200"):
        raise ValueError("Enter a valid delivery distance from 0 to 200 km.")
    total_weight = Decimal("0")
    for raw in items:
        sp_id = str(raw.get("store_product_id") or raw.get("id") or "").strip()
        qty = _decimal(raw.get("quantity") or raw.get("qty") or "0", "0")
        sp = StoreProduct.query.filter_by(id=sp_id, store_id=store_id).first() if sp_id else None
        if not sp or qty <= 0:
            raise ValueError("Your basket has an invalid item. Refresh it and try again.")
        total_weight += _decimal(getattr(sp.product, "weight", None), "0") * qty
    total_weight = total_weight.quantize(THREE, rounding=ROUND_HALF_UP)
    packaging_weight = _decimal(config["shipping_packaging_weight_kg"], "0")
    if packaging_weight < 0: packaging_weight = Decimal("0")
    included_packaging = packaging_weight if config["shipping_include_packaging_weight"] == "1" else Decimal("0")
    billable_weight = (total_weight + included_packaging).quantize(THREE, rounding=ROUND_HALF_UP)
    fee = Decimal("0")
    enabled = config["shipping_delivery_enabled"] == "1"
    if enabled:
        fee = max(Decimal("0"), _decimal(config["shipping_base_fee"]))
        fee += max(Decimal("0"), _decimal(config["shipping_per_km_fee"])) * distance
        threshold = max(Decimal("0"), _decimal(config["shipping_weight_limit_kg"], "10"))
        if config["shipping_charge_overweight"] == "1" and billable_weight > threshold:
            fee += max(Decimal("0"), _decimal(config["shipping_overweight_fee"], "0"))
    fee = fee.quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "distance_km": distance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "product_weight_kg": total_weight,
        "packaging_weight_kg": included_packaging.quantize(THREE),
        "estimated_weight_kg": billable_weight,
        "delivery_fee": fee,
        "weight_limit_kg": max(Decimal("0"), _decimal(config["shipping_weight_limit_kg"], "10")),
        "overweight_fee_applied": bool(enabled and config["shipping_charge_overweight"] == "1" and billable_weight > max(Decimal("0"), _decimal(config["shipping_weight_limit_kg"], "10"))),
        "delivery_enabled": enabled,
    }
