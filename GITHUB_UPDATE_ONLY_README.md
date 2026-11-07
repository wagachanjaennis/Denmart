# Denmart GitHub update-only patch — 7 November 2026

This archive is an **overlay for the existing Denmart repository**. It contains only the files changed or added for the advertisement photo/price work and the offline advertisement PWA fix. It is not a replacement project archive.

## Apply to GitHub

1. Download and extract this ZIP.
2. Copy the extracted folders and files into the **root of the existing GitHub repository**, keeping the folder structure. When asked, overwrite files with the same names.
3. Commit and push the changes, then allow the existing hosting service to redeploy.
4. Do **not** delete or replace the existing database, `instance/`, uploaded user files, or other project folders. This patch contains no database backups.
5. Once the new code is deployed, open `/advertisement` while the device is online. Let the current campaign and all scenes load at least once. Keep the page open until its images/video have played or loaded. The PWA service worker then saves the screen, campaign JSON, image assets, QR image, player assets, and the active MP4 (when present).
6. Install/update the PWA or reopen the already-installed PWA while online once so the browser can install the new service worker. Then test `/advertisement` with network connectivity disabled.
7. Run the supplied campaign settings script once only if you also want to publish the prepared Denmart campaign content from this update:

   ```bash
   AUTO_INIT_DB=0 python scripts/apply_denmart_advert_campaign.py
   ```

   Run it in the deployed app environment with the production database connection. It updates only the advertisement campaign settings; it does not restore or overwrite the database.

## Offline advertisement behaviour

- `/advertisement` and `/advertisement/screen` are now eligible for network-first navigation caching with a last-known-good offline fallback.
- `/advertisement/current.json` uses the last successful campaign JSON if the network is unavailable.
- The player requests a service-worker warm-up when opened and when a new scheduled campaign is detected. The warm-up stores the rendered screen, the current campaign, its image references, the QR image and the selected MP4 asset.
- Uploaded MP4 files are stored as a complete response (subject to the application's 20 MB upload limit) so the service worker can answer later browser byte-range requests while offline.
- Existing public image, page and static caches are migrated when the service worker updates.

## Important limits

Offline replay is available after a successful online warm-up on that device and browser profile. It cannot be guaranteed after someone clears site data, uninstalls/resets the browser, the operating system evicts storage, or the device changes. The first install/update of the service worker needs an internet connection. A normal browser still requires a tap/click for fullscreen; kiosk mode is recommended for an unattended display.

## Files included

- Existing code files updated for the catalogue photo ranking, ad editor/photo library, product price badges and full-screen player.
- `routes/shop.py` includes the versioned root-scope PWA service worker and offline ad/media caching.
- `templates/advertising/screen.html` registers/warm-ups the root-scope worker from the ad screen itself.
- `static/js/advert-player.js` asks the worker to refresh its offline snapshot when a scheduled campaign changes.
- The 53 supplied campaign photos are included as optimised WebP files under `static/advertising/uploads/`, along with the photo-library index.
