# Denmart M-PESA Auto-Approval — 2026-10-04

## Authority
The Android gateway only transports SMS telemetry. The server's raw SMS is authoritative for payment evidence. `Live Messages` remains the complete server receipt/audit stream.

## Automatic approval rule
A valid inbound Safaricom/M-PESA receipt is eligible for automatic approval only when exactly one still-open gateway payment has:

- the same normalized Kenyan payer phone; and
- the same exact normalized amount as the payment's current outstanding balance.

Payer name is stored and normalized for display/manual review only. It is never required for an exact phone + amount match and never acts as the primary identifier.

## Duplicate protection
The M-PESA transaction code is treated as the payment's external consumption key. Before matching, the server checks whether that code has already been recorded or attached to a paid provider transaction for the business. A reused code is classified as `DUPLICATE / ALREADY_PROCESSED` and cannot approve another payment.

## Outcomes
`PAYMENT_MATCHED / AUTO_APPROVED` + `matched_by=PHONE_AND_AMOUNT` settles the single exact candidate immediately.

`PAYMENT_UNMATCHED` means no eligible pending payment has the receipt phone + exact amount.

`PAYMENT_AMBIGUOUS` means more than one exact candidate exists, or the receipt phone corresponds to multiple open payments with different expected balances.

`UNDERPAYMENT` and `OVERPAYMENT` are recorded when the payer phone identifies open payment(s) but the received amount does not equal the outstanding amount. Neither outcome auto-approves.

## Audit data
Every parsed payment receipt keeps the raw SMS/event data plus normalized phone, classification, matching method, matched payment ID (when any), candidate payments (when any), and processing timestamp. The original gateway receipt message is never removed after a match or failed match.

## Safety
Approval, creation of the provider payment record, gateway event update, and audit linkage are committed in the same database transaction. The gateway settlement path also rejects any cumulative overpayment before completing the sale/order.

## Backward compatibility
The database bootstrap adds the new nullable matcher/audit columns to existing databases and backfills normalized gateway-payment phone values without deleting or rewriting the original raw phone/SMS data.
