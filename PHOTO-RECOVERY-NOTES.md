# Denmart photo recovery patch — 13 October 2026

This is a targeted code patch. It does not include or overwrite the production database.

## What it changes

- Reconnects legacy image-source records to current product rows using exact product name and barcode, checking brand where both versions provide it, instead of depending on old product IDs alone.
- Chooses a safer alternate photo source when a higher-priority source is ambiguous.
- Rejects shared image URLs when they would put a different product, brand, pack size or model under the wrong picture, unless the URL itself uniquely identifies the pack-size owner.
- Stops treating the old generated product silhouettes as real photographs.
- Preserves an existing genuine cached image if the older batch/barcode file still exists in `static/catalogue/products/<batch>/<barcode>.webp` and its manifest identity matches the product.
- Keeps the Render build-time photo-cache step enabled so reachable, unambiguous source URLs can be downloaded into the deployed static image cache. This requires the external source to be reachable during deployment.
- Hides browser-storage/backup notices from public shopping pages while retaining those operational notices in `/control`, `/control2` and `/merchant`.

## Important evidence and limitation

The supplied SQLite backup has 1,327 product records, 0 rows in `product_images`, and 138 product records with HTTP image URLs. Those 138 URL fields contain only 68 distinct URLs; 19 of the URLs are reused across 89 records. The supplied project archive has 87 local product-image files but only 10 distinct file hashes: 78 files are identical and the remaining distinct assets are stylized product-card drawings, not verified retail packshot photographs.

The old manifest contains 1,319 product identities that can be matched by barcode and full name, but that does not mean it contains 1,319 actual photos. Existing shared links are deliberately not assigned to another product merely to fill a blank card. The supplied database and ZIP do not contain the missing thousands of original image bytes, so this patch cannot recreate photographs that are absent from the backup or deployment filesystem. It can reconnect available, unambiguous sources and carry forward any matching legacy cached files that still exist during the build.

To recover any remaining original photos, the missing image archive or the old persistent/deployment cache is required. Do not restore or replace the production database as part of applying this patch.

## Apply

Extract the ZIP into the existing project root, preserving paths, then commit and push the changed files to the existing GitHub repository. Do not upload this ZIP as a single file, delete the current project, or replace the production database.
