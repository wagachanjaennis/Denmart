# Image upload plan

The catalogue contains 1319 product identities.

- **130 products** have curated real-image source URLs already recorded in `data/catalogue_image_sources.json` and `catalogue/catalogue-image-manifest.json`.
- **38 of those** are already cached as real photos in this ZIP.
- The remaining catalogue entries use an explicit neutral placeholder rather than a fake/generated product photo.
- The Render build command already runs `python scripts/prepare_catalogue_images.py`, so reachable curated sources are downloaded and normalized during deployment.
- `catalogue/github-upload-batches/` contains **exactly 100** upload batches. The canonical `catalogue/products/` path is preserved for the application.

Do not delete the source-link data: it is what lets the next build fetch the real product photos.
