# Denmart — canonical deployment

This is a coherent full-project build. It consolidates the fixes that were previously being applied as separate patches so that an older file cannot silently override a newer one during deployment.

## Customer payment
- Existing checkout uses the Denmart Buy Goods Till fallback defined in `config.py`.
- Payment approval uses the independent PAY records.
- Live Android gateway receipts are compared against the current pending payment by normalized phone and exact amount, with normalized payer name as the priority/supporting match.
- POS uses the same payment engine and completes the POS sale exactly once after payment approval.

## Android gateway
- Admin setup: `/control/android-gateway`
- Live mirror: `/control/live-messages`
- Ingress: `/api/payment-gateway/sms`
- Legacy ingress: `/api/payment-gateway/telemetry`
- Existing APK legacy ingress: `/api/mpesa-listener/event`
- Secrets are resolved from Render environment variables and business-scoped system settings. Do not put a gateway secret in GitHub.

## Admin
- Admin portal: `/control`
- Authentication calls the current `routes.admin.dashboard` function; obsolete `_dashboard` imports are not used.

## Operational note
Render may receive routine internet scans for paths such as `/.env`, `/phpinfo.php`, etc. A 404 on those requests is expected and is unrelated to the application flow.
