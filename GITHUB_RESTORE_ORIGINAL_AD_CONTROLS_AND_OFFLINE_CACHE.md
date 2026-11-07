# Denmart — restore original advert controls + offline caching

This is an incremental GitHub patch for the existing Denmart repository. Extract it into the repository root and preserve the folder paths. Do not replace the repository or database.

## What is restored
The advert studio files in this patch are copied from the very first Denmart project archive uploaded in this conversation. They restore the original editor rather than redesigning it. This includes the two-colour full-screen scene background (background colour 1 + colour 2 and gradient toggle), text content and typography controls, font size/weight/font and text colour, layer fill/stroke/position/size/opacity/rotation/radius/shadow, image upload and fitting, image animation/effects and timing, scene timeline, product-image selection, QR options, ticker, schedule, priority, MP4 upload, preview, save, publish and export controls.

No campaign theme is forced, no colours are hard-coded to purple, no campaign is auto-published, and no editor controls are removed or hidden by this patch. The original templates, CSS and editor JavaScript are restored from the first archive.

## The only functional improvement: PWA offline cache
The `/shop/sw.js` service worker is the worker actually registered by the public shop PWA. It now:
- saves the `/advertisement` screen after it has loaded successfully online;
- caches the last successful `/advertisement/current.json` campaign rotation;
- caches the advert player's CSS/JS, QR image, and same-origin or external product images used by the player;
- saves uploaded MP4 files and serves browser byte-range requests from the saved file (for clips up to 250 MB, subject to device storage quota);
- migrates existing Denmart public caches instead of deleting previously saved shop pages and product photos;
- does not cache admin, advert-control, payment, checkout or API data.

The public player makes one immediate request for the last saved schedule on page load; its 45-second online refresh continues unchanged.

## Deploy
1. Extract this ZIP.
2. Upload/merge its contents into the existing GitHub repository root, preserving paths and allowing the listed files to overwrite their current versions.
3. Deploy normally.
4. On each installed PWA device, open Denmart and `/advertisement` once while online. Let the advert, images, and any uploaded video play/load successfully; the worker caches those assets as they are used.
5. Reload `/advertisement` while online once after the new worker activates. Then test by disconnecting the network and reopening the installed PWA.

There is no database migration, no campaign setup script, and no need to restore a database backup.

## Notes
- Offline playback is available only for campaigns and media that have successfully loaded on that device before it goes offline. Browser storage must not be cleared; the browser may evict cached media if the device is critically low on storage.
- A website cannot force browser fullscreen before a user gesture; the original player requests fullscreen after the user taps/clicks, exactly as the original controls/player did.
