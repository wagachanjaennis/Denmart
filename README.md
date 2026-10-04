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
