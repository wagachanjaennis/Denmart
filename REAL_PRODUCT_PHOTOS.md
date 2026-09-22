# Denmart real product photos

Denmart uses a build-time image cache. The storefront never performs a product-image search during a customer's visit and never redirects a product to another product's image.

## Priority
The first 500 catalogue SKUs are prioritised. They are stored in `static/catalogue/products/001/` through `005/`, with 100 files per folder. Folders `006/` through `014/` are reserved for the remaining catalogue.

## Matching rule
A photo is accepted only after a strong product identity match using the brand/name/pack-size information from the catalogue. Exact curated sources are tried first, followed by Open Food Facts-family datasets and Kenyan retail product pages.

A failed match remains `pending_real_photo`. No fake bottle, cylinder, egg, milk or other product illustration is created, and no unrelated product photo is borrowed.

## GitHub
`.github/workflows/cache-catalogue-images.yml` downloads the highest-priority real photos on GitHub Actions, verifies the local cache, and commits only the verified files and manifest. Run it manually from **Actions → Cache real Denmart product photos → Run workflow** to refresh the first 500.

## Render
The Render build runs the same real-photo-only cache before the application starts, so the deployed site can populate its local assets even when the image cache has not yet been committed back to GitHub.

## Sources
The source URL is stored in `static/catalogue/catalogue-image-manifest.json` for auditability. Product-photo use should be reviewed against the source site's terms/licensing before commercial publication.
