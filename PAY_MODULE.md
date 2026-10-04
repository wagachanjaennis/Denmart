# Denmart PAY

PAY is a new independent payment-and-fulfilment module. It does not read or reuse historical payment records.

## Customer flow
1. Add items to the basket.
2. Enter the customer's full M-PESA registered name and phone number.
3. Choose the configured PayBill / Buy Goods destination.
4. The server creates a new PAY request with status `PENDING` and a private approval link.
5. The approval page waits for the live Android gateway.
6. An exact normalized name + phone + amount match is auto-approved only when it is unambiguous.
7. Approved requests enter `PACKAGING`, then an administrator can move them through `READY`, `DISPATCHED`, and `COMPLETED`.

## Gateway matching
The installed Android gateway continues to POST to the existing endpoints. Telemetry is preserved, then the new PAY matcher evaluates valid M-PESA candidates against current PAY requests.

Safe outcomes include `PAYMENT_MATCHED`, `PAYMENT_AMBIGUOUS`, `NAME_MISMATCH`, `UNDERPAYMENT`, `OVERPAYMENT`, `PHONE_MISMATCH`, `PAYMENT_UNMATCHED`, `STOCK_CONFLICT`, and `DUPLICATE`.

A receipt and an automatic approval are committed together in the same database transaction. Already-paid PAY requests are never re-approved by a later receipt.

## Admin
Open **Control → Operations → PAY** to configure PayBill / Buy Goods instructions, review the payment queue, manually approve conflicts, and advance fulfilment.
