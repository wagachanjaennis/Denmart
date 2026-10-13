# Denmart offline PWA and data-retention patch

This is a **patch overlay**, not a replacement project. Apply it over the current Denmart codebase after the earlier visual storefront patch. Preserve the existing database and uploaded files.

## What the offline mode supports

- **Admin and Control 2:** the last successfully viewed portal pages and same-origin/external images are cached by the installed PWA. Form text fields are autosaved locally as drafts and can be restored. A draft is not a server-side change; approvals, staff/permission changes, product/stock mutations, settings changes, and finance operations must be submitted online and confirmed by the server.
- **POS:** a previously authorized cashier can unlock the saved till on the same device using their username and password. Product catalogue, current basket, held sales, and queued cash sales use IndexedDB first, with limited localStorage compatibility mirrors. Queued sales are sent with a stable client reference to avoid duplicate sales after a lost response. The server must accept the sale, and cash sales remain **PENDING_APPROVAL** until an authorized approver approves them. Price/stock conflicts remain in the local queue for review.
- **Online shopping:** visited public pages, product search results, product photos as they are viewed, catalogue data from viewed/search results, and the basket are cached. Browsing and building a basket can work offline. Placing a real order or initiating/confirming a payment still requires a server connection; the offline basket is not an order confirmation.
- **Data recovery:** POS provides an explicit JSON backup export for its offline catalogue, held sales, basket and pending cash-sale queue. The app requests persistent browser storage and warns when the browser has not confirmed that protection or when device storage is near its limit.

## Required setup after deployment

1. Deploy the patch to the existing service; do not delete or replace the production database, `instance` directory, uploads, or existing project files.
2. On **each PC/phone where the PWA is installed**, open Denmart while connected. Open the relevant portal and sign in online again once (Admin, Control 2 and POS are set up separately). This lets that device establish the local offline sign-in verifier.
3. Visit the pages you need offline while online. For POS, let the product catalogue finish caching, and confirm the shift is open before relying on offline cash-sale queuing. Scroll through online-shop pages/products whose photos you want cached.
4. Reload the PWA once after service-worker installation/upgrade. On a test device, confirm the offline banner and try opening the app after disabling connectivity.
5. Test with a small non-production POS sale. Reconnect and confirm it synchronizes once and appears as **pending approval**, not completed. Resolve any price/stock conflicts before retrying; do not clear the browser data while anything is queued.

## Important limits

Offline mode cannot execute a server action while there is no connection. It intentionally does not pretend that payment approval, stock changes, delivery updates, online checkout, or administrative mutations have succeeded just because the browser saved a draft. Full offline mutation support would require a server-side sync protocol and conflict resolution for each administrative action.

No browser cache can promise that data will *never* be lost: a lost/damaged device, manual site-data clearing, browser profile reset, storage denial, or full disk can remove local-only data. The authoritative business records must remain on the server and must be protected with regular database and uploaded-file backups. Export the POS offline backup regularly, especially before moving devices or clearing browser data.

## Validation performed

Python syntax compilation passed for the modified route modules. `node --check` passed for the modified standalone JavaScript and the four service-worker scripts extracted from their Flask route definitions. The environment did not have the Flask runtime dependencies available, so a live Flask/browser/database integration test was not performed.
