# Denmart storefront speed and product photo upgrade

This update is deliberately scoped to the public storefront and the photo cache. It preserves the existing POS, stock, payments, admin and ordering flows.

## What changed
- The home page now has a proper supermarket hero, catalogue count, shop CTA and retained QR entry point.
- Product cards use a larger image area, a 4-column desktop layout and a 2-column mobile layout. The first images are eager/high-priority; the rest remain lazy loaded.
- Generic bottle/box/tube illustration files are not classified or displayed as real product photos. A missing photo is labelled honestly rather than shown as a fake pack shot.
- Render's build acquires/normalizes real product photos for up to 350 prioritized products, then caches/reuses available local and database photos. It can cache up to 250 additional external-source downloads per build. These operations run during deployment, never during each storefront request.
- The build process keeps a compressed photo copy in the persistent database where practical and preserves existing gallery/upload rows instead of deleting them. Stable local WEBP files are also generated.
- The browser service worker uses cache-first handling for images and retains up to 1,800 images; a cache hit no longer triggers an external re-download on every visit. The browser may still evict storage on its own, so persistence is requested where supported.
- Reused source URLs assigned to different SKUs are treated as ambiguous and are not blindly reused for multiple pack sizes.

## Deploy note
The actual photo acquisition requires Render's build environment to reach the upstream product image sources. The editing sandbox could not access those upstream hosts, so the zip does not claim to include hundreds of downloaded photographs already. Deploy this project through Render to run the configured acquisition/cache steps. Availability and source coverage vary by product; missing products will show a neutral “Photo being added” panel rather than false imagery.
