# Denmart M-PESA live matching fix

Replace these files in the existing GitHub repo:

- `routes/api.py`
- `services/payment_engine.py`
- `routes/pay.py`
- `templates/pay/approval.html`

Root cause fixed: real incoming M-PESA receipts from the Android gateway can contain a bare 9-digit Kenyan number, such as `739952128`, and Airtel receipts can prefix the payer as `AIRTEL MONEY - NAME`. The previous parser rejected the bare phone and included the provider prefix in the payer name, so the PAY matcher was skipped or could not match.

The new parser converts the example message:

`UJ40P8WT1S Confirmed. You have received Ksh1.00 from AIRTEL MONEY - JOSIAH MUKUNG 739952128 ...`

to:

- transaction code: `UJ40P8WT1S`
- amount: `1.00`
- payer name: `JOSIAH MUKUNG`
- phone: `254739952128`

Matching priority:

1. normalized name + phone + exact amount, if that uniquely identifies one eligible payment
2. otherwise one unique normalized phone + exact amount candidate is auto-approved
3. multiple candidates stay `PAYMENT_AMBIGUOUS`
4. zero exact candidates are checked only for under/overpayment by phone; never auto-approved

The approval page now visibly shows the customer's name, phone, and amount that the server is waiting to compare with the live gateway receipt. Once a receipt is linked, it shows the gateway name, phone, amount, classification, and match method.
