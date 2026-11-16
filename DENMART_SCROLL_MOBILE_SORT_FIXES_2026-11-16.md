# Denmart scroll, mobile layout and visual catalogue editor patch — 16 November 2026

## Public storefront
- Restores normal document scrolling on mouse wheel, touch swipe and browser scrollbar by explicitly keeping the page root vertically scrollable. POS/agent one-screen workspaces remain excluded from the global scroll override.
- Removes the installed-app document-level `touchmove` cancellation. Native vertical scrolling is left to the browser; standalone overscroll containment remains CSS-driven.
- Adds final responsive catalogue rules after legacy overrides: three columns at phone/tablet widths up to 900px and two columns on narrow phones up to 560px. Desktop product layout is unchanged.
- Bumps the public CSS and app JavaScript cache versions so deployed browsers fetch the fixes instead of retaining the previous files.

## Visual shop editor
- Adds a one-click “Put products with photos first” automation. It stable-sorts all products with usable image sources to the top, preserves the order within each group, and places products without photos after them.
- Displays the number of photo/no-photo products and the exact position where the no-photo section begins. Broken image loads are changed to “Photo unavailable” and counted as no-photo on the next sort.
- Adds an undo action for unsaved reordering.
- Supports mouse dragging anywhere on a product card and touch dragging from the grip, preserving normal phone scrolling when the user starts a swipe on the card itself.
- Uses direct insert-on-drop placement, rather than stepping through many up/down taps. Auto-scrolls the page when a dragged card reaches the top or bottom edge of the viewport.
- The editor now attaches saved ProductImage gallery entries and feeder overlays even when a custom order already exists, so the photo-first action reads the same image sources as the public catalogue.
- Existing up/down buttons remain as an accessible fallback. Product records, pricing, stock and availability are not changed by sorting.

## Deployment safety
- No SQLite or JSON database file is included. Do not upload database backups as part of this patch.
- The existing `storefront_sort_order` field is reused; no schema migration is required.
- Save the new visual arrangement from Admin → Visual shop editor after reviewing the photo-first result.

## Validation performed
- JavaScript syntax checks passed for `app.js` and `admin-storefront-order.js`.
- Python compile checks passed for `app.py`, `routes/admin.py` and `routes/shop.py`.
- The updated Jinja storefront editor template parsed successfully.
- Full live Flask/browser integration tests were not run in this workspace; the deployed site should be smoke-tested on a phone and a computer after upload.
