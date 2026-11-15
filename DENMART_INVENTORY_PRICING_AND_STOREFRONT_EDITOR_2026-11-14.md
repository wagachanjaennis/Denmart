# Denmart inventory, pricing and storefront editor update — 14 November 2026

## Admin product photos

- Product rows now expose a separate **Photo** action at Admin → Products.
- The image-only editor is available at `/control/products/<product_id>/image`.
- It supports upload, URL replacement, preview and removal. Its POST handler only writes the product image and image metadata; it does not parse or modify price, stock, barcode or availability fields.
- The normal product editor links to the image-only page instead of mixing image fields into the pricing form.

## Pricing rules

- Quick product entry accepts decimal CP, SP, minimum price and maximum price values.
- Cost price must be strictly below a positive selling price; an unpriced draft can be saved with both CP and SP blank.
- If a minimum price is supplied, it must be strictly above cost and at or below selling price. Blank/zero minimum means no extra minimum floor; on a newly priced product, a blank minimum defaults to the selling price.
- If a maximum price is supplied, it cannot be below selling price. On a newly priced product, a blank maximum defaults to 30% above selling price.
- Minimum cannot exceed maximum. Price inputs use two decimal places; stock and weight retain three decimal places where applicable.
- An unpriced draft may be captured with both cost and selling price blank. It remains disabled until a positive selling price is saved.

## Inventory page

- Inventory search is executed in SQL and the page is bounded to the first 400 matching stock rows per view.
- Transaction history for those rows is loaded in a batch rather than with a separate query for every product.
- If the transaction ledger cannot be read (for example, a missing/temporarily unavailable inventory-transactions table), the current stock quantities still render with a warning instead of taking down the entire Inventory page.
- This is a defensive fix; the actual production Inventory exception still needs the corresponding System Errors row/traceback to confirm its original cause.

## Visual storefront ordering

- Admin → Catalogue and stock → **Online shop order** opens `/control/storefront-order`.
- The screen shows active online products for a selected mart, with photo, name and price, and supports touch/mouse drag-and-drop plus up/down controls.
- Before an owner first saves a custom order, the preview reproduces the current customer catalogue order, including the image/feeder overlays and the same 60-product family interleave used by the storefront.
- Saving persists a per-mart `storefront_sort_order` on `store_products`. The customer browse pages and infinite-scroll pages use that same saved order. Search results remain search-oriented.
- Newly enabled products with no saved position appear after the saved items until arranged.
- Existing order values are not overwritten until the admin explicitly presses **Save display order**.

## Additive database change

- A nullable integer `store_products.storefront_sort_order` column is added on application bootstrap. This migration does not replace or rewrite existing product, order, payment, customer or stock data.
- The project deployment configuration uses `AUTO_INIT_DB=1`; keep it enabled for this additive startup migration unless you run the equivalent schema change manually.
- No SQLite database, database dump or backup is included in this source ZIP.

## Public request / error-log noise

- `/ai.txt` and `/llms.txt` now return small public crawler guidance files.
- `/contact` redirects to the existing Locations page.
- Common WordPress, Git, environment-file, framework debug and API scanner probes continue to receive HTTP 404, but are excluded from the application System Errors log to reduce noise. This does not expose or enable any of those paths.
- Unsupported non-GET requests to `/` still receive HTTP 405; those bot probes are no longer counted as application health incidents.
- Existing historical System Errors records remain in the database until an administrator resolves them.

## Deployment and verification

Deploy the complete source project, retaining the live database and persistent uploads. On startup, the application performs the additive storefront-order column check.

Static checks completed in the build environment: Python compileall, Jinja compilation for all templates, and JavaScript syntax checks. A live Flask/database smoke test was not possible in the build environment because Flask runtime packages are not installed there. After deployment, verify Admin → Products → Photo, Quick product entry, Inventory, and Online shop order against the live database.
