# Denmart `/pay` — independent live M-PESA path

This update adds a new payment path without replacing Daraja or the existing `/checkout` route.

## Android gateway connection
The supplied APK already posts live SMS data to:

- `POST /api/payment-gateway/sms`
- legacy aliases remain `/api/payment-gateway/telemetry` and `/api/mpesa-listener/event`

The server keeps that transport contract and delegates the incoming event to `services/auto_payment.py`. No APK rebuild is required for this server update.

## New customer flow
Basket → `/pay/checkout` → enter name + phone → create order → `/pay/order/<order_number>` → show merchant payment number → poll the live server until `PAID`.

The old `/checkout` and Daraja routes remain available separately.

## Automatic matching rule
Only an eligible open Order/Sale whose normalized phone equals the normalized phone parsed from the live SMS and whose exact total equals the received amount can be auto-approved.

No score, fuzzy name matching, time window, amount-only matching, or name-only matching is used.

Every gateway SMS is stored in `auto_payment_receipts` with the full raw message.
