Denmart gateway + PAY hotfix

Replace these five files in the EXISTING GitHub project:

routes/api.py
routes/pay.py
routes/shop.py
services/payment_engine.py
config.py

What this fixes:
- Keeps the existing Android gateway endpoint aliases.
- Accepts the established Android gateway authentication keys stored in the current config/database paths.
- Parses Kenyan 9-digit SMS phone numbers such as 739952128 into 254739952128.
- Parses receipts such as "AIRTEL MONEY - JOSIAH MUKUNG 739952128" into the payer name and phone separately.
- Sends parsed gateway receipts into the independent PAY matcher whenever transaction code + amount + phone are available; payer name is supporting data.
- Exact name + phone + amount is the first match. Exactly one phone + exact amount is the safe fallback and can auto-approve even when the payer-name formatting differs.
- Fixes timezone-naive/timezone-aware comparisons on /pay/approval.
- Keeps /pay/api/<token> for the approval page polling.
- Keeps the M-PESA Till fallback 0757817361 from the existing Denmart project.
- Restores the missing Flask jsonify import in the shop PWA routes.

Important gateway deployment note:
The log supplied by the owner showed the existing APK reaching /api/mpesa-listener/event and receiving HTTP 401. That means transport is working but the APK's old key is not currently accepted by the deployed server. After this code is deployed, open /control/android-gateway, copy the currently generated APK connection URL, paste the COMPLETE URL (including ?key=...) into the existing APK, save/test it, then watch /control/live-messages.


## Service controls and delivery weights (2026-10)

- Optional private service-control login: set `DEV_NAME` and `DEV_PASS` in the Render environment. The control panel is at `/qaz`, is not linked in the customer UI, and logs changes into the audit trail. It can pause online shopping, POS, admin operations, or the whole site. It intentionally does not impersonate users or bypass their account passwords.
- Set product weights in kilograms in Admin → Products or on `/scan` with a phone camera/handheld barcode scanner. The online checkout asks for a location and distance, then calculates delivery using the settings in Admin → PAY.
- Before a customer pays, Admin → PAY → open an order lets staff enter its measured packed weight and final delivery charge. Saving updates the exact total on the customer's open payment page. That quote locks when payment enters review or is approved.
- Initial delivery defaults are KES 50 base + KES 20/km, with a 10 kg threshold and KES 100 extra charge, plus 0.25 kg packaging weight. **Replace these defaults with your actual business rates in Admin → PAY before taking live orders.** The extra-weight charge and packaging weight are independently switchable.
- Download a portable SQLite snapshot from Admin → Backups → Export SQLite. It is a normal `.sqlite` database file that can be committed to a private GitHub repository manually; putting live customer/order data into a public repository is not recommended. Automatic GitHub publishing is not enabled by this patch.
