# Denmart real catalogue image cache

Denmart does not bundle fake product illustrations. Product images are acquired at build time and stored locally under `static/catalogue/products/NNN/`, with 100-product batches.

The first 500 high-expectation products are prioritised into batches `001`–`005`. The remaining catalogue is reserved in `006`–`014`.

A photo is accepted only when its source can be tied to the requested product identity. The pipeline refuses cross-product reuse and records misses as `pending_real_photo`. The public storefront never performs an image search at runtime.

The browser service worker uses a dedicated same-origin image cache so a successfully downloaded photo remains available after temporary network loss.
