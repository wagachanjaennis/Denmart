# Denmart product-retention and advertising-studio update

This is an **update-only patch**. Extract its contents into the root of the existing Denmart GitHub repository and preserve the included paths. Replace matching application files and add the new files, then commit and let Render redeploy.

## Included changes

- Keeps online catalogue items visible when stock is zero; marks them as out of stock and disables purchase controls instead of silently removing them.
- Prioritises products that have a verified image when browsing, while search relevance remains the primary ordering in search results.
- Keeps saved catalogue photos available when the feeder/API record has no image, adds exact-barcode public-image recovery as a last resort, and compresses/caches photos fetched successfully into the existing product-image table.
- Includes the real bundled product photos physically shipped in this patch. Placeholder illustrations are deliberately excluded from the verified-photo list.
- Provides a dedicated, standalone advertising workspace using real product rows from the saved Denmart catalogue, image gallery selection/rotation, mini/medium/maximum preview, text overlay and flowing-message settings, start/end dates, daily time windows, weekday selection, and campaign priority.
- Accepts uploaded MP4 advertisements and serves the stored original bytes for playback/download without re-encoding. Canvas-created animations can be exported as H.264 MP4 using the added FFmpeg dependency.
- Does not add database files, product imports, stock files, sales history, customer records, payment history, secrets, or backups to this ZIP. No database schema migration is required. Successful photo fetches can create compressed `ProductImage` cache rows in the existing database at runtime.

## Apply the patch

1. Make your own backup of the current repository and production database before deploying any update.
2. Extract the ZIP directly into the repository root, preserving folders such as `routes/`, `services/`, `templates/`, and `static/`.
3. Commit the replacement and newly added files to GitHub; Render should redeploy from the configured branch. Do not upload or replace a database as part of this patch.
4. In the restricted Denmart authority area, open `/advertcontrol`, create/edit an advert, preview the scene in each size, choose real catalogue photos, save a draft, and publish or schedule only after checking the output.
5. After the server deploys, open `/control/android-gateway`, copy the full current connection URL including its generated `?key=...`, and paste it into the existing Android gateway app. Do not reuse an old key from previous logs.

## Important operating notes

- A product row is not hidden just because a photograph is missing or an upstream API is offline. A real photo is used when a saved image, an included verified photo, a valid curated exact-name source, or an exact-barcode public lookup is available. Some products may still need a genuine photo uploaded if no reliable public source exists; the system does not invent product packaging to make those rows look populated.
- Remote photos become durable server-side cache rows only after the source succeeds once. On the device, the service worker caches images actually viewed; it cannot pre-cache every photo on every customer's device. Keep the online catalogue connected for first-time image retrieval.
- Generated MP4 export needs the new `imageio-ffmpeg` requirement to be installed in the Render deploy. Browser and hosting limits may restrict unusually long or large exports. Uploaded MP4 originals are limited to 20 MB and remain byte-for-byte unchanged.
- Syntax and archive checks are run on this patch, along with the repository's lightweight Python tests. A live Render deployment, real database-backed campaign publication, live external photo availability, and an actual Android connection cannot be certified from this package-building environment.
