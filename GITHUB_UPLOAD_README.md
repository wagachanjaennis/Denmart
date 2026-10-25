# Denmart — product photo cache

The current workflow keeps product-photo discovery and cache generation separate from customer browsing.

- `data/catalogue_image_priority.json` provides the first 500 priority SKUs.
- The Render build searches the first 350 and then checks the full database for saved uploads, existing image rows and up to 250 additional external sources.
- Images are accepted only if reachable and sufficiently matched to the exact product; shared source URLs and duplicate normalized image bytes are rejected across different SKUs.
- Successfully normalized images are served from local WEBP files and are saved into the persistent database where practical. This lets a later Render build regenerate local copies even when a prior build's filesystem is gone.
- The browser image cache is cache-first and capped at 1,800 images; product image URLs are versioned by image content.
- Generic bottle/box/tube illustrations have been removed. The source archive intentionally contains no fake product pictures. A network-enabled Render build must populate verified photo files.

The GitHub Actions workflow remains available for committing verified photos back to the repository. Source-site licence and attribution terms should be reviewed before commercial use. See `DENMART_STOREFRONT_PHOTO_UPGRADE.md` and `REAL_PRODUCT_PHOTOS.md` for the details.
