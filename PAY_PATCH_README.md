# Denmart PAY live M-PESA patch

This is a targeted patch for an existing Denmart deployment. Do not replace the rest of the project.

Production files changed/added:
- app.py
- bootstrap.py
- models.py
- routes/api.py
- routes/pay.py (new)
- services/auto_payment.py (new)
- templates/shop/cart.html
- templates/pay/checkout.html (new)
- templates/pay/dashboard.html (new)
- templates/pay/order_payment.html (new)

The existing Android gateway transport is retained at:
- POST /api/payment-gateway/sms
- POST /api/payment-gateway/telemetry
- POST /api/mpesa-listener/event

The gateway handler now hands the received SMS to the independent /pay matcher.
The old Daraja provider file is unchanged.
The old /checkout route remains available.
The new admin automation console is /pay.
The new customer payment page is /pay/checkout -> /pay/order/<order_number>.
