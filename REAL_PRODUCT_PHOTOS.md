# Denmart real product photos

The photo pipeline only accepts image files downloaded from a curated product source, a product-data provider, or a retailer page after identity checks. It does not generate pretend product packaging. An unverified photo remains pending and the storefront shows an honest neutral placeholder.

## Priority and build

`data/catalogue_image_priority.json` lists 500 priority SKUs. Render attempts real-photo discovery for the first 350 during deployment, then reuses database/local photos and may make up to 250 additional source downloads for other catalogue items. These are targets, not guaranteed results; actual coverage depends on verifiable reachable sources. The site itself is kept responsive because the search/download work runs in the build rather than while customers browse.

The optional GitHub workflow can be run from **Actions → Cache real Denmart product photos → Run workflow** to generate and commit available images. Files are normalized to WebP and referenced from the image manifest. The database keeps compact image bytes where practical, so they can be regenerated in a later Render deployment even if a generated static folder is not in the repository.

Source URL, match score and provider are recorded where available. Reused source URLs are not assigned across different SKUs, preventing wrong pack sizes/flavours from borrowing one product's photograph. Check source-site licensing and attribution requirements before commercial use.
