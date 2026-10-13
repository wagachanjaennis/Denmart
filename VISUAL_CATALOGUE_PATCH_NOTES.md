# Denmart visual catalogue patch — 13 October 2026

This incremental patch is meant to be overlaid on the existing repository (and includes the prior upgrade-patch files present in this working patch). It does not replace the database or remove application modules.

Changes:
- The public homepage begins with only **Shop now** and the QR code; the repeated popular-aisle chips, large slogan and long introductory text are removed. The store name/logo continue to appear in the shared header.
- The category sidebar stays available on desktop and becomes a compact horizontal, scrollable department rail on phones. A sidebar advert can still be configured in Admin.
- The homepage puts the available online catalogue immediately below the compact shop actions and lets customers scroll through the full current range (up to the existing 2,000-item query cap). Product cards use three columns on normal phones and two only on very narrow screens.
- The visual palette now uses a bright fresh green with yellow/coral details. Storefront body text uses a simpler system sans-serif font; section headings use a restrained handwriting-style font where available.
- Denmart is the default branding if the saved brand is blank or the legacy default “Toror Mart.” A deliberately configured new name is retained. Public title, description, Open Graph, Twitter and OnlineStore metadata use the current display name. Google may take time to recrawl the page before its search result updates.
- Product-image rendering preserves explicitly stored HTTP/data URLs, verifies local cached files, reuses available legacy verified photos if a CDN is unavailable, and suppresses known duplicate SKU photos. The Render blueprint runs the cache builder with a short network timeout and parallel downloads of the existing curated, exact-product sources. It does not change product prices, inventory, sales or the product database.

**Photo coverage limitation:** the supplied repository contains about 1,319 catalogue records but only 130 curated exact-product image sources, and just a small subset of those sources were already cached in the archive. The patch improves the display and caching of existing exact images, including database-saved image URLs, but cannot honestly provide a distinct verified pack photo for every SKU without more exact image sources or admin-uploaded photos. It deliberately avoids reusing the wrong pack size or making a generic graphic look like the actual product.

Validation: Python syntax parsing and Jinja template parsing passed in the working copy. A live Flask/Render deployment and a live Google recrawl were not performed in this environment.
