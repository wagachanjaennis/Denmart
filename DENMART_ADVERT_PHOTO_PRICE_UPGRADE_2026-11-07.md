# Denmart advertisement, photo priority and full-screen upgrade

Prepared 7 November 2026 from the Denmart source archive and supplied backup.

## What changed

- Added the 53 newly supplied Denmart photos as optimised WebP assets under `static/advertising/uploads/`. The studio now shows this fresh library before catalogue search, ordered by a technical clarity/resolution score.
- Updated the ad product-search API and public catalogue ordering to rank saved/local product photos before remote image sources and products with no image. Broken browser-loaded images are visibly marked as unavailable and moved below working results in the editor.
- Added the active online store's saved selling price to each product result. Choosing **Add image + price** places a catalogue product image and editable KES badge on the creative. For a new upload, choose **Match product + price**, then search the exact catalogue product/pack size; the selected upload is paired with that SKU’s saved price. No price is guessed for unmatched photos.
- Replaced the old festive / opening-date draft with a reusable Denmart local-shopping campaign: everyday essentials, household goods, new arrivals, the website, and the two branch directions provided for this update.
- Cleaned the public `/advertisement` player so it fills the viewport and has no on-screen player controls or hint text. A first tap/click requests fullscreen with hidden browser navigation UI where supported.

## Important fullscreen limitation

A normal website cannot force F11/fullscreen or hide the browser's address bar before a user gesture. Browsers require a tap/click/keyboard action for security. On a TV or permanently mounted display, launch the browser in kiosk mode or install the site as a full-screen PWA; otherwise tap the ad screen once to request fullscreen.

## Deployment

1. Keep a copy of the current live database and uploaded files before deploying.
2. Deploy the source contents from this archive to the Denmart application repository and redeploy the app.
3. To update only the advert settings on the existing live database, run `AUTO_INIT_DB=0 python scripts/apply_denmart_advert_campaign.py` in the deployed app environment with its production `DATABASE_URL`. This preserves other drafts and all sales, stock, customer and payment records. You can then review the campaign in `/advertcontrol`. The updated full database backup files are also provided separately; restoring either one replaces the database with the 7 November 2026 snapshot, so do **not** restore them over newer live data unless that is intended.
4. Open `/advertisement`, tap/click once for fullscreen on a normal browser, or use kiosk/PWA mode for an unattended display.

## Branch copy used

- Main Branch: Toll, close to Thika Road.
- Kimbo: Exit 13, Kimbo Maangi, then Ebenezer Centre.

The uploaded item photos are not automatically assigned to product SKUs. Use **Match product + price** in the photo library and confirm the exact product size/variant before attaching its selling price, especially where a photo could show another pack or flavour.

## Offline PWA advertisement replay

The root-scope shop PWA service worker now caches `/advertisement` and `/advertisement/screen`, the last successful `/advertisement/current.json`, campaign image assets, QR image and active MP4. The player asks the worker to refresh this saved snapshot when it opens and when a scheduled campaign changes. After deploying, open the ad page online once on each device/PWA profile and let the current campaign finish loading before testing it offline. Offline replay depends on the browser retaining its local site storage; clearing site data or reinstalling the browser removes the saved copy.
