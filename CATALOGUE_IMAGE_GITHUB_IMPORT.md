# Denmart real product photo import

The product-photo cache is organised into `static/catalogue/products/001` … `014`, with a maximum of 100 photo files per folder. The first 500 catalogue SKUs are prioritised into `001`–`005`; the remaining catalogue is reserved in `006`–`014`.

Image files use the product's unique barcode as the filename. `data/catalogue_image_priority.json` contains the 500 prioritised products, while `static/catalogue/catalogue-image-manifest.json` binds each product id to its expected local file.

`.github/workflows/cache-catalogue-images.yml` downloads **real product photographs only**. It tries exact curated sources first, then Open Food Facts-family data, then exact product pages on Kenyan retail sites. Each accepted source must match the requested brand/name/pack-size identity. One source URL cannot be assigned to another product.

There are intentionally **no fake/generated product images in the repository**. A product without a verified photo stays `pending_real_photo`, and the public site displays a neutral card naming that exact product instead of showing another product.

Run **Actions → Cache real Denmart product photos → Run workflow** in GitHub. The default is the first 500 priority products. Verified photos are written into the matching 100-file batch folders and committed back to the repository.

The Render build runs the same real-photo-only downloader before starting the app. Customer browsing never performs live image searches.
