# Denmart PAY Emergency Fix — 2026-10-04

Replace these five files in the existing GitHub repository, preserving the same paths:

- `config.py`
- `routes/shop.py`
- `routes/pay.py`
- `routes/auth.py`
- `services/payment_engine.py`

Fixes included:

1. Restores the hard-coded M-PESA Buy Goods destination `0757817361` as the fallback payment destination.
2. Imports `jsonify` in `routes/shop.py`, fixing `/shop/manifest.webmanifest` and related PWA icon errors.
3. Makes payment expiry comparison safe when a database timestamp is timezone-aware or timezone-naive.
4. Fixes the admin `/control` authenticated handoff to call `routes.admin.dashboard()` instead of the removed `_dashboard()` function.

No Procfile, Render configuration, APK, or unrelated project files need to be changed for this emergency fix.
