# Denmart public search, catalogue sharing and admin visual editor update — 16 November 2026

## Visitor experience
- A single search input is shown on each page: the home page and /shop use their own search panel and the global header search is hidden on those two pages to avoid duplication.
- The compact search panel contains a soft animated background window; the mobile layout reduces the QR footprint and clips horizontal overflow so swiping beyond product images does not reveal a blank side area.
- Catalogue live-search first uses a bounded SQL match over product names, brands, barcodes, SKUs, search keywords and aliases; fuzzy fallback is retained when SQL matching returns no rows.
- Product cards, live-search results, infinite-scroll cards, new-arrival tiles and product detail pages include product sharing. Native mobile share is used where available, with Copy Link, WhatsApp, Facebook and Telegram links. Product detail photographs open in a separate full-image tab.
- “Advertise with Denmart” opens `/advertisement?view=advertise`. The existing `/advertisement` player remains the default. The contact view reads business contacts or configurable SystemSetting values. Admin → Settings now includes advertising phone/WhatsApp and email fields. The service worker keeps the advertiser contact cache separate from the canonical full-screen ad-player cache.
- A custom Denmart D/basket/leaf mark is used as the default brand mark and app icon; an existing uploaded business logo remains supported.

## Admin experience
- Admin has a distinct Visual shop editor entry at `/control/storefront-editor`; it previews the real storefront sequence, allows drag insertion/reordering and provides a separate photo-edit action on every product card. The old Online shop order route remains available.
- Existing drag behaviour inserts a product between its neighbours rather than swapping or replacing product records.
- Category rows can be renamed, described and reordered from Admin → Categories.
- Admin inventory treats NULL reorder levels as zero in comparisons and sorting, preventing Decimal-versus-None exceptions.
- Admin photo uploads are authoritative over bundled manifests/caches. Image removal writes an explicit tombstone in the existing `products.image_url` field and deletes gallery rows, preventing old manifest images from returning. Newly saved photos get versioned public URLs to avoid stale browser caches. No database schema migration is required.
- System Errors includes a CSRF-protected, business-scoped Clear error log action. It deletes only SystemError rows for the current business, records an audit entry, and later failures receive new rows. Known automated scanner paths continue returning 404 but no longer flood the system-health log. Expired admin CSRF submissions do not execute the action and return the user to Admin with a refresh message.

## Database and deployment
- No SQLite or JSON database file is included in this code update. Do not replace the existing live database for this deployment.
- Existing tables are reused; no migration is required by these changes.
- The public search and product image paths should be smoke-tested on the deployed service after upload.

## Validation
- Python compile checks passed.
- JavaScript syntax checks passed for `app.js`, `shop-infinite.js` and `admin-storefront-order.js`.
- All Jinja templates parsed successfully.
- A focused unit check verified the image-removal tombstone and administrator-upload priority.
- Full Flask runtime/integration tests were not run in this workspace because Flask is not installed here.
