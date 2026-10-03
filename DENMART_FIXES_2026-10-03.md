# Denmart fixes — 03 October 2026

- Unified admin Payment Control Centre for online orders and physical POS sales.
- Manual payment approval with audit trail and stock-reservation recovery for verified failures.
- Per-business / per-mart M-PESA Till and PayBill destinations, with destination-aware checkout and Daraja routing.
- Strict incoming Safaricom/M-PESA receipt filtering; Airtel, outgoing, balance, airtime, bundles and withdrawal notifications are ignored.
- Gateway matching now uses business + mart + amount + payer phone/name + transaction reference + time proximity, with an exact-phone pass before the bounded fallback queue.
- Public mart location pages, customer location sorting, map links, robots.txt and sitemap.xml.
- Service-worker cache version bumped so older checkout JavaScript is not retained by the PWA cache.
- GET fallback added for the product-price control URL that was returning HTTP 405.

Source verification:
- Python compilation: PASS.
- Browser JavaScript syntax check with Node: PASS.
- Jinja template parsing: PASS.

Android APK assembly was not performed in this environment because the Gradle 8.11.1 distribution was not cached and external network access to services.gradle.org was unavailable. The Java M-PESA parser was compiled and exercised with positive/negative receipt cases successfully.
