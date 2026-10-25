# Denmart product-photo cache and GitHub import

The project keeps SKU metadata and source mappings separately from the downloadable photo cache. The priority list contains 500 products; Render discovers photos for the first 350 during build, then a second build pass reuses uploaded/static/DB-saved photos and can download up to 250 additional unique sources. A build may find fewer photos than requested because no source is guaranteed to exist for every SKU.

`static/catalogue/catalogue-image-manifest.json` records each successfully cached product image and its source. Photo files are normalized WEBP. Filenames are keyed to a stable barcode/product key, and URLs include a content revision so browsers can pick up an updated photo. Product photo bytes are also stored in the persistent database when they fit the configured cache limit.

The pipeline skips reused URLs shared across different SKUs and never creates fake/generic product artwork. Unknown items show a neutral “Photo being added” state. Photo acquisition runs during the Render build, not in the customer-facing page request.

The GitHub Actions workflow remains available to refresh/commit any verified images. Before commercial publication, review the chosen source's licence and attribution requirements.
