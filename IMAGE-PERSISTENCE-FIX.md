> **Storefront photo refresh — 25 October 2026:** The Render pipeline now runs `scripts/github_catalogue_image_cache.py --limit 350 --workers 8` followed by `scripts/prepare_catalogue_images.py`. This is the preferred deployed path for the public shop: it prioritizes top products, refuses ambiguous shared photos, keeps database-saved WEBP copies where practical, and uses cache-first browser handling. Real photo discovery needs a network-enabled Render build; the source archive cannot honestly claim new images are bundled before that build. The older standalone SQLite backup workflow documented below remains available for offline repair workflows.

# Denmart image persistence fix

## What changed

- Product image resolution now honors saved HTTP(S) image URLs instead of silently hiding URLs that are not in the hard-coded name list.
- Local image URLs are shown only when the actual file exists in the deployed `static/` directory.
- SQLite and JSON backup restore now preserve existing image URLs by product barcode, then by normalized product name + brand, when the incoming backup has a blank or stale image reference. It also creates a primary `product_images` record when a restored product has a usable image URL but no image row.
- `scripts/cache_catalogue_photo_urls.py` can cache saved real-photo URLs into stable barcode-keyed WEBP files and create a separate repaired SQLite backup. This makes cached photos independent of changing product IDs.

## Safest workflow to cache current photos

Run this from the Denmart project root on a computer with internet access:

```bash
python scripts/cache_catalogue_photo_urls.py "path/to/your-backup.sqlite" --output-db "denmart-images.sqlite"
```

To also search Open Food Facts for missing or unreachable photos, use this optional mode:

```bash
python scripts/cache_catalogue_photo_urls.py "path/to/your-backup.sqlite" --output-db "denmart-images.sqlite" --discover-openfoodfacts --discovery-limit 600
```

The input database is not overwritten. The script saves actual downloaded photos under `static/catalogue/products/by-barcode/` and updates only image references plus `product_images` rows in the output database. It does not generate substitute product artwork. Discovery is deliberately conservative about product name, brand and pack size; it may skip products when it cannot verify a strong match, and it cannot guarantee enough results to cover most of the catalogue. Open Food Facts licensing/attribution requirements must be checked before commercial use. Failed downloads leave the original URL untouched.

Commit the generated `static/catalogue/products/by-barcode/` files with the code, and upload `denmart-images.sqlite` only after reviewing it. If you only deploy the code fix without caching, the external photos will still depend on their source websites being reachable.

## Coverage limitation

The supplied database has 1,327 products, but 1,189 have no saved image URL. The source project does not contain 1,189 verified product photos. This patch fixes URLs being hidden and protects existing images across restores; it cannot truthfully invent exact photos for products that have no source. Run the cache script on a network-connected machine to preserve currently reachable photos locally. Missing products still need exact, verified image sources or administrator uploads.
