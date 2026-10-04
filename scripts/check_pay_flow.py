import ast
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    "routes/pay.py",
    "services/auto_payment.py",
    "templates/pay/dashboard.html",
    "templates/pay/checkout.html",
    "templates/pay/order_payment.html",
]
for rel in required:
    assert (ROOT / rel).exists(), f"missing {rel}"

for rel in ("app.py", "bootstrap.py", "models.py", "routes/api.py", "routes/pay.py", "services/auto_payment.py"):
    ast.parse((ROOT / rel).read_text(encoding="utf-8"), filename=rel)

api = (ROOT / "routes/api.py").read_text(encoding="utf-8")
assert '@bp.post("/payment-gateway/sms")' in api
assert '@bp.post("/payment-gateway/telemetry")' in api
assert '@bp.post("/mpesa-listener/event")' in api
assert "services.auto_payment" in api

app = (ROOT / "app.py").read_text(encoding="utf-8")
assert 'from routes.pay import bp as pay_bp' in app
assert 'app.register_blueprint(pay_bp)' in app

models = (ROOT / "models.py").read_text(encoding="utf-8")
assert 'class AutoPaymentReceipt' in models
assert 'uq_auto_pay_business_device_event' in models
assert 'uq_auto_pay_business_transaction' not in models

bootstrap = (ROOT / "bootstrap.py").read_text(encoding="utf-8")
assert 'DROP CONSTRAINT IF EXISTS uq_auto_pay_business_transaction' in bootstrap

cart = (ROOT / "templates/shop/cart.html").read_text(encoding="utf-8")
assert 'href="/pay/checkout"' in cart
assert 'href="/checkout"' in cart

auto = (ROOT / "services/auto_payment.py").read_text(encoding="utf-8")
assert "services.payments.settlement" not in auto
assert "from services.payments.settlement" not in auto
assert "from services.payments.daraja" not in auto
assert "classify_match" in auto

# Pure parser/normalization checks without importing Flask/SQLAlchemy.
mod = ast.parse(auto, filename="services/auto_payment.py")
ns = {"re": re, "Decimal": Decimal, "InvalidOperation": InvalidOperation}
needed = {"normalize_ke_phone", "normalize_name", "parse_amount", "parse_transaction", "parse_phone", "is_mpesa", "classify_match"}
for node in mod.body:
    if isinstance(node, ast.FunctionDef) and node.name in needed:
        local = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "services/auto_payment.py", "exec"), ns, local)
        ns[node.name] = local[node.name]

assert ns["normalize_ke_phone"]("0732154678") == "254732154678"
assert ns["normalize_ke_phone"]("+254732154678") == "254732154678"
assert ns["normalize_ke_phone"]("254732154678") == "254732154678"
assert ns["normalize_ke_phone"]("0112345678") == "254112345678"
assert ns["normalize_name"](" Jean   Promise ") == "JEAN PROMISE"

msg = "UJ40P8V59L Confirmed. You have received Ksh 1,000.00 from JEAN PROMISE 254732154678 on 04/10/26 at 17:00. New M-PESA balance is Ksh 2,000.00."
assert ns["parse_transaction"](msg) == "UJ40P8V59L"
assert ns["parse_amount"](msg) == Decimal("1000.00")
assert ns["parse_phone"](msg) == "254732154678"
assert ns["is_mpesa"](msg, "MPESA") is True

make = lambda phone, amount: {"phone": phone, "amount": Decimal(str(amount)), "kind": "ORDER", "entity": object(), "id": "x"}
status, method, candidate = ns["classify_match"]("254732154678", Decimal("1000.00"), [make("254732154678", "1000.00")])
assert (status, method) == ("AUTO_APPROVED", "PHONE_AND_EXACT_AMOUNT") and candidate is not None
status, _, _ = ns["classify_match"]("254732154678", Decimal("1000.00"), [])
assert status == "PAYMENT_UNMATCHED"
status, method, candidate = ns["classify_match"]("254732154678", Decimal("1000.00"), [make("254732154678", "1000.00"), make("254732154678", "1000.00")])
assert (status, method, candidate) == ("PAYMENT_AMBIGUOUS", "PHONE_AND_EXACT_AMOUNT_MULTIPLE", None)
status, _, candidate = ns["classify_match"]("254732154678", Decimal("900.00"), [make("254732154678", "1000.00")])
assert status == "UNDERPAYMENT" and candidate is not None
status, _, candidate = ns["classify_match"]("254732154678", Decimal("1100.00"), [make("254732154678", "1000.00")])
assert status == "OVERPAYMENT" and candidate is not None

print("PAY FLOW CONTRACT + PURE RULE TESTS: PASS")
