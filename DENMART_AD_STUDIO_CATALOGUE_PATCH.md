# Denmart advert studio + catalogue patch

This is an **overlay patch** for the existing Denmart repository, not a replacement project.

## Apply

1. Extract this ZIP into the existing repository root, allowing the listed files to overwrite their matching paths.
2. Commit and push the changed files to the existing GitHub repository so Render deploys them.
3. Do not delete the existing database or reset the database. This patch makes **no database schema changes** and contains no database file.

## What changed

- Replaced the visible advert workspace with a canvas editor: add and move text/numbers, images, shapes, CTA blocks, price badges, stickers and QR codes; resize/rotate/delete/duplicate/reorder layers; adjust colours, fill, outline, opacity, shadows and gradients; use per-layer animation presets including fade, melt/reveal, typewriter, wipe, rise, slide, zoom, bounce, float, rotate, blur, pulse, shake, flip, pop, drop and glow.
- Added drag-and-drop image import, image compression, real catalogue product-photo search, scene timeline, undo/redo, MP4 import and animated MP4 export through the existing campaign save/publish records.
- Hid the old mini/medium/maximum preview workspace and its duplicate controls from the everyday editor; the visible header has one public-site link. Removed the Advert Control link from admin/control navigation.
- Changed shop home and catalogue views to render bounded 60-product pages and continue loading while scrolling. Product families are interleaved to reduce runs of similar items. API results keep the current DB product names, barcodes, selling prices and stock, while real saved/manifest/source photos and exact-barcode photo lookup are used where available.
- Removed a per-product lazy category lookup from the scroll API. The image manifest and product-photo endpoint are read/reused from existing app assets; no new DB tables are created.

## Patch contents

- `routes/advertising.py`
- `routes/shop.py`
- `services/product_images.py`
- `templates/admin/_nav.html`
- `templates/advertising/studio.html`
- `templates/shop/home.html`
- `templates/shop/shop.html`
- `static/css/advert-studio.css`
- `static/js/advert-player.js`
- `static/js/advert-studio.js`
- `static/js/advert-design-editor.js` (new)
- `static/js/shop-infinite.js` (new)

Product images are sourced from the existing DB/image manifest and exact-barcode photo lookup. An image is not fabricated when no suitable source is found; actual photo coverage therefore depends on the existing records and available source catalogues.

## Checks performed

- JavaScript syntax checks: advert player, advert studio, new design editor and storefront pagination.
- Python compilation: advert routes, shop routes and product image service.
- Jinja parsing for the edited studio, admin navigation and shop templates.
- `pytest -q tests_search.py tests_mpesa_matcher_rules.py`: 11 passed.

The app was not started against a live database during patch validation, to avoid modifying or initializing the deployment database.
