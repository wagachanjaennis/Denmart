# Denmart admin cleanup — 11 November 2026

## Included fixes

- Product photo uploads now import and call the image-data validation helper required by the save route.
- The product editor has a dedicated image preview, file-size/type checks in the browser, explicit Save behaviour, URL image support and a working remove-image priority.
- Legacy `/control/stock` and `/control/stock-room` links route to the current Inventory page; `/control/stock/adjust` is accepted by the stock adjustment handler.
- Legacy `/control/orders` and `/control/payments` links route to the current Pay workspace. Old order-fulfilment and manual-payment form paths are accepted by the current PayOrder handlers.
- Legacy `/control/payment-gateway` bookmarks route to the current Android Gateway page.
- Supermarket-owned private-label prefixes were removed from seed catalogue code and generated catalogue/image indexes. Retailer page scraping was disabled in the image-discovery script.

## Deliberately unchanged

- No SQLite database or live product rows were edited. The database cleanup remains a separate step for the administrator.
- Existing customer products, prices, stock, sales, purchases, users, settings and backups are preserved.

## Validation performed

- Python source files compiled with `compileall`.
- All six edited/generated JSON indexes and manifests parse successfully and have updated counts.
- A source/data scan found no remaining references to the removed retailer names/domains.

A full authenticated browser test still needs to be run after deployment against the live database and hosting environment.
