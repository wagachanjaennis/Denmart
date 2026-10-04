# Denmart Live-Message Auto Approval — 2026-10-04

## Authority
For gateway M-PESA payments, the Android gateway only transports SMS telemetry. The server's raw SMS is authoritative for payment evidence.

`Live Messages` is the automatic approval path. The `Payments` page is status + manual-review only and does not run a matching pass when opened.

## Automatic approval rules
A live M-PESA receipt can auto-approve an open online order or POS sale when:

1. The raw SMS is structurally identified as an incoming Safaricom/M-PESA receipt.
2. The receipt contains a valid transaction code and amount.
3. The receipt amount exactly equals the entity's current outstanding balance.
4. At least one durable payer identity matches: payer phone OR payer name.
5. If the customer entered an M-PESA transaction code, an exact code match is treated as the strongest signal.
6. The receipt is reasonably tied to the payment attempt: up to 10 minutes before creation and up to 24 hours after creation.

Underpayments, overpayments, and ambiguous identity matches stay open for manual review rather than being silently approved.

## Repeat purchases
M-PESA transaction codes are unique consumption keys. Once a code has been matched, it cannot settle another payment. A later payment from the same customer with the same name/number/amount but a different transaction code is a new receipt and can match the newest open purchase.

## Important fixes
- An open payment's `external_reference` no longer counts as a consumed transaction code; otherwise a customer-entered code could block its own live receipt from matching.
- A payer being labelled `Airtel Money` inside a valid Safaricom/Till receipt no longer invalidates the receipt. The receiving SMS sender and receipt structure remain authoritative.
- Masked customer phone numbers can now be retained for suffix comparison where the SMS format exposes them.
- Payment status polling reports state without triggering a hidden reconciliation side effect.
- The Live Messages UI marks settled receipts with a green top line and `PAID / AUTO-APPROVED`.

## Verification
Python source files pass AST parsing and `compileall` syntax checks in the build container. Runtime integration tests were not executed because the container does not have the project's Flask dependencies installed.
