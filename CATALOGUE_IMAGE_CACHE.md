# Denmart catalogue image cache

This build removes runtime product-image searching from the customer storefront.

Each product stores a same-origin URL such as `/static/catalogue/products/<product-id>.webp` in `products.image_url`, and the matching file is bundled under `static/catalogue/products/`.

The Render build runs `scripts/prepare_catalogue_images.py`. It uses the stored source manifest for previously verified product-image URLs and attempts to download/normalize those photos during the build. A temporary source failure never replaces an existing local asset. Products without a verified photograph receive a deterministic product-specific catalogue visual rather than an unrelated stock image or blank tile.

The PWA service worker caches local catalogue images cache-first after they are viewed, while HTTP caching marks product assets immutable for one year.

For portable SQLite use, `scripts/cache_sqlite_backup.py` prepares a supplied SQLite backup with the same local product-image mappings.
