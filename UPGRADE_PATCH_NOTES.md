# Denmart upgrade patch — 13 October 2026

## Apply

Copy/extract this patch over the existing project root, preserving the folders shown in the ZIP. It intentionally contains only changed and new files, not a replacement copy of the application. Back up the repository and database first, then review/commit the changed files and deploy using your usual GitHub → Render workflow.

## Included changes

- **Cash POS approval safety:** cash sales are submitted as `PENDING_APPROVAL`; stock is reserved rather than deducted; no receipt is available until an authorized administrator approves. Rejection releases reservations. The master admin has a pending cash-sales list and Control 2 approval can be enabled separately.
- **Faster catalogue entry:** compact in-place product entry supports barcode + name, optional category, sell/cost prices and quantity, then clears for the next item without a full-page reload. Catalogue browsing is searchable and paginated at 100 rows rather than returning up to 10,000 rows. CSV import remains available for spreadsheet-sized catalogue uploads. Barcode lookup prefers local data and has a faster manual-entry fallback.
- **Phone scanning:** scan form can capture name, barcode, category, price/cost, unit/pack details and stock, then continue directly to the next item.
- **Control 2 manager portal:** separate PWA route for restricted day-to-day operations. Managers can review payment/order records, update fulfillment only when payment is approved, add stock and create/disable staff accounts. There are no delete routes. Payment and cash-sale approval rights default to OFF and are controlled in main admin Settings.
- **Admin usability and alerts:** clearer mobile navigation with lower-priority gateway pages hidden on narrow screens, visible daily report shortcut, readable green theme, approval counts/red dots, polling, optional sound and browser notifications, and staff names in audit displays.
- **PWA and POS offline support:** admin and Control 2 installable shells do not cache private records. POS caches product pages/data when online and keeps a bounded local queue for later server submission. Reconnected cash sales still require server-side approval; offline queueing itself is not a completed sale.
- **Brand and storefront:** brand name defaults to Denmart until set in Settings; green theme; editable scrolling announcement and sidebar promotion; storefront category sidebar, QR/basket layout refinements, fewer repeated product images in featured rows, mobile product grid adjustments, and a dynamic storefront PWA icon based on the current brand or uploaded logo.
- **Order launch gate:** public customers can browse and build a basket while online checkout is off. Main admin must enable **Open online ordering and customer checkout now** in Settings before order submission is accepted. The same setting is enforced on the server, not just through a disabled button. The default announcement says online delivery will be available from 27 October 2026 and can be edited or cleared in Settings.

## Important limits

- This is a **partial upgrade patch**, not every idea in the request. Distance-based delivery pricing, automatic product-weight delivery calculations, capturing and persisting a customer's delivery location, and a fully offline admin (including offline approvals/data changes) are not implemented in this patch.
- The visual patch now preserves explicit image URLs already stored on product records and caches the curated exact-product sources at deployment. It also avoids showing the same mapped image on several different pack sizes. Product imagery is still not complete for every catalogue row: the supplied catalogue has about 1,319 items but only 130 curated exact-product sources, so remaining SKUs need exact sources or administrator-uploaded photos rather than misleading stock imagery.
- Full live application testing was not possible in the build environment because Flask and the project's runtime dependencies were unavailable, and package installation could not reach its package index. Static Python compilation, JavaScript syntax checks and Jinja template parsing passed; that is not a substitute for a staging test.

## Before production use

Test in staging with a backup: (1) cashier submits a cash sale; (2) it remains pending and stock is only reserved; (3) an admin approves and stock is then deducted; (4) rejection releases the reservation; (5) an electronic payment remains unapproved until the payment workflow confirms or an authorized admin manually approves it; (6) Control 2 approval authority is off until explicitly enabled; (7) checkout remains blocked until the launch toggle is enabled; (8) test the POS with the network removed and restored, including duplicate retry behavior.
