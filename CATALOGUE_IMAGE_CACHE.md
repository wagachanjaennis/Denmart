# Denmart catalogue image cache

The public storefront no longer displays generated bottle/box/tube illustrations as if they were real product photos. A product without a verified photograph gets a neutral “Photo being added” panel.

The Render build runs `scripts/github_catalogue_image_cache.py --limit 350 --workers 8`, then `scripts/prepare_catalogue_images.py`. The first step searches product-photo sources for top-ranked essentials; the second reuses local assets and saved database photo copies, normalizes available photos to WEBP and persists compact copies in `product_images`. This work happens during deployment, not each page render. Coverage depends on which exact source photos are reachable and can be verified.

The product route prefers locally bundled and database-saved photos before trying a small set of known remote sources. It does not conduct a live product search during a customer image request. Existing uploads/gallery rows are preserved. Shared source URLs used by multiple SKUs are treated as ambiguous, so a 500 ml pack is not blindly used as the image for a 2 L item.

The PWA service worker is cache-first for product images, retaining up to 1,800 cached images without re-fetching them on every visit. Static photo URLs are versioned by image content to allow a corrected photo to replace a prior cached version.

For portable SQLite workflows, existing scripts such as `scripts/cache_sqlite_backup.py` and `scripts/cache_catalogue_photo_urls.py` remain available. Check source-site licensing/attribution terms before commercial use.
