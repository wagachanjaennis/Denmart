DENMART PAY HARDCODE PATCH — 2026-10-04

Replace these three files in the existing GitHub repository:
- config.py
- services/payment_engine.py
- routes/shop.py

Changes:
1. Customer PAY defaults to Buy Goods Till 0757817361 when payment settings are blank.
2. Existing blank pay_settings rows are automatically hydrated with that Till.
3. New pay_settings rows also use that Till.
4. Customer order creation has a final fallback so checkout cannot stop on the old “Payment instructions are not configured yet” condition.
5. routes/shop.py imports Business, fixing the PWA manifest/app-icon 500s shown in Render logs.

No Procfile, APK, database reset, or unrelated files are required.

IMPORTANT: 0757817361 is the Till value found in the original Denmart project. It has not been independently verified here as a live merchant destination. Replace it with the merchant’s verified Till before accepting real payments.
